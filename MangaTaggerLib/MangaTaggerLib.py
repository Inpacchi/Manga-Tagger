import logging
import os
import requests
import time
from datetime import datetime
from ntpath import basename
from requests.exceptions import ConnectionError
from xml.etree.ElementTree import SubElement, Element, Comment, tostring
from xml.dom.minidom import parseString
from zipfile import ZipFile

from jikanpy.exceptions import APIException

from MangaTaggerLib.api import MTJikan
from MangaTaggerLib.database import MetadataTable, ProcFilesTable, ProcSeriesTable
from MangaTaggerLib.errors import FileAlreadyProcessedError, FileUpdateNotRequiredError, UnparsableFilenameError, \
    MangaNotFoundError
from MangaTaggerLib.models import Metadata
from MangaTaggerLib.task_queue import QueueWorker
from MangaTaggerLib.utils import AppSettings, compare

# Global Variable Declaration
LOG = logging.getLogger('MangaTaggerLib.MangaTaggerLib')

CURRENTLY_PENDING_DB_SEARCH = set()
CURRENTLY_PENDING_RENAME = set()


def main():
    AppSettings.load()

    LOG.info(f'Starting Manga Tagger - Version {AppSettings.version}')
    LOG.debug('RUNNING IN DEBUG MODE')

    if AppSettings.mode_settings is not None:
        LOG.info('DRY RUN MODE ENABLED')
        LOG.info(f"MetadataTable Insertion: {AppSettings.mode_settings['database_insert']}")
        LOG.info(f"Renaming Files: {AppSettings.mode_settings['rename_file']}")
        LOG.info(f"Writing Comicinfo.xml: {AppSettings.mode_settings['write_comicinfo']}")

    QueueWorker.run()


def process_manga_chapter(file_path, event_id):
    filename = basename(file_path)
    directory_path = file_path.split(filename)[0]
    directory_name = basename(directory_path[:-1])

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
    except TypeError as te:
        LOG.warning(f'Manga Tagger was unable to process "{file_path}"', extra=logging_info)
        return None

    manga_library_dir = f'{AppSettings.library_dir}\\{directory_name}'
    LOG.debug(f'Manga Library Directory: {manga_library_dir}')

    if not os.path.exists(manga_library_dir):
        LOG.info(f'A directory for "{directory_name}" in "{AppSettings.library_dir}" does not exist; creating now '
                 f'and granting application permission to access it.')
        os.mkdir(manga_library_dir)
        AppSettings.grant_permissions(manga_library_dir)

    new_file_path = f'{manga_library_dir}\\{new_filename}'
    LOG.debug(f'new_file_path: {new_file_path}')

    LOG.info(f'Checking for current and previously processed files with filename "{basename(new_file_path)}"...',
             extra=logging_info)

    if AppSettings.mode_settings is None or AppSettings.mode_settings['rename_file']:
        try:
            # Multithreading Optimization
            if new_file_path in CURRENTLY_PENDING_RENAME:
                LOG.info(f'A file is currently being renamed under the filename "{basename(new_file_path)}". Locking '
                         f'{file_path} from further processing until this rename action is complete...',
                         extra=logging_info)

                while new_file_path in CURRENTLY_PENDING_RENAME:
                    time.sleep(1)

                LOG.info(f'The file being renamed to "{new_file_path}" has been completed. Unlocking '
                         f'"{basename(new_file_path)}" for file rename processing.', extra=logging_info)
            else:
                LOG.info(f'No files currently currently being processed under the filename '
                         f'"{basename(new_file_path)}". Locking new filename for processing...', extra=logging_info)
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

    metadata_tagger(new_file_path, directory_name, manga_details[1], logging_info)
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
    chapter_title: str = filename[1].strip('.cbz').lower()
    LOG.debug(f'manga_title: {manga_title}')
    LOG.debug(f'chapter: {chapter_title}')

    # If "chapter" is in the chapter substring
    try:
        if chapter_title.find('chapter') > -1:
            delimiter = 'chapter'

            if ' ' in chapter_title:
                delimiter_index = 7
            else:
                delimiter_index = 8
        elif chapter_title.find('ch.') > -1:
            delimiter = 'ch.'

            if ' ' in chapter_title:
                delimiter_index = 3
            else:
                delimiter_index = 4
        elif chapter_title.find('ch') > -1:
            delimiter = 'ch.'

            if ' ' in chapter_title:
                delimiter_index = 2
            else:
                delimiter_index = 3
        else:
            raise UnparsableFilenameError(filename, 'ch/chapter')
    except UnparsableFilenameError as ufe:

        LOG.exception(ufe, extra=logging_info)
        return None

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


