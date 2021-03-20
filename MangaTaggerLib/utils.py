import atexit
import json
import logging
import subprocess
import sys
from logging.handlers import RotatingFileHandler, SocketHandler
from pathlib import Path
from tkinter import filedialog, messagebox, Tk

import numpy
import psutil
from fuzzywuzzy import fuzz
from pythonjsonlogger import jsonlogger

from MangaTaggerLib.database import Database
from MangaTaggerLib.task_queue import QueueWorker
from MangaTaggerLib.api import AniList


class AppSettings:
    mode_settings = None
    timezone = None
    version = None

    library_dir = None
    is_network_path = None

    processed_series = None

    _log = None

    @classmethod
    def load(cls):
        settings_location = Path(Path.cwd(), 'settings.json')
        if Path(settings_location).exists():
            with open(settings_location, 'r') as settings_json:
                settings = json.load(settings_json)
        else:
            with open(settings_location, 'w+') as settings_json:
                settings = cls._create_settings()
                json.dump(settings, settings_json, indent=4)

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
            QueueWorker.threads = 1
        else:
            QueueWorker.threads = settings['application']['multithreading']['threads']

        cls._log.debug(f'Threads: {QueueWorker.threads}')

        if settings['application']['multithreading']['max_queue_size'] < 0:
            QueueWorker.max_queue_size = 0
        else:
            QueueWorker.max_queue_size = settings['application']['multithreading']['max_queue_size']

        cls._log.debug(f'Max Queue Size: {QueueWorker.max_queue_size}')

        # Debug Mode - Prevent application from processing files
        if settings['application']['debug_mode']:
            QueueWorker._debug_mode = True

        cls._log.debug(f'Debug Mode: {QueueWorker._debug_mode}')

        # Manga Library Configuration
        if settings['application']['library']['dir'] is not None:
            cls.library_dir = settings['application']['library']['dir']
            cls._log.debug(f'Library Directory: {cls.library_dir}')

            cls.is_network_path = settings['application']['library']['is_network_path']

            if not Path(cls.library_dir).exists():
                cls._log.info(f'Library directory "{AppSettings.library_dir}" does not exist; creating now.')
                Path(cls.library_dir).mkdir()
        else:
            cls._log.critical('Manga Tagger cannot function without a library directory for moving processed '
                              'files into. Configure one in the "settings.json" and try again.')
            sys.exit(1)

        # Load necessary database tables
        Database.load_database_tables()

        # Initialize QueueWorker and load task queue
        QueueWorker.initialize()
        QueueWorker.load_task_queue()

        # Scan download directory for downloads not already in database upon loading
        cls._scan_download_dir()

        # Initialize API
        AniList.initialize()

        # Register function to be run prior to application termination
        atexit.register(cls._exit_handler)
        cls._log.debug(f'{cls.__name__} class has been initialized')

    @classmethod
    def _initialize_fmd_settings(cls, fmd_dir, download_dir):
        cls._log.info('Now setting Free Manga Downloader configuration settings...')

        fmd_settings_path = Path(fmd_dir, 'userdata', 'settings.json')

        # If FMD is running, stop it
        for process in psutil.process_iter():
            if 'fmd.exe' == process.name():
                cls._log.info('Free Manga Downloader is currently running and must be closed for Manga Tagger to '
                              'initialize the FMD settings properly.')
                process.terminate()

        # If FMD settings has not been initialized, start and stop FMD to generate the settings.json file, so that we
        # can then set the download path
        if not fmd_settings_path.exists():
            cls._log.info('The settings.json for Free Manga Downloader (FMD) does not exist, meaning that FMD has '
                          'not been opened before. Opening the application to generate the settings.json...')

            Tk().withdraw()
            messagebox.showinfo('Manga Tagger', 'For Manga Tagger to continue, the settings.json for Free Manga '
                                                'Downloader (FMD) must first be generated. After clicking "OK", FMD '
                                                'will open. Please click "No" to any module update pop-ups and close '
                                                'FMD using the "X" in the upper right-hand corner.')

            subprocess.run(str(Path(fmd_dir, 'fmd.exe')))

            if download_dir is None:
                cls._log.info('Download directory has not been set; a file dialog window will be opened to input '
                              'the destination download directory.')
                Tk().withdraw()
                download_dir = Path(filedialog.askdirectory(title='Select the folder where you want your manga to be '
                                                                  'downloaded to'))

        # Load settings
        with open(fmd_settings_path, 'r') as fmd_settings:
            settings_json = json.load(fmd_settings)
        changes_made = False

        # GenerateMangaFolder MUST BE TRUE in order to properly parse the download directory
        if settings_json['saveto']['GenerateMangaFolder'] is False:
            settings_json['saveto']['GenerateMangaFolder'] = True
            settings_json['saveto']['MangaCustomRename'] = '%MANGA%'
            changes_made = True
            cls._log.info('Setting "Generate Manga Folder" should be enabled with "Manga Custom Rename" '
                          f'configured as "%MANGA%"; this configuration has been applied')

        # ChapterCustomRename MUST FOLLOW this format to be properly parsed
        if settings_json['saveto']['ChapterCustomRename'].find('-.-') == -1 \
                or settings_json['saveto']['ChapterCustomRename'] != '%MANGA% -.- %CHAPTER%':
            settings_json['saveto']['ChapterCustomRename'] = '%MANGA% -.- %CHAPTER%'
            changes_made = True
            cls._log.info('Setting "Chapter Custom Rename" should be configured as "%MANGA% -.- '
                          f'%CHAPTER%" for parsing by Manga Tagger; this configuration has been applied')

        # Set the download format to CBZ
        if settings_json['saveto']['Compress'] != 2:
            settings_json['saveto']['Compress'] = 2
            changes_made = True
            cls._log.info('Setting "Compress" should be set to 2, which corresponds to the CBZ file format.')

        # Set the download directory
        if download_dir is None:
            download_dir = Path(settings_json['saveto']['SaveTo'])

            if not download_dir.is_absolute():
                cls._log.warning(f'"{download_dir}" is not a valid path. The download directory must be an '
                                 f'absolute path, such as "C:\\Downloads". Please select a new download path.')

                Tk().withdraw()
                download_dir = Path(filedialog.askdirectory(title='Select the folder where you want your manga to be '
                                                                  'downloaded to'))

        QueueWorker.download_dir = download_dir
        cls._log.info(f'Download directory has been set as "{QueueWorker.download_dir}"')

        if changes_made:
            with open(Path(fmd_dir, 'userdata', 'settings.json'), 'w') as fmd_settings:
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
        if not Path(log_dir).exists():
            Path(log_dir).mkdir()

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
        return RotatingFileHandler(Path(log_dir, f'MangaTagger.{extension}'),
                                   maxBytes=settings['max_size'],
                                   backupCount=settings['backup_count'],
                                   encoding=encoder)

    @classmethod
    def _exit_handler(cls):
        cls._log.info('Initiating shutdown procedures...')

        # Stop worker threads
        QueueWorker.exit()

        # Save necessary database tables
        Database.save_database_tables()

        # Close MongoDB connection
        Database.close_connection()

        cls._log.info('Now exiting Manga Tagger')

    @classmethod
    def _create_settings(cls):
        Tk().withdraw()
        fmd_dir = filedialog.askdirectory(title='Select the folder that Free Manga Downloader is installed in')

        return {
            "application": {
                "debug_mode": False,
                "timezone": "America/New_York",
                "library": {
                    "dir": "C:\\Library",
                    "is_network_path": False
                },
                "dry_run": {
                    "enabled": False,
                    "rename_file": False,
                    "database_insert": False,
                    "write_comicinfo": False
                },
                "multithreading": {
                    "threads": 8,
                    "max_queue_size": 0
                }
            },
            "database": {
                "database_name": "manga_tagger",
                "host_address": "localhost",
                "port": 27017,
                "username": "manga_tagger",
                "password": "Manga4LYFE",
                "auth_source": "admin",
                "server_selection_timeout_ms": 1
            },
            "logger": {
                "logging_level": "info",
                "log_dir": "logs",
                "max_size": 10485760,
                "backup_count": 5,
                "console": {
                    "enabled": True,
                    "log_format": "%(asctime)s | %(threadName)s %(thread)d | %(name)s | %(levelname)s - %(message)s"
                },
                "file": {
                    "enabled": True,
                    "log_format": "%(asctime)s | %(threadName)s %(thread)d | %(name)s | %(levelname)s - %(message)s"
                },
                "json": {
                    "enabled": True,
                    "log_format": "%(threadName)s %(thread)d %(asctime)s %(name)s %(levelname)s %(message)s"
                },
                "tcp": {
                    "enabled": False,
                    "host": "localhost",
                    "port": 1798,
                    "log_format": "%(threadName)s %(thread)d | %(asctime)s | %(name)s | %(levelname)s - %(message)s"
                },
                "json_tcp": {
                    "enabled": False,
                    "host": "localhost",
                    "port": 1798,
                    "log_format": "%(threadName)s %(thread)d %(asctime)s %(name)s %(levelname)s %(message)s"
                }
            },
            "fmd": {
                "fmd_dir": fmd_dir,
                "download_dir": None
            }
        }

    @classmethod
    def _scan_download_dir(cls):
        for directory in QueueWorker.download_dir.iterdir():
            for manga_chapter in directory.glob('*.cbz'):
                if manga_chapter.name.strip('.cbz') not in QueueWorker.task_list.keys():
                    QueueWorker.add_to_task_queue(manga_chapter)


def compare(s1, s2):
    return fuzz.ratio(s1, s2)/100
