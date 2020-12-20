import atexit
import json
import logging
import os
import pickle
import subprocess
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler, SocketHandler
from ntpath import dirname, getsize
from queue import Queue
from threading import Thread

import numpy
from configparser import ConfigParser
from pythonjsonlogger import jsonlogger
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from MangaTaggerLib import MangaTaggerLib
from MangaTaggerLib.api import AniList
from MangaTaggerLib.database import Database, ProcSeriesTable


class AppSettings:
    mode_settings = None
    timezone = None
    version = None

    threads = None
    max_queue_size = None

    download_dir = None
    library_dir = None
    is_network_path = None

    processed_series = None

    _log = None

    @classmethod
    def load(cls):
        with open('settings.json') as settings_json:
            settings = json.load(settings_json)

        setup = ConfigParser()
        setup.read('setup.cfg')

        cls._initialize_logger(settings['logger'])
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')

        # Database Configuration
        cls._log.debug('Now setting database configuration...')

        Database.database_name = settings['database']['database_name']
        Database.host_address = settings['database']['host_address']
        Database.port = settings['database']['port']
        Database.username = settings['database']['username']
        Database.password = settings['database']['password']
        Database.auth_source = settings['database']['auth_source']
        Database.server_selection_timeout_ms = settings['database']['server_selection_timeout_ms']

        cls._log.debug('Database settings configured!')
        Database.initialize()
        Database.print_debug_settings()

        # Free Manga Downloader Configuration
        cls._initialize_fmd_settings(settings['fmd']['fmd_dir'], settings['fmd']['download_dir'])

        # Set Application Version
        cls.version = setup['metadata']['version']
        cls._log.debug(f'Version: {cls.version}')

        # Set Application Timezone
        cls.timezone = settings['application']['timezone']
        cls._log.debug(f'Timezone: {cls.timezone}')

        # Dry Run Mode Configuration
        # No logging here due to being handled at the INFO level in MangaTaggerLib
        if settings['application']['dry_run']['enabled']:
            cls.mode_settings = {'database_insert': settings['application']['dry_run']['database_insert'],
                                 'rename_file': settings['application']['dry_run']['rename_file'],
                                 'write_comicinfo': settings['application']['dry_run']['write_comicinfo']}

        # Multithreading Configuration
        if settings['application']['multithreading']['threads'] <= 0:
            cls.threads = 1
        else:
            cls.threads = settings['application']['multithreading']['threads']

        cls._log.debug(f'Threads: {cls.threads}')

        if settings['application']['multithreading']['max_queue_size'] < 0:
            cls.max_queue_size = 0
        else:
            cls.max_queue_size = settings['application']['multithreading']['max_queue_size']

        cls._log.debug(f'Max Queue Size: {cls.max_queue_size}')

        # Manga Library Configuration
        if settings['application']['library']['dir'] is not None:
            cls.library_dir = settings['application']['library']['dir']
            cls._log.debug(f'Library Directory: {cls.library_dir}')

            cls.is_network_path = settings['application']['library']['is_network_path']

            if not os.path.exists(cls.library_dir):
                cls._log.info(f'Library directory "{AppSettings.library_dir}" does not exist; creating now and '
                              f'granting application permission to access it.')
                os.mkdir(cls.library_dir)
                cls.grant_permissions(cls.library_dir)
        else:
            cls._log.critical('Manga Tagger cannot function without a library directory for moving processed '
                              'files into. Configure one in the "settings.json" and try again.')
            sys.exit(1)

        # Load processed database series
        cls.processed_series = ProcSeriesTable.load()
        if cls.processed_series is None:
            cls.processed_series = set()

        # Initialize API
        AniList.initialize()

        # Register function to be run prior to application termination
        atexit.register(cls._exit_handler)
        cls._log.debug(f'{cls.__name__} class has been initialized.')

    @classmethod
    def grant_permissions(cls, dir_name, print_output=True):
        output = subprocess.check_output(['icacls', dir_name, '/grant:r', 'EVERYONE:(OI)(CI)MF'])
        if print_output:
            output = output.decode('utf-8').split(';')
            output_2 = output[0].split('\r\n')

            cls._log.info(output_2[0])
            cls._log.info(output_2[1])
            cls._log.info(output[1].strip('\r\n'))

    @classmethod
    def _initialize_fmd_settings(cls, fmd_dir, download_dir):
        cls._log.debug('Now setting Free Manga Downloader configuration...')

        # Load settings
        with open(f'{fmd_dir}\\userdata\\settings.json') as fmd_settings:
            settings_json = json.load(fmd_settings)
        changes_made = False

        # GenerateMangaFolder MUST BE TRUE in order to properly parse the download directory
        if settings_json['saveto']['GenerateMangaFolder'] is False:
            settings_json['saveto']['GenerateMangaFolder'] = True
            settings_json['saveto']['MangaCustomRename'] = '%MANGA%'
            changes_made = True
            cls._log.debug(f'Setting "Generate Manga Folder" should be enabled with "Manga Custom Rename" '
                           f'configured as "%MANGA%"; this configuration has been applied')

        # ChapterCustomRename MUST FOLLOW this format to be properly parsed
        if settings_json['saveto']['ChapterCustomRename'].find('-.-') == -1 \
                or settings_json['saveto']['ChapterCustomRename'] != '%MANGA% -.- %CHAPTER%':
            settings_json['saveto']['ChapterCustomRename'] = '%MANGA% -.- %CHAPTER%'
            changes_made = True
            cls._log.debug(f'Setting "Chapter Custom Rename" should be configured as "%MANGA% -.- '
                           f'%CHAPTER%" for parsing by Manga Tagger; this configuration has been applied')

        # DEVELOPMENT ONLY SETTING
        if download_dir is None:
            cls.download_dir = settings_json['saveto']['SaveTo']
            cls._log.debug(f'Download directory has been set as "{cls.download_dir}"')
        else:
            cls.download_dir = download_dir
            cls._log.debug(
                f'Download directory has been overridden and set as "{cls.download_dir}"')

        if changes_made:
            with open(f'{fmd_dir}\\userdata\\settings.json', 'w') as fmd_settings:
                json.dump(settings_json, fmd_settings, indent=4)
                cls._log.debug(f'Changes to the "settings.json" for Free Manga Downloader have been saved')

    @classmethod
    def _initialize_logger(cls, settings):
        logger = logging.getLogger('MangaTaggerLib')
        logging_level = settings['logging_level']
        log_dir = settings['log_dir']

        if logging_level.lower() == 'info':
            logging_level = logging.INFO
        elif logging_level.lower() == 'debug':
            logging_level = logging.DEBUG
        else:
            logger.critical('Logging level not of expected values "info" or "debug". Double check the configuration'
                            'in settings.json and try again.')
            sys.exit(1)

        logger.setLevel(logging_level)

        # Create log directory and allow the application access to it
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)
            cls.grant_permissions(log_dir, False)

        # Console Logging
        if settings['console']['enabled']:
            log_handler = logging.StreamHandler()
            log_handler.setFormatter(logging.Formatter(settings['console']['log_format']))
            logger.addHandler(log_handler)

        # File Logging
        if settings['file']['enabled']:
            log_handler = cls._create_rotating_file_handler(log_dir, 'log', settings, 'utf-8')
            log_handler.setFormatter(logging.Formatter(settings['file']['log_format']))
            logger.addHandler(log_handler)

        # JSON Logging
        if settings['json']['enabled']:
            log_handler = cls._create_rotating_file_handler(log_dir, 'json', settings)
            log_handler.setFormatter(jsonlogger.JsonFormatter(settings['json']['log_format']))
            logger.addHandler(log_handler)

        # Check TCP and JSON TCP for port conflicts before creating the handlers
        if settings['tcp']['enabled'] and settings['json_tcp']['enabled']:
            if settings['tcp']['port'] == settings['json_tcp']['port']:
                logger.critical('TCP and JSON TCP logging are both enabled, but their port numbers are the same. '
                                'Either change the port value or disable one of the handlers in settings.json '
                                'and try again.')
                sys.exit(1)

        # TCP Logging
        if settings['tcp']['enabled']:
            log_handler = SocketHandler(settings['tcp']['host'], settings['tcp']['port'])
            log_handler.setFormatter(logging.Formatter(settings['tcp']['log_format']))
            logger.addHandler(log_handler)

        # JSON TCP Logging
        if settings['json_tcp']['enabled']:
            log_handler = SocketHandler(settings['json_tcp']['host'], settings['json_tcp']['port'])
            log_handler.setFormatter(jsonlogger.JsonFormatter(settings['json_tcp']['log_format']))
            logger.addHandler(log_handler)

    @staticmethod
    def _create_rotating_file_handler(log_dir, extension, settings, encoder=None):
        return RotatingFileHandler(f'{log_dir}\\MangaTagger.{extension}',
                                   maxBytes=settings['max_size'],
                                   backupCount=settings['backup_count'],
                                   encoding=encoder)

    @classmethod
    def _exit_handler(cls):
        cls._log.info('Initiating shutdown procedures...')

        # Save processed series
        cls._log.info('Dumping processed series...')
        ProcSeriesTable.save(cls.processed_series)

        # Close MongoDB connection
        cls._log.info('Closing MongoDB connection...')
        Database.close_connection()

        cls._log.info('Now exiting Manga Tagger')


