import logging
import os
import shutil
import time
from datetime import datetime
from os import path
from pathlib import Path

import pymanga
from requests.exceptions import ConnectionError
from xml.etree.ElementTree import SubElement, Element, Comment, tostring
from xml.dom.minidom import parseString
from zipfile import ZipFile

from jikanpy.exceptions import APIException

from MangaTaggerLib._version import __version__
from MangaTaggerLib.api import MTJikan, AniList, Kitsu, MangaUpdates, NH, Fakku
from MangaTaggerLib.database import MetadataTable, ProcFilesTable, ProcSeriesTable
from MangaTaggerLib.errors import FileAlreadyProcessedError, FileUpdateNotRequiredError, UnparsableFilenameError, \
    MangaNotFoundError, MangaMatchedException
from MangaTaggerLib.models import Metadata, Data
from MangaTaggerLib.task_queue import QueueWorker
from MangaTaggerLib.utils import AppSettings, compare

# Global Variable Declaration
LOG = logging.getLogger('MangaTaggerLib.MangaTaggerLib')

CURRENTLY_PENDING_DB_SEARCH = set()
CURRENTLY_PENDING_RENAME = set()


def main():
    AppSettings.load()

    LOG.info(f'Starting Manga Tagger - Version {__version__}')
    LOG.debug('RUNNING IN DEBUG MODE')

    if AppSettings.mode_settings is not None:
        LOG.info('DRY RUN MODE ENABLED')
        LOG.info(f"MetadataTable Insertion: {AppSettings.mode_settings['database_insert']}")
        LOG.info(f"Renaming Files: {AppSettings.mode_settings['rename_file']}")
        LOG.info(f"Writing Comicinfo.xml: {AppSettings.mode_settings['write_comicinfo']}")

    QueueWorker.run()


def process_manga_chapter(file_path: Path, event_id):
    filename = file_path.name
    directory_path = file_path.parent
    directory_name = file_path.parent.name

    logging_info = {
        'event_id': event_id,
        'manga_title': directory_name,
        "original_filename": filename
    }

    LOG.info(f'Now processing "{file_path}"...', extra=logging_info)

    LOG.debug(f'filename: {filename}')
    LOG.debug(f'directory_path: {directory_path}')
    LOG.debug(f'directory_name: {directory_name}')

    manga_details = file_renamer(filename, logging_info)

    try:
        new_filename = manga_details[0]
        LOG.debug(f'new_filename: {new_filename}')
    except TypeError:
        LOG.warning(f'Manga Tagger was unable to process "{file_path}"', extra=logging_info)
        return None

    manga_library_dir = Path(AppSettings.library_dir, directory_name)
    LOG.debug(f'Manga Library Directory: {manga_library_dir}')

    if not manga_library_dir.exists():
        LOG.info(f'A directory for "{directory_name}" in "{AppSettings.library_dir}" does not exist; creating now.')
        manga_library_dir.mkdir()

    new_file_path = Path(manga_library_dir, new_filename)
    LOG.debug(f'new_file_path: {new_file_path}')

    LOG.info(f'Checking for current and previously processed files with filename "{new_filename}"...',
             extra=logging_info)

    if AppSettings.mode_settings is None or AppSettings.mode_settings['rename_file']:
        try:
            # Multithreading Optimization
            if new_file_path in CURRENTLY_PENDING_RENAME:
                LOG.info(f'A file is currently being renamed under the filename "{new_filename}". Locking '
                         f'{file_path} from further processing until this rename action is complete...',
                         extra=logging_info)

                while new_file_path in CURRENTLY_PENDING_RENAME:
                    time.sleep(1)

                LOG.info(f'The file being renamed to "{new_file_path}" has been completed. Unlocking '
                         f'"{new_filename}" for file rename processing.', extra=logging_info)
            else:
                LOG.info(f'No files currently currently being processed under the filename '
                         f'"{new_filename}". Locking new filename for processing...', extra=logging_info)
                CURRENTLY_PENDING_RENAME.add(new_file_path)

            rename_action(file_path, new_file_path, directory_name, manga_details[1], logging_info)
        except (FileExistsError, FileUpdateNotRequiredError, FileAlreadyProcessedError) as e:
            LOG.exception(e, extra=logging_info)
            CURRENTLY_PENDING_RENAME.remove(new_file_path)
            return

    # More Multithreading Optimization
    if directory_name in ProcSeriesTable.processed_series:
        LOG.info(f'"{directory_name}" has been processed as a searched series and will continue processing.',
                 extra=logging_info)
    else:
        if directory_name in CURRENTLY_PENDING_DB_SEARCH:
            LOG.info(f'"{directory_name}" has not been processed as a searched series but is currently pending '
                     f'a database search. Suspending further processing until database search has finished...',
                     extra=logging_info)

            while directory_name in CURRENTLY_PENDING_DB_SEARCH:
                time.sleep(1)

            LOG.info(f'"{directory_name}" has been processed as a searched series and will now be unlocked for '
                     f'processing.', extra=logging_info)
        else:
            LOG.info(f'"{directory_name}" has not been processed as a searched series nor is it currently pending '
                     f'a database search. Locking series from being processing until database has been searched...',
                     extra=logging_info)
            CURRENTLY_PENDING_DB_SEARCH.add(directory_name)

    metadata_tagger(directory_name, manga_details[1], logging_info, new_file_path)
    LOG.info(f'Processing on "{new_file_path}" has finished.', extra=logging_info)