def rename_action(current_file_path, new_file_path, manga_title, chapter_number, logging_info):
    chapter_number = chapter_number.replace('.', '-')
    results = ProcFilesTable.search(manga_title, chapter_number)
    LOG.debug(f'Results: {results}')

    # If the series has not been processed
    if results is None:
        LOG.info(f'"{manga_title}" chapter {chapter_number} has not been processed before. '
                 f'Proceeding with file rename...', extra=logging_info)
        insert_record_and_rename(current_file_path, new_file_path, manga_title, chapter_number, logging_info)

    else:
        versions = ['v2', 'v3', 'v4', 'v5']
        try:
            existing_old_filename = results['old_filename']
            existing_current_filename = results['new_filename']

            # If currently processing file has the same name as an existing file
            if existing_current_filename == basename(new_file_path):
                # If currently processing file has a version in it's filename
                if any(version in basename(current_file_path).lower() for version in versions):
                    # If the version is newer than the existing file
                    if compare_versions(existing_old_filename, current_file_path):
                        LOG.info(f'Newer version of "{manga_title}" chapter {chapter_number} has been found. Deleting '
                                 f'existing file and proceeding with file rename...', extra=logging_info)
                        os.remove(new_file_path)
                        LOG.info(f'"{basename(new_file_path)}" has been deleted! Proceeding to rename new file...',
                                 extra=logging_info)
                        update_record_and_rename(results, current_file_path, new_file_path, logging_info)
                    else:
                        LOG.warning(f'"{basename(current_file_path)}" was not renamed due being the exact same as the '
                                    f'existing chapter; file currently being processed will be deleted',
                                    extra=logging_info)
                        os.remove(current_file_path)
                        raise FileUpdateNotRequiredError(basename(current_file_path))
                # If the current file doesn't have a version in it's filename, but the existing file does
                elif any(version in basename(existing_old_filename).lower() for version in versions):
                    LOG.warning(f'"{basename(current_file_path)}" was not renamed due to not being an updated version '
                                f'of the existing chapter; file currently being processed will be deleted',
                                extra=logging_info)
                    os.remove(current_file_path)
                    raise FileUpdateNotRequiredError(basename(current_file_path))
                # If all else fails
                else:
                    LOG.warning(f'No changes have been found for "{existing_current_filename}"; file currently being '
                                f'processed will be deleted', extra=logging_info)
                    os.remove(current_file_path)
                    raise FileAlreadyProcessedError(basename(current_file_path))
        except KeyError as ke:
            LOG.info(f'Series "{manga_title}" has been processed before, but chapter {chapter_number} has not. '
                     f'Proceeding with file rename...', extra=logging_info)
            insert_record_and_rename(current_file_path, new_file_path, manga_title, chapter_number, logging_info)

    LOG.info(f'"{basename(new_file_path)}" will be unlocked for any pending processes.', extra=logging_info)
    CURRENTLY_PENDING_RENAME.remove(new_file_path)


def compare_versions(old_filename, new_filename):
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


def insert_record_and_rename(old_file_path, new_file_path, manga_title, chapter_number, logging_info):
    os.rename(old_file_path, new_file_path)
    LOG.info(f'"{basename(new_file_path).strip(".cbz")}" has been renamed.', extra=logging_info)

    record = {
        "series_title": manga_title,
        "chapter_number": chapter_number,
        "old_filename": basename(old_file_path),
        "new_filename": basename(new_file_path),
        "process_date": datetime.now().date().strftime('%Y-%m-%d')
    }

    LOG.debug(f'Record: {record}')

    logging_info['inserted_processed_record'] = record
    ProcFilesTable.insert(record, logging_info)


def update_record_and_rename(results, old_file_path, new_file_path, logging_info):
    os.rename(old_file_path, new_file_path)
    LOG.info(f'"{basename(new_file_path).strip(".cbz")}" has been renamed.', extra=logging_info)

    record = {
        "$set": {
            "old_filename": basename(old_file_path),
            "update_date": datetime.now().date().strftime('%Y-%m-%d')
        }
    }
    LOG.debug(f'Record: {record}')

    logging_info['updated_processed_record'] = record
    ProcFilesTable.update(results, record, logging_info)


