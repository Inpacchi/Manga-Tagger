import logging
import time
from datetime import datetime
from os import path
from pathlib import Path
from requests.exceptions import ConnectionError
from xml.etree.ElementTree import SubElement, Element, Comment, tostring
from xml.dom.minidom import parseString
from zipfile import ZipFile

from jikanpy.exceptions import APIException

from MangaTaggerLib._version import __version__
from MangaTaggerLib.api import MTJikan, AniList
from MangaTaggerLib.database import MangaTable, FilesTable
from MangaTaggerLib.errors import FileAlreadyProcessedError, FileUpdateNotRequiredError, UnparsableFilenameError, \
    MangaNotFoundError, MangaMatchedException
from MangaTaggerLib.models import Metadata
from MangaTaggerLib.task_queue import QueueWorker
from MangaTaggerLib.utils import AppSettings, compare

# Global Variable Declaration
LOG = logging.getLogger('MangaTaggerLib.MangaTaggerLib')

# CURRENTLY_PENDING_DB_SEARCH = set()
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
    file_id = None
    filename = file_path.name
    directory_path = file_path.parent
    directory_name = file_path.parent.name

    logging_info = {
        'event_id': event_id,
        'manga_title': directory_name,
        "original_filename": filename
    }

    LOG.info(f'Now processing "{file_path}"...')

    LOG.debug(f'filename: {filename}')
    LOG.debug(f'directory_path: {directory_path}')
    LOG.debug(f'directory_name: {directory_name}')

    manga_details = file_renamer(filename, logging_info)

    try:
        new_filename = manga_details[0]
        LOG.debug(f'new_filename: {new_filename}')
    except TypeError:
        LOG.warning(f'Manga Tagger was unable to process "{file_path}"')
        return None

    manga_library_dir = Path(AppSettings.library_dir, directory_name)
    LOG.debug(f'Manga Library Directory: {manga_library_dir}')

    if not manga_library_dir.exists():
        LOG.info(f'A directory for "{directory_name}" in "{AppSettings.library_dir}" does not exist; creating now.')
        manga_library_dir.mkdir()

    new_file_path = Path(manga_library_dir, new_filename)
    LOG.debug(f'new_file_path: {new_file_path}')

    LOG.info(f'Checking for current and previously processed files with filename "{new_filename}"...')

    if AppSettings.mode_settings is None or AppSettings.mode_settings['rename_file']:
        try:
            # Multithreading Optimization
            if new_file_path in CURRENTLY_PENDING_RENAME:
                LOG.info(f'A file is currently being renamed under the filename "{new_filename}". Locking '
                         f'{file_path} from further processing until this rename action is complete...')

                while new_file_path in CURRENTLY_PENDING_RENAME:
                    time.sleep(1)

                LOG.info(f'The file being renamed to "{new_file_path}" has been completed. Unlocking '
                         f'"{new_filename}" for file rename processing.')
            else:
                LOG.info(f'No files currently currently being processed under the filename '
                         f'"{new_filename}". Locking new filename for processing...')
                CURRENTLY_PENDING_RENAME.add(new_file_path)

            file_id = rename_action(file_path, new_file_path, directory_name, manga_details[1], logging_info)
        except (FileExistsError, FileUpdateNotRequiredError, FileAlreadyProcessedError) as e:
            LOG.exception(e)
            CURRENTLY_PENDING_RENAME.remove(new_file_path)
            return

    metadata_tagger(directory_name, manga_details[1], logging_info, file_id, new_file_path)
    LOG.info(f'Processing on "{new_file_path}" has finished.')