def file_renamer(filename, logging_info):
    LOG.info(f'Attempting to rename "{filename}"...', extra=logging_info)

    # Parse the manga title and chapter name/number (this depends on where the manga is downloaded from)
    try:
        if filename.find('-.-') == -1:
            raise UnparsableFilenameError(filename, '-.-')

        filename = filename.split(' -.- ')
        LOG.info(f'Filename was successfully parsed as {filename}.', extra=logging_info)
    except UnparsableFilenameError as ufe:
        LOG.exception(ufe, extra=logging_info)
        return None

    manga_title: str = filename[0]
    chapter_title: str = path.splitext(filename[1].lower())[0]
    LOG.debug(f'manga_title: {manga_title}')
    LOG.debug(f'chapter: {chapter_title}')

    # If "chapter" is in the chapter substring
    try:
        if manga_title.lower() in chapter_title:
            if compare(manga_title, chapter_title) > .5 and compare(manga_title, chapter_title[:len(manga_title)]) > .8:
                raise MangaMatchedException()

        if 'oneshot' in path.splitext(filename[1].lower())[0]:
            LOG.debug(f'manga_type: oneshot')
            return f'{manga_title} {path.splitext(filename[1])[0]}.cbz', 'oneshot'

        chapter_title = chapter_title.replace(' ', '')

        if 'chapter' in chapter_title:
            delimiter = 'chapter'
            delimiter_index = 7
        elif 'ch.' in chapter_title:
            delimiter = 'ch.'
            delimiter_index = 3
        elif 'ch' in chapter_title:
            delimiter = 'ch'
            delimiter_index = 2
        elif 'act' in chapter_title:
            delimiter = 'act'
            delimiter_index = 3
        else:
            raise UnparsableFilenameError(filename, 'ch/chapter')
    except UnparsableFilenameError as ufe:
        LOG.exception(ufe, extra=logging_info)
        return None
    except MangaMatchedException:
        if 'chapter' in chapter_title:
            chapter_title = chapter_title.replace(' ', '')
            delimiter = f'{manga_title.lower()}chapter'
            delimiter_index = len(delimiter) + 1
        else:
            delimiter = manga_title.lower()
            delimiter_index = len(delimiter) + 1

    LOG.debug(f'delimiter: {delimiter}')
    LOG.debug(f'delimiter_index: {delimiter_index}')

    i = chapter_title.index(delimiter) + delimiter_index
    LOG.debug(f'Iterator i: {i}')
    LOG.debug(f'Length: {len(chapter_title)}')

    chapter_number = ''
    while i < len(chapter_title):
        substring = chapter_title[i]
        LOG.debug(f'substring: {substring}')

        if substring.isdigit() or substring == '.':
            chapter_number += chapter_title[i]
            i += 1

            LOG.debug(f'chapter_number: {chapter_number}')
            LOG.debug(f'Iterator i: {i}')
        else:
            break

    if chapter_number.find('.') == -1:
        chapter_number = chapter_number.zfill(3)
    else:
        chapter_number = chapter_number.zfill(5)

    filename = f'{manga_title} {chapter_number}.cbz'

    LOG.debug(f'chapter_number: {chapter_number}')

    logging_info['chapter_number'] = chapter_number
    logging_info['new_filename'] = filename

    LOG.info(f'File will be renamed to "{filename}".', extra=logging_info)

    return filename, chapter_number