def metadata_tagger(manga_file_path, manga_title, manga_chapter_number, logging_info):
    manga_search = None
    db_exists = True
    retries = 0

    LOG.info(f'Table search value is "{manga_title}"', extra=logging_info)
    while manga_search is None:
        if retries == 0:
            LOG.info('Searching manga_metadata for manga title by search value...', extra=logging_info)
            manga_search = MetadataTable.search_by_search_value(manga_title)
            retries = 1
        elif retries == 1:
            LOG.info('Searching manga_metadata for regular manga title...', extra=logging_info)
            manga_search = MetadataTable.search_by_series_title(manga_title)
            retries = 2
        elif retries == 2:
            LOG.info('Searching manga_metadata for English manga title...', extra=logging_info)
            manga_search = MetadataTable.search_by_series_title_eng(manga_title)
            retries = 3
        else:  # The manga is not in the database, so ping the API and create the database
            LOG.info('Manga was not found in the database; resorting to Jikan API.', extra=logging_info)

            try:
                manga_search = MTJikan().search('manga', manga_title)
            except (APIException, ConnectionError) as e:
                LOG.warning(e, extra=logging_info)
                LOG.warning('Manga Tagger has unintentionally breached the API limits on Jikan. Waiting 60s to clear '
                            'all rate limiting limits...')
                time.sleep(60)
                manga_search = MTJikan().search('manga', manga_title)
            db_exists = False

    if db_exists:
        if manga_title in ProcSeriesTable.processed_series:
            LOG.info(f'Found an entry in manga_metadata for "{manga_title}".', extra=logging_info)
        else:
            LOG.info(f'Found an entry in manga_metadata for "{manga_title}"; unlocking series for processing.',
                     extra=logging_info)
            ProcSeriesTable.processed_series.add(manga_title)
            CURRENTLY_PENDING_DB_SEARCH.remove(manga_title)

        manga_metadata = Metadata(manga_title, logging_info, details=manga_search)
        logging_info['metadata'] = manga_metadata.__dict__
    else:
        try:
            manga_id = None

            for result in manga_search['results']:
                if result['type'].lower() == 'manga' and compare(manga_title, result['title']) > .8:
                    manga_id = result['mal_id']
                    break

            if manga_id is None:
                raise MangaNotFoundError(manga_title)
        except MangaNotFoundError as mnfe:
            LOG.exception(mnfe, extra=logging_info)
            return

        LOG.info(f'ID for "{manga_title}" found as "{manga_id}".', extra=logging_info)

        try:
            jikan_details = MTJikan().manga(manga_id)
        except (APIException, ConnectionError) as e:
            LOG.warning(e, extra=logging_info)
            LOG.warning('Manga Tagger has unintentionally breached the API limits on Jikan. Waiting 60s to clear '
                        'all rate limiting limits...')
            time.sleep(60)
            jikan_details = MTJikan().manga(manga_id)

        anilist_details = search_staff_by_mal_id(manga_id, logging_info)
        LOG.debug(f'jikan_details: {jikan_details}')
        LOG.debug(f'anilist_details: {anilist_details}')

        manga_metadata = Metadata(manga_title, logging_info, jikan_details, anilist_details)
        logging_info['metadata'] = manga_metadata.__dict__

        if AppSettings.mode_settings is None or AppSettings.mode_settings['database_insert']:
            MetadataTable.insert(manga_metadata, logging_info)

        LOG.info(f'Retrieved metadata for "{manga_title}" from the Anilist and MyAnimeList APIs; '
                 f'now unlocking series for processing!', extra=logging_info)
        ProcSeriesTable.processed_series.add(manga_title)
        CURRENTLY_PENDING_DB_SEARCH.remove(manga_title)

    comicinfo_xml = construct_comicinfo_xml(manga_metadata, manga_chapter_number, logging_info)

    if AppSettings.mode_settings is None or AppSettings.mode_settings['write_comicinfo']:
        reconstruct_manga_chapter(comicinfo_xml, manga_file_path, logging_info)


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

    LOG.info(f'Finished creating ComicInfo object for "{metadata.series_title}", chapter {chapter_number}.',
             extra=logging_info)
    return parseString(tostring(comicinfo)).toprettyxml(indent="   ")


def reconstruct_manga_chapter(comicinfo_xml, manga_file_path, logging_info):
    try:
        with ZipFile(manga_file_path, 'a') as zipfile:
            zipfile.writestr('ComicInfo.xml', comicinfo_xml)
    except Exception as e:
        LOG.exception(e, extra=logging_info)
        LOG.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.',
                    extra=logging_info)
        return

    LOG.info(f'ComicInfo.xml has been created and appended to "{manga_file_path}".', extra=logging_info)


def search_staff_by_mal_id(mal_id, logging_info):
    query = '''
    query search_staff_by_mal_id ($mal_id: Int) {
      Media (idMal: $mal_id, type: MANGA) {
        siteUrl
        staff {
          edges {
            node{
              name {
                first
                last
                full
                alternative
              }
              siteUrl
            }
            role
          }
        }
      }
    }
    '''

    variables = {
        'mal_id': mal_id
    }

    try:
        response = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables})
    except Exception as e:
        LOG.exception(e, extra=logging_info)
        LOG.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.',
                    extra=logging_info)
        return None

    LOG.debug(f'mal_id: {mal_id}')
    LOG.debug(f'Response JSON: {response.json()}')

    return response.json()['data']['Media']