def tag_manga_chapter(file_id):
    result = FilesTable.get_by_id(file_id)

    filename = result['new_filename']
    directory_name = result['series_title']

    logging_info = {
        'file_id': file_id,
        'manga_title': directory_name,
        "filename": filename
    }

    LOG.info(f'Adding meta data to file id: {file_id}.')

    manga_library_dir = Path(AppSettings.library_dir, directory_name)
    LOG.debug(f'Manga Library Directory: {manga_library_dir}')
    new_file_path = Path(manga_library_dir, filename)
    LOG.debug(f'new_file_path: {new_file_path}')

    metadata_tagger(directory_name, result['chapter_number'], logging_info, file_id, new_file_path)
    LOG.info(f'Processing on "{new_file_path}" has finished.')


def file_renamer(filename, logging_info):
    LOG.info(f'Attempting to rename "{filename}"...')

    # Parse the manga title and chapter name/number (this depends on where the manga is downloaded from)
    try:
        if filename.find('-.-') == -1:
            raise UnparsableFilenameError(filename, '-.-')

        filename = filename.split(' -.- ')
        LOG.info(f'Filename was successfully parsed as {filename}.')
    except UnparsableFilenameError as ufe:
        LOG.exception(ufe)
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

        if 'vol' in chapter_title:
            delimiter = 'vol'
            delimiter_index = 3
        elif 'chapter' in chapter_title:
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
        LOG.exception(ufe)
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
    chapter_title = chapter_title.replace(' ', '')
    LOG.debug(f'chapter_title: {chapter_title}')
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

    LOG.info(f'File will be renamed to "{filename}".')

    return filename, chapter_number


def rename_action(current_file_path: Path, new_file_path: Path, manga_title, chapter_number, logging_info):
    chapter_number = chapter_number.replace('.', '-')
    results = FilesTable.search(manga_title, chapter_number)
    LOG.debug(f'Results: {results}')

    # If the series OR the chapter has not been processed
    if results is None:
        LOG.info(f'"{manga_title}" chapter {chapter_number} has not been processed before. '
                 f'Proceeding with file rename...')
        file_id = FilesTable.insert_record_and_rename(current_file_path, new_file_path, manga_title, chapter_number,
                                                      logging_info)
    else:
        file_id = results['file_id']
        versions = ['v2', 'v3', 'v4', 'v5']

        existing_old_filename = results['old_filename']
        existing_current_filename = results['new_filename']

        # If currently processing file has the same name as an existing file
        if existing_current_filename == new_file_path.name:
            # Check if file was processed successfully
            if results['processed_date'] is None:
                LOG.info(f'File previously failed to renamed, trying again.')
                FilesTable.update_record_and_rename(results, current_file_path, new_file_path, logging_info)
            # If currently processing file has a version in its filename
            elif any(version in current_file_path.name.lower() for version in versions):
                # If the version is newer than the existing file
                if compare_versions(existing_old_filename, current_file_path.name):
                    LOG.info(f'Newer version of "{manga_title}" chapter {chapter_number} has been found. Deleting '
                             f'existing file and proceeding with file rename...')
                    new_file_path.unlink()
                    LOG.info(f'"{new_file_path.name}" has been deleted! Proceeding to rename new file...')
                    FilesTable.update_record_and_rename(results, current_file_path, new_file_path, logging_info)
                else:
                    LOG.warning(f'"{current_file_path.name}" was not renamed due being the exact same as the '
                                f'existing chapter; file currently being processed will be deleted')
                    current_file_path.unlink()
                    raise FileUpdateNotRequiredError(current_file_path.name)
            # If the current file doesn't have a version in it's filename, but the existing file does
            elif any(version in existing_old_filename.lower() for version in versions):
                LOG.warning(f'"{current_file_path.name}" was not renamed due to not being an updated version '
                            f'of the existing chapter; file currently being processed will be deleted')
                current_file_path.unlink()
                raise FileUpdateNotRequiredError(current_file_path.name)
            # If all else fails
            else:
                LOG.warning(f'No changes have been found for "{existing_current_filename}"; file currently being '
                            f'processed will be deleted')
                current_file_path.unlink()
                raise FileAlreadyProcessedError(current_file_path.name)

    LOG.info(f'"{new_file_path.name}" will be unlocked for any pending processes.')
    CURRENTLY_PENDING_RENAME.remove(new_file_path)

    return file_id


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