def rename_action(current_file_path: Path, new_file_path: Path, manga_title, chapter_number, logging_info):
    chapter_number = chapter_number.replace('.', '-')
    results = ProcFilesTable.search(manga_title, chapter_number)
    LOG.debug(f'Results: {results}')

    # If the series OR the chapter has not been processed
    if results is None:
        LOG.info(f'"{manga_title}" chapter {chapter_number} has not been processed before. '
                 f'Proceeding with file rename...', extra=logging_info)
        ProcFilesTable.insert_record_and_rename(current_file_path, new_file_path, manga_title, chapter_number,
                                                logging_info)
    else:
        versions = ['v2', 'v3', 'v4', 'v5']

        existing_old_filename = results['old_filename']
        existing_current_filename = results['new_filename']

        # If currently processing file has the same name as an existing file
        if existing_current_filename == new_file_path.name:
            # If currently processing file has a version in it's filename
            if any(version in current_file_path.name.lower() for version in versions):
                # If the version is newer than the existing file
                if compare_versions(existing_old_filename, current_file_path.name):
                    LOG.info(f'Newer version of "{manga_title}" chapter {chapter_number} has been found. Deleting '
                             f'existing file and proceeding with file rename...', extra=logging_info)
                    new_file_path.unlink()
                    LOG.info(f'"{new_file_path.name}" has been deleted! Proceeding to rename new file...',
                             extra=logging_info)
                    ProcFilesTable.update_record_and_rename(results, current_file_path, new_file_path, logging_info)
                else:
                    LOG.warning(f'"{current_file_path.name}" was not renamed due being the exact same as the '
                                f'existing chapter; file currently being processed will be deleted',
                                extra=logging_info)
                    current_file_path.unlink()
                    raise FileUpdateNotRequiredError(current_file_path.name)
            # If the current file doesn't have a version in it's filename, but the existing file does
            elif any(version in existing_old_filename.lower() for version in versions):
                LOG.warning(f'"{current_file_path.name}" was not renamed due to not being an updated version '
                            f'of the existing chapter; file currently being processed will be deleted',
                            extra=logging_info)
                current_file_path.unlink()
                raise FileUpdateNotRequiredError(current_file_path.name)
            # If all else fails
            else:
                LOG.warning(f'No changes have been found for "{existing_current_filename}"; file currently being '
                            f'processed will be deleted', extra=logging_info)
                current_file_path.unlink()
                raise FileAlreadyProcessedError(current_file_path.name)

    LOG.info(f'"{new_file_path.name}" will be unlocked for any pending processes.', extra=logging_info)
    CURRENTLY_PENDING_RENAME.remove(new_file_path)


def compare_versions(old_filename: str, new_filename: str):
    old_version = 0
    new_version = 0

    LOG.debug('Preprocessing')
    LOG.debug(f'Old Version: {old_version}')
    LOG.debug(f'New Version: {new_version}')

    if 'v2' in old_filename.lower():
        old_version = 2
    elif 'v3' in old_filename.lower():
        old_version = 3
    elif 'v4' in old_filename.lower():
        old_version = 4
    elif 'v5' in old_filename.lower():
        old_version = 5

    if 'v2' in new_filename.lower():
        new_version = 2
    elif 'v3' in new_filename.lower():
        new_version = 3
    elif 'v4' in new_filename.lower():
        new_version = 4
    elif 'v5' in new_filename.lower():
        new_version = 5

    LOG.debug('Postprocessing')
    LOG.debug(f'Old Version: {old_version}')
    LOG.debug(f'New Version: {new_version}')

    if new_version > old_version:
        return True
    else:
        return False