class SeriesHandler(PatternMatchingEventHandler):
    _log = None

    @classmethod
    def class_name(cls):
        return cls.__name__

    @classmethod
    def fully_qualified_class_name(cls):
        return f'{cls.__module__}.{cls.__name__}'

    def __init__(self, queue):
        self._log = logging.getLogger(self.fully_qualified_class_name())
        super().__init__(patterns=['*.cbz'])
        self.queue = queue
        self._log.debug(f'{self.class_name()} class has been initialized.')

    def on_created(self, event):
        self._log.debug(f'Event Type: {event.event_type}')
        self._log.debug(f'Event Path: {event.src_path}')

        self.queue.put(event)
        self._log.info(f'Creation event for "{event.src_path}" will be added to the queue')

    def on_moved(self, event):
        self._log.debug(f'Event Type: {event.event_type}')
        self._log.debug(f'Event Source Path: {event.src_path}')
        self._log.debug(f'Event Destination Path: {event.dest_path}')

        if dirname(event.src_path) == dirname(event.dest_path) and '-.-' in event.dest_path:
            self.queue.put(event)
        self._log.info(f'Moved event for "{event.dest_path}" will be added to the queue')


class QueueWorker:
    queue = None
    _log = None

    @classmethod
    def run(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        cls.queue = Queue(maxsize=AppSettings.max_queue_size)
        for i in range(AppSettings.threads):
            worker = Thread(target=cls.process, name=f'MTT-{i}', daemon=True)
            cls._log.debug(f'Worker thread {worker.name} has been initialized')
            worker.start()

        worker = Thread(target=ProcSeriesTable.save_while_running(AppSettings.processed_series),
                        name=f'MTT-Processed_Series_Save', daemon=True)
        cls._log.debug(f'Application thread {worker.name} has been initialized')
        worker.start()

        if AppSettings.is_network_path:
            observer = PollingObserver()
        else:
            observer = Observer()
        observer.schedule(SeriesHandler(cls.queue), AppSettings.download_dir, True)
        observer.start()

        cls._log.info(f'Watching "{AppSettings.download_dir}" for new downloads')

        while True:
            time.sleep(1)
        observer.join()
        cls.queue.join()

    @classmethod
    def process(cls):
        while True:
            if not cls.queue.empty():
                event = cls.queue.get()

                if event.event_type == 'created':
                    cls._log.info(f'Pulling "file {event.event_type}" event from the queue for "{event.src_path}"')
                    path = event.src_path
                elif event.event_type == 'moved':
                    cls._log.info(f'Pulling "file {event.event_type}" event from the queue for "{event.dest_path}"')
                    path = event.dest_path
                else:
                    cls._log.error('Event was passed, but Manga Tagger does not know how to handle it. Please open an '
                                   'issue for further investigation.')

                current_size = -1
                try:
                    while current_size != getsize(path):
                        current_size = getsize(path)
                        time.sleep(1)
                except FileNotFoundError as fnfe:
                    cls._log.exception(fnfe)

                try:
                    MangaTaggerLib.process_manga_chapter(path, uuid.uuid1())
                except Exception as e:
                    cls._log.exception(e)
                    cls._log.warning('Manga Tagger is unfamiliar with this error. Please log an issue for '
                                     'investigation.')

                cls.queue.task_done()


def compare(s1, s2):
    s1 = s1.lower().strip('/[^a-zA-Z ]/g", ')
    s2 = s2.lower().strip('/[^a-zA-Z ]/g", ')

    rows = len(s1) + 1
    cols = len(s2) + 1
    distance = numpy.zeros((rows, cols), int)

    for i in range(1, rows):
        distance[i][0] = i

    for i in range(1, cols):
        distance[0][i] = i

    for col in range(1, cols):
        for row in range(1, rows):
            if s1[row - 1] == s2[col - 1]:
                cost = 0
            else:
                cost = 2

            distance[row][col] = min(distance[row - 1][col] + 1,
                                     distance[row][col - 1] + 1,
                                     distance[row - 1][col - 1] + cost)

    return ((len(s1) + len(s2)) - distance[row][col]) / (len(s1) + len(s2))