def metadata_tagger(manga_title, manga_chapter_number, logging_info, file_id, manga_file_path=None):
    db_exists = True

    LOG.info(f'Table search value is "{manga_title} and file id is "{file_id}"')
    manga_search = MangaTable.search(manga_title)
    if manga_search is None:
        LOG.info('Manga was not found in the database; resorting to Jikan API.')
        while manga_search is None:
            try:
                manga_search = MTJikan().search('manga', manga_title)
            except (APIException, ConnectionError) as e:
                LOG.warning(e)
                LOG.warning('Manga Tagger has unintentionally breached the API limits on Jikan. Waiting 60s to clear '
                            'all rate limiting limits...')
                time.sleep(60)
                manga_search = MTJikan().search('manga', manga_title)
        db_exists = False

        LOG.debug(f"API Results for {manga_title}: {manga_search}")

    if db_exists:
        manga_id = manga_search['manga_id']
        manga_metadata = Metadata(manga_title, logging_info, details=manga_search)
        logging_info['metadata'] = manga_metadata.__dict__
    else:
        manga_found = False
        try:
            for result in manga_search['data']:
                if result['type'].lower() == 'manga' or result['type'].lower() == 'one-shot':
                    mal_id = result['mal_id']
                    anilist_results = AniList.search_for_manga_title_by_mal_id(mal_id, logging_info)
                    if anilist_results is None:
                        continue
                    anilist_titles = construct_anilist_titles(anilist_results['title'])
                    logging_info['anilist_titles'] = anilist_titles

                    try:
                        jikan_details = MTJikan().manga(mal_id)
                    except (APIException, ConnectionError) as e:
                        LOG.warning(e)
                        LOG.warning(
                            'Manga Tagger has unintentionally breached the API limits on Jikan. Waiting 60s to clear '
                            'all rate limiting limits...')
                        time.sleep(60)
                        jikan_details = MTJikan().manga(mal_id)

                    jikan_titles = construct_jikan_titles(jikan_details['data'])
                    logging_info['jikan_titles'] = jikan_titles

                    LOG.info(f'Comparing titles found for "{manga_title}"...')
                    comparison_values = compare_titles(manga_title, jikan_titles, anilist_titles, logging_info)

                    if comparison_values is None:
                        continue
                    elif any(value > .8 for value in comparison_values):
                        LOG.info(f'Match found for {manga_title}')
                        manga_found = True
                        break
                    elif any(value > .5 for value in comparison_values):
                        jikan_details = MTJikan().manga(mal_id)
                        jikan_authors = jikan_details['authors']
                        anilist_authors = AniList.search_staff_by_mal_id(mal_id,
                                                                         logging_info)['staff']['edges']

                        logging_info['jikan_authors'] = jikan_authors
                        logging_info['anilist_authors'] = anilist_authors

                        LOG.info(f'Match found for {manga_title} with 50% likelihood; now checking '
                                 f'authors for further veritifcation')

                        if compare_authors(jikan_authors, anilist_authors, logging_info):
                            LOG.info(f'Authors matched up for {manga_title}; proceeding with processing')
                            manga_found = True
                            break
            if not manga_found:
                raise MangaNotFoundError(manga_title)
        except MangaNotFoundError as mnfe:
            LOG.exception(mnfe)
            return

        LOG.info(f'ID for "{manga_title}" found as "{mal_id}".')

        anilist_details = AniList.search_staff_by_mal_id(mal_id, logging_info)
        LOG.debug(f'jikan_details: {jikan_details}')
        LOG.debug(f'anilist_details: {anilist_details}')

        manga_metadata = Metadata(manga_title, logging_info, jikan_details['data'], anilist_details)
        logging_info['metadata'] = manga_metadata.__dict__

        if AppSettings.mode_settings is None or ('database_insert' in AppSettings.mode_settings.keys()
                                                 and AppSettings.mode_settings['database_insert']):
            manga_id = MangaTable.insert(manga_metadata, logging_info)
            manga_metadata.manga_id = manga_id


        LOG.info(f'Retrieved metadata for "{manga_title}" from the Anilist and MyAnimeList APIs; '
                 f'now unlocking series for processing!')

    if AppSettings.mode_settings is None or ('write_comicinfo' in AppSettings.mode_settings.keys()
                                             and AppSettings.mode_settings['write_comicinfo']):
        comicinfo_xml = construct_comicinfo_xml(manga_metadata, manga_chapter_number, logging_info)
        reconstruct_manga_chapter(comicinfo_xml, manga_file_path, logging_info)

    FilesTable.add_manga_id(file_id, manga_id)
    FilesTable.add_tagged_date(file_id)
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
    LOG.debug(f'pre_comparison_values: {comparison_values}')

    if not any(value > .69 for value in comparison_values):
        return None

    comparison_values = []

    for jikan_key in jikan_titles.keys():
        for anilist_key in anilist_titles.keys():
            comparison_values.append(compare(jikan_titles[jikan_key], anilist_titles[anilist_key]))

    logging_info['post_comparison_values'] = comparison_values
    LOG.debug(f'post_comparison_values: {comparison_values}')

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
    LOG.info(f'Constructing comicinfo object for "{metadata.series_title}", chapter {chapter_number}...')

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

    publish_date = datetime.strptime(metadata.publish_date, '%Y-%m-%d').date()
    year = SubElement(comicinfo, 'Year')
    year.text = f'{publish_date.year}'

    month = SubElement(comicinfo, 'Month')
    month.text = f'{publish_date.month}'

    writer = SubElement(comicinfo, 'Writer')
    writer.text = next(iter(metadata.staff['story']))

    penciller = SubElement(comicinfo, 'Penciller')
    penciller.text = next(iter(metadata.staff['art']))

    inker = SubElement(comicinfo, 'Inker')
    inker.text = next(iter(metadata.staff['art']))

    colorist = SubElement(comicinfo, 'Colorist')
    colorist.text = next(iter(metadata.staff['art']))

    letterer = SubElement(comicinfo, 'Letterer')
    letterer.text = next(iter(metadata.staff['art']))

    cover_artist = SubElement(comicinfo, 'CoverArtist')
    cover_artist.text = next(iter(metadata.staff['art']))

    publisher = SubElement(comicinfo, 'Publisher')
    publisher.text = next(iter(metadata.serializations))

    genre = SubElement(comicinfo, 'Genre')
    for mg in metadata.genres:
        if genre.text is not None:
            genre.text += f',{mg}'
        else:
            genre.text = f'{mg}'

    web = SubElement(comicinfo, 'Web')
    web.text = metadata.mal_url

    language = SubElement(comicinfo, 'LanguageISO')
    language.text = 'en'

    manga = SubElement(comicinfo, 'Manga')
    manga.text = 'Yes'

    notes = SubElement(comicinfo, 'Notes')
    notes.text = f'Scraped metadata from AniList and MyAnimeList (using Jikan API) on {metadata.scrape_date}'

    comicinfo.set('xmlns:xsd', 'http://www.w3.org/2001/XMLSchema')
    comicinfo.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

    LOG.info(f'Finished creating ComicInfo object for "{metadata.series_title}", chapter {chapter_number}.')
    return parseString(tostring(comicinfo)).toprettyxml(indent="   ")


def reconstruct_manga_chapter(comicinfo_xml, manga_file_path, logging_info):
    try:
        with ZipFile(manga_file_path, 'a') as zipfile:
            zipfile.writestr('ComicInfo.xml', comicinfo_xml)
    except Exception as e:
        LOG.exception(e)
        LOG.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.')
        return

    LOG.info(f'ComicInfo.xml has been created and appended to "{manga_file_path}".')