def metadata_tagger(manga_title, manga_chapter_number, logging_info, manga_file_path=None):
    manga_search = None
    db_exists = False

    LOG.info(f'Table search value is "{manga_title}"', extra=logging_info)

    for x in range(4):
        manga_search = dbSearch(manga_title, x)
        if manga_search is not None:
            db_exists = True
            break
    # Metadata already exists
    if db_exists:
        if manga_title in ProcSeriesTable.processed_series:
            LOG.info(f'Found an entry in manga_metadata for "{manga_title}".', extra=logging_info)
        else:
            LOG.info(f'Found an entry in manga_metadata for "{manga_title}"; unlocking series for processing.',
                     extra=logging_info)
            ProcSeriesTable.processed_series.add(manga_title)
            CURRENTLY_PENDING_DB_SEARCH.remove(manga_title)

        manga_metadata = Metadata(manga_title, logging_info, db_details=manga_search)
        logging_info['metadata'] = manga_metadata.__dict__
    # Get metadata
    else:
        sources = {
            "MAL": MTJikan(),
            "AniList": AniList(),
            "MangaUpdates": MangaUpdates(),
            "NHentai": NH(),
            "Fakku": Fakku()}
        # sources["Kitsu"] = Kitsu
        preferences = ["AniList", "MangaUpdates", "MAL", "Fakku", "NHentai"]
        results = {}
        metadata = None
        results["MAL"] = sources["MAL"].search('manga', manga_title)
        results["AniList"] = sources["AniList"].search(manga_title, logging_info)
        results["MangaUpdates"] = sources["MangaUpdates"].search(manga_title)
        results["NHentai"] = sources["NHentai"].search(manga_title)
        results["Fakku"] = sources["Fakku"].search(manga_title)
        try:
            for source in preferences:
                for result in results[source]:
                    if source == "AniList":
                        # Construct Anilist XML
                        titles = [x[1] for x in result["title"].items() if x[1] is not None]
                        [titles.append(x) for x in result["synonyms"]]
                        for title in titles:
                            if compare(manga_title, title) >= 0.9:
                                manga = sources["AniList"].manga(result["id"], logging_info)
                                manga["source"] = "AL"
                                metadata = Data(manga, manga_title)
                                raise MangaMatchedException("Found a match")
                    elif source == "MangaUpdates":
                        # Construct MangaUpdates XML
                        if compare(manga_title, result['title']) >= 0.9:
                            manga = sources["MangaUpdates"].series(result["id"])
                            manga["source"] = "MangaUpdates"
                            metadata = Data(manga, manga_title, result["id"])
                            raise MangaMatchedException("Found a match")
                    elif source == "MAL":
                        if compare(manga_title, result['title']) >= 0.9:
                            try:
                                manga = sources["MAL"].manga(result["mal_id"])
                            except (APIException, ConnectionError) as e:
                                LOG.warning(e, extra=logging_info)
                                LOG.warning(
                                    'Manga Tagger has unintentionally breached the API limits on Jikan. Waiting 60s to clear '
                                    'all rate limiting limits...')
                                time.sleep(60)
                                manga = MTJikan().manga(result["mal_id"])
                            manga["source"] = "MAL"
                            metadata = Data(manga, manga_title, result["mal_id"])
                            raise MangaMatchedException("Found a match")
                    elif source == "Fakku":
                        if result["success"]:
                            manga = sources["Fakku"].manga(result["url"])
                            manga["source"] = "Fakku"
                            metadata = Data(manga, manga_title)
                            raise MangaMatchedException("Found a match")
                    elif source == "NHentai":
                        if compare(manga_title, result["title"]):
                            manga = sources["NHentai"].manga(result["id"], result["title"])
                            manga["source"] = "NHentai"
                            metadata = Data(manga, manga_title, result["id"])
                            raise MangaMatchedException("Found a match")
        except MangaNotFoundError as mnfe:
            LOG.exception(mnfe, extra=logging_info)
            return
        except MangaMatchedException:
            pass

        manga_metadata = Metadata(manga_title, logging_info, details=metadata.toDict())
        logging_info['metadata'] = manga_metadata.__dict__

        if AppSettings.mode_settings is None or ('database_insert' in AppSettings.mode_settings.keys()
                                                 and AppSettings.mode_settings['database_insert']):
            MetadataTable.insert(manga_metadata, logging_info)

        LOG.info(f'Retrieved metadata for "{manga_title}" from the Anilist and MyAnimeList APIs; '
                 f'now unlocking series for processing!', extra=logging_info)
        ProcSeriesTable.processed_series.add(manga_title)
        CURRENTLY_PENDING_DB_SEARCH.remove(manga_title)

    if AppSettings.mode_settings is None or ('write_comicinfo' in AppSettings.mode_settings.keys()
                                             and AppSettings.mode_settings['write_comicinfo']):
        comicinfo_xml = construct_comicinfo_xml(manga_metadata, manga_chapter_number, logging_info)
        reconstruct_manga_chapter(comicinfo_xml[0], manga_file_path, comicinfo_xml[1], logging_info)

    return manga_metadata


