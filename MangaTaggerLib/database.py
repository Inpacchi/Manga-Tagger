import json
import logging
import shutil
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from queue import Queue
from sqlite3 import Error

# Define the lock globally
lock = threading.Lock()


class Database:
    database_name = None

    sql_create_manga_table = """CREATE TABLE IF NOT EXISTS manga (
                                       manga_id integer PRIMARY KEY,
                                       mal_id integer,
                                       series_title text,
                                       series_title_eng text,
                                       series_title_jap text,
                                       status text,
                                       type text,
                                       description text,
                                       mal_url text,
                                       anilist_url text,
                                       genres text,
                                       staff text,
                                       serializations text,
                                       scrape_date text,
                                       publish_date text                                    
                                   );"""

    sql_create_files_table = """CREATE TABLE IF NOT EXISTS files (
                                    file_id integer PRIMARY KEY,
                                    chapter_number text,
                                    new_filename text,
                                    old_filename text,
                                    series_title text,
                                    processed_date text,
                                    tagged_date text,
                                    manga_id integer,
                                    FOREIGN KEY (manga_id) REFERENCES manga (manga_id)
                                );"""

    sql_create_task_queue_table = """CREATE TABLE IF NOT EXISTS task_queue (
                                         task_id integer PRIMARY KEY,
                                         event_type text,
                                         manga_chapter text,
                                         src_path text
                                     );"""

    _client = None
    _database = None
    _table = None
    _log = None

    def dict_factory(cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    @classmethod
    def get_sqlite3_thread_safety(cls):

        # Map value from SQLite's THREADSAFE to Python's DBAPI 2.0
        # threadsafety attribute.
        sqlite_threadsafe2python_dbapi = {0: 0, 2: 1, 1: 3}
        conn = sqlite3.connect(cls.database_name)
        threadsafety = conn.execute(
            """
    select * from pragma_compile_options
    where compile_options like 'THREADSAFE=%'
    """
        ).fetchone()[0]
        conn.close()

        threadsafety_value = int(threadsafety.split("=")[1])

        return sqlite_threadsafe2python_dbapi[threadsafety_value]

    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')

        try:
            cls._log.info('Establishing database connection...')

            if cls.get_sqlite3_thread_safety() == 3:
                check_same_thread = False
            else:
                check_same_thread = True

            cls._client = sqlite3.connect(cls.database_name, check_same_thread=check_same_thread)
            cls._client.row_factory = cls.dict_factory
            cls._database = cls._client.cursor()
            try:
                lock.acquire(True)
                cls._database.execute(cls.sql_create_manga_table)
            finally:
                lock.release()

            try:
                lock.acquire(True)
                cls._database.execute(cls.sql_create_files_table)
            finally:
                lock.release()

            try:
                lock.acquire(True)
                cls._database.execute(cls.sql_create_task_queue_table)
            finally:
                lock.release()

        except Error as e:
            cls._log.exception(e)
            cls._log.critical('Manga Tagger cannot run without a database connection. Please check the'
                              'configuration in settings.json and try again.')
            sys.exit(1)
        # finally:
        #     if cls._client:
        #         cls._client.close()

        # cls._database = cls._client[cls.database_name]

        MangaTable.initialize()
        FilesTable.initialize()
        TaskQueueTable.initialize()

        cls._log.info('Database connection established!')
        cls._log.debug(f'{cls.__name__} class has been initialized')

    @classmethod
    def print_debug_settings(cls):
        cls._log.debug(f'Database Name: {Database.database_name}')

    @classmethod
    def delete_all(cls, table, logging_info):
        try:
            cls._log.info(f'Attempting to delete all records in table {table}...')
            try:
                lock.acquire(True)
                cls._database.execute(f'DELETE FROM {table}')
            finally:
                lock.release()
        except Exception as e:
            cls._log.exception(e)
            cls._log.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.')
            return

        cls._log.info('Deletion was successful!')

    @classmethod
    def close_connection(cls):
        cls._client.close()


class MangaTable(Database):
    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        cls._table = 'manga'
        cls._log.debug(f'{cls.__name__} class has been initialized')

    @classmethod
    def search(cls, manga_title):
        cls._log.debug(f'Searching manage for "{manga_title}"')
        try:
            lock.acquire(True)
            results = cls._database.execute(
                'SELECT * FROM manga WHERE series_title_eng = ? OR series_title = ?',
                (manga_title, manga_title,))
            result = results.fetchone()
        finally:
            lock.release()
        return result

    @classmethod
    def insert(cls, data, logging_info=None):
        params = (
            data.mal_id,
            data.series_title,
            data.series_title_eng,
            data.series_title_jap,
            data.status,
            data.type,
            data.description,
            data.mal_url,
            data.anilist_url,
            json.dumps(data.genres),
            json.dumps(data.staff),
            json.dumps(data.serializations),
            data.publish_date,
            data.scrape_date
        )

        cls._log.info('Inserting record into the database...')
        try:
            lock.acquire(True)
            cls._database.execute(
                'INSERT INTO manga (mal_id, series_title, series_title_eng, series_title_jap, status, type, '
                "description, mal_url, anilist_url, genres, staff, serializations, publish_date, scrape_date) VALUES "
                "(?, ?, ?, strftime('%Y-%m-%d', ?), ?, strftime('%Y-%m-%d %H:%M:%S[+-]HH:MM', ?), ?, ?, ?, ?, ?, ?, ?,"
                " ?)", params)
            cls._client.commit()

            manga_id = cls._database.lastrowid
        finally:
            lock.release()
        cls._log.info(f'Insertion was successful! Manga ID: {manga_id}')

        return manga_id


# class ProcSeriesTable(Database):
#     processed_series = set()
#
#     @classmethod
#     def initialize(cls):
#         cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
#         cls._table = 'processed_series'
#         cls._id = None
#         cls._last_save_time = None
#         cls._log.debug(f'{cls.__name__} class has been initialized')


class FilesTable(Database):
    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        cls._table = 'files'
        cls._log.debug(f'{cls.__name__} class has been initialized')

    @classmethod
    def search(cls, manga_title, chapter_number):
        cls._log.debug(f'Searching files cls by keys "series_title" and "chapter_number" '
                       f'using values "{manga_title}" and {chapter_number}')
        try:
            lock.acquire(True)
            results = cls._database.execute(
                'SELECT * FROM files WHERE series_title = ? AND chapter_number = ?',
                (manga_title,
                 chapter_number,))
            result = results.fetchone()
        finally:
            lock.release()
        return result

    @classmethod
    def get_by_id(cls, file_id):
        cls._log.debug(f'Getting details for file id: {file_id}')
        try:
            lock.acquire(True)
            results = cls._database.execute(
                'SELECT * FROM files WHERE file_id = ?',
                (file_id,))
            result = results.fetchone()
        finally:
            lock.release()
        return result

    @classmethod
    def untagged(cls):
        cls._log.debug('Getting untagged files.')
        try:
            lock.acquire(True)
            results = cls._database.execute('SELECT file_id FROM files WHERE tagged_date is null')
        finally:
            lock.release()
        return results

    @classmethod
    def insert_record_and_rename(cls, old_file_path: Path, new_file_path: Path, manga_title, chapter, logging_info):

        params = (
            manga_title,
            chapter,
            old_file_path.name,
            new_file_path.name
        )

        cls._log.debug(f'Params: {params}')

        logging_info['record_params'] = params

        try:
            #old_file_path.rename(new_file_path)
            shutil.move(old_file_path.as_posix(), new_file_path.as_posix())
        except FileNotFoundError as e:
            cls._log.exception(f'{old_file_path.as_posix()} not found.')

        try:
            lock.acquire(True)

            if new_file_path.is_file():
                cls._log.info(f'"{new_file_path.name.strip(".cbz")}" has been renamed.')

                cls._database.execute(
                    'INSERT INTO files (series_title, chapter_number, old_filename,new_filename, processed_date) '
                    'VALUES (?, ?, ?, ?, datetime()) ', params)
            else:
                cls._log.info(f'"{new_file_path.name.strip(".cbz")}" rename failed.')
                cls._database.execute(
                    'INSERT INTO files (series_title, chapter_number, old_filename, new_filename) VALUES (?, ?, ?, ?)',
                    params)

            cls._client.commit()

            file_id = cls._database.lastrowid

        finally:
            lock.release()

        cls._log.debug(f'File record added. File ID: {file_id} Params: {params}')
        return file_id

    @classmethod
    def update_record_and_rename(cls, results, old_file_path: Path, new_file_path: Path, logging_info):

        logging_info['updated_processed_record'] = results

        try:
            # old_file_path.rename(new_file_path)
            shutil.move(old_file_path.resolve().name, new_file_path.resolve().name)
        except FileNotFoundError as e:
            cls._log.exception(f'{old_file_path.name} not found.')

        if new_file_path.is_file():
            cls._log.info(f'"{new_file_path.name.strip(".cbz")}" has been renamed.')
            try:
                lock.acquire(True)
                cls._database.execute(
                    'UPDATE files SET processed_date = datetime() WHERE file_id = ?', (results['file_id'],))
                cls._client.commit()
            finally:
                lock.release()
        else:
            cls._log.info(f'"{new_file_path.name.strip(".cbz")}" rename failed.')

        cls._log.debug(f'File record updated: {results["file_id"]}')

    @classmethod
    def add_manga_id(cls, file_id, manga_id):
        cls._log.info(f'Adding Manga ID: {manga_id} to File ID: {file_id}')

        params = (
            manga_id,
            file_id
        )

        try:
            lock.acquire(True)
            cls._database.execute('UPDATE files SET manga_id = ? WHERE file_id = ?', params)
            cls._client.commit()
        finally:
            lock.release()
        cls._log.debug(f'File record updated: {file_id}')

    @classmethod
    def add_tagged_date(cls, file_id):
        cls._log.info(f'Adding tagged date to File ID: {file_id}')
        try:
            lock.acquire(True)
            cls._database.execute('UPDATE files SET tagged_date = datetime() WHERE file_id = ?', (file_id,))
            cls._client.commit()
        finally:
            lock.release()
        cls._log.debug(f'File record updated: {file_id}')


class TaskQueueTable(Database):
    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        cls._table = 'task_queue'
        cls.queue = Queue()
        cls._log.debug(f'{cls.__name__} class has been initialized')

    @classmethod
    def load(cls, task_list: dict):
        cls._log.info('Loading task queue...')
        try:
            lock.acquire(True)
            results = cls._database.execute('SELECT * FROM task_queue')

            if results is not None:
                for result in results.fetchall():
                    cls._log.info(f'Adding task: {result}')
                    result['src_path'] = result['src_path'].replace('\\', '/')
                    task_list[result['manga_chapter']] = result
        finally:
            lock.release()

    @classmethod
    def save(cls, queue):
        if not queue.empty():
            cls._log.info('Saving task queue...')
            while not queue.empty():
                event = queue.get()
                cls._log.debug(f'Event: {event}')
                params = (
                    event['event_type'],
                    event['manga_chapter'],
                    event['src_path'],
                )
                try:
                    lock.acquire(True)
                    cls._database.execute(
                        'INSERT INTO task_queue (event_type, manga_chapter, src_path) VALUES (?, ?, ?)',
                        params)
                    cls._client.commit()
                finally:
                    lock.release()

    @classmethod
    def delete_all(cls):
        super(TaskQueueTable, cls).delete_all(cls._table, None)