def construct_jikan_titles(jikan_details):
    jikan_titles = {
        'title': jikan_details['title']
    }

    if jikan_details['title_english'] is not None:
        jikan_titles['title_english'] = jikan_details['title_english']

    if jikan_details['title_japanese'] is not None:
        jikan_titles['title_japanese'] = jikan_details['title_japanese']

    if not jikan_details['title_synonyms']:
        i = 1
        for title in jikan_details['title_synonyms']:
            jikan_titles[f'title_{i}'] = title
            i += 1

    return jikan_titles


def construct_anilist_titles(anilist_details):
    anilist_titles = {}

    if anilist_details['romaji'] is not None:
        anilist_titles['romaji'] = anilist_details['romaji']

    if anilist_details['english'] is not None:
        anilist_titles['english'] = anilist_details['english']

    if anilist_details['native'] is not None:
        anilist_titles['native'] = anilist_details['native']

    return anilist_titles


def compare_titles(manga_title: str, jikan_titles: dict, anilist_titles: dict, logging_info):
    comparison_values = []

    for jikan_key in jikan_titles.keys():
        comparison_values.append(compare(manga_title, jikan_titles[jikan_key]))

    for anilist_key in anilist_titles.keys():
        comparison_values.append(compare(manga_title, anilist_titles[anilist_key]))

    logging_info['pre_comparison_values'] = comparison_values
    LOG.debug(f'pre_comparison_values: {comparison_values}', extra=logging_info)

    if not any(value > .9 for value in comparison_values):
        return None

    comparison_values = []

    for jikan_key in jikan_titles.keys():
        for anilist_key in anilist_titles.keys():
            comparison_values.append(compare(jikan_titles[jikan_key], anilist_titles[anilist_key]))

    logging_info['post_comparison_values'] = comparison_values
    LOG.debug(f'post_comparison_values: {comparison_values}', extra=logging_info)
    return comparison_values


def compare_authors(jikan_authors, anilist_authors, logging_info):
    for author_1 in jikan_authors:
        if ',' in author_1['name']:
            full_name_split = author_1['name'].split(', ')
            author_1_name = f'{full_name_split[1]} {full_name_split[0]}'
        else:
            author_1_name = author_1['name']

        for author_2 in anilist_authors:
            if author_1_name == author_2['node']['name']['full']:
                return True
    return False


def construct_comicinfo_xml(metadata, chapter_number, logging_info):
    LOG.info(f'Constructing comicinfo object for "{metadata.series_title}", chapter {chapter_number}...',
             extra=logging_info)

    comicinfo = Element('ComicInfo')

    application_tag = Comment('Generated by Manga Tagger, an Endless Galaxy Studios project')
    comicinfo.append(application_tag)

    series = SubElement(comicinfo, 'Series')
    series.text = metadata.series_title

    if metadata.series_title_eng is not None and compare(metadata.series_title, metadata.series_title_eng) != 1:
        alt_series = SubElement(comicinfo, 'AlternateSeries')
        alt_series.text = metadata.series_title_eng

    number = SubElement(comicinfo, 'Number')
    number.text = f'{chapter_number}'

    summary = SubElement(comicinfo, 'Summary')
    summary.text = metadata.description

    if metadata.publish_date is not None:
        publish_date = datetime.strptime(metadata.publish_date, '%Y-%m-%d').date()
        year = SubElement(comicinfo, 'Year')
        year.text = f'{publish_date.year}'

        month = SubElement(comicinfo, 'Month')
        month.text = f'{publish_date.month}'

    else:
        year = SubElement(comicinfo, 'Year')
        year.text = None

        month = SubElement(comicinfo, 'Month')
        month.text = None

    writer = SubElement(comicinfo, 'Writer')
    writer.text = tryIter(metadata.staff['story'])

    penciller = SubElement(comicinfo, 'Penciller')
    penciller.text = tryIter(metadata.staff['art'])

    inker = SubElement(comicinfo, 'Inker')
    inker.text = tryIter(metadata.staff['art'])

    colorist = SubElement(comicinfo, 'Colorist')
    colorist.text = tryIter(metadata.staff['art'])

    letterer = SubElement(comicinfo, 'Letterer')
    letterer.text = tryIter(metadata.staff['art'])

    cover_artist = SubElement(comicinfo, 'CoverArtist')
    cover_artist.text = tryIter(metadata.staff['art'])

    publisher = SubElement(comicinfo, 'Publisher')
    publisher.text = tryIter(metadata.serializations)

    genre = SubElement(comicinfo, 'Genre')
    for mg in metadata.genres:
        if genre.text is not None:
            genre.text += f',{mg}'
        else:
            genre.text = f'{mg}'

    web = SubElement(comicinfo, 'Web')
    if metadata.anilist_url is not None:
        web.text = metadata.anilist_url
    elif metadata.mal_url is not None:
        web.text = metadata.mal_url
    else:
        web.text = "None"

    language = SubElement(comicinfo, 'LanguageISO')
    language.text = 'en'

    manga = SubElement(comicinfo, 'Manga')
    manga.text = 'Yes'

    notes = SubElement(comicinfo, 'Notes')
    notes.text = f'Scraped metadata from AniList and MyAnimeList (using Jikan API) on {metadata.scrape_date}'

    comicinfo.set('xmlns:xsd', 'http://www.w3.org/2001/XMLSchema')
    comicinfo.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

    hentai = False
    if metadata.source == "Fakku" or metadata.source == "NHentai":
        hentai = True

    LOG.info(f'Finished creating ComicInfo object for "{metadata.series_title}", chapter {chapter_number}.',
             extra=logging_info)
    return [parseString(tostring(comicinfo,short_empty_elements=False)).toprettyxml(indent="   "), hentai]


def reconstruct_manga_chapter(comicinfo_xml, manga_file_path, isHentai,logging_info):
    try:
        with ZipFile(manga_file_path, 'a') as zipfile:
            zipfile.writestr('ComicInfo.xml', comicinfo_xml)
    except Exception as e:
        LOG.exception(e, extra=logging_info)
        LOG.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.',
                    extra=logging_info)
        return
    if isHentai:
        dir = "\\".join(str(manga_file_path.absolute()).split("\\")[:-1])
        dirh = Path(dir.replace("Manga", "Hentai"))
        if not os.path.isdir(dirh):
            os.mkdir(dirh)
        shutil.move(manga_file_path, Path(str(manga_file_path.absolute()).replace("Manga", "Hentai")))
        os.remove(dir)

    LOG.info(f'ComicInfo.xml has been created and appended to "{manga_file_path}".', extra=logging_info)


def tryIter(x):
    if isinstance(x, str):
        return x
    if x is None:
        return "None"
    try:
        return next(iter(x))
    except StopIteration:
        return "None"


def dbSearch(string, mode):
    if mode == 0:
        return MetadataTable.search_by_search_value(string)
    elif mode == 1:
        return MetadataTable.search_by_series_title(string)
    elif mode == 2:
        return MetadataTable.search_by_series_title_eng(string)
