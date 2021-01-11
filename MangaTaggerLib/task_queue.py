import logging
import time
import uuid
from enum import Enum
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import List

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from MangaTaggerLib import MangaTaggerLib
from MangaTaggerLib.database import TaskQueueTable


class QueueEventOrigin(Enum):
    WATCHDOG = 1
    FROM_DB = 2
    SCAN = 3


class QueueEvent:
    def __init__(self, event, origin=QueueEventOrigin.WATCHDOG):
        if origin == QueueEventOrigin.WATCHDOG:
            self.event_type = event.event_type
            self.src_path = Path(event.src_path)
            try:
                self.dest_path = Path(event.dest_path)
            except AttributeError:
                pass
        elif origin == QueueEventOrigin.FROM_DB:
            self.event_type = event['event_type']
            self.src_path = Path(event['src_path'])
            try:
                self.dest_path = Path(event['dest_path'])
            except KeyError:
                pass
        elif origin == QueueEventOrigin.SCAN:
            self.event_type = 'existing'
            self.src_path = event

    def __str__(self):
        if self.event_type in ('created', 'existing'):
            return f'File {self.event_type} event at {self.src_path.absolute()}'
        elif self.event_type == 'modified':
            return f'File {self.event_type} event at {self.dest_path.absolute()}'

    def dictionary(self):
        ret_dict = {
            'event_type': self.event_type,
            'src_path': str(self.src_path.absolute()),
            'manga_chapter': str(self.src_path.name.strip('.cbz'))
        }

        try:
            ret_dict['dest_path'] = str(self.dest_path.absolute())
        except AttributeError:
            pass

        return ret_dict


class QueueWorker:
    _queue: Queue = None
    _observer: Observer = None
    _log: logging = None
    _worker_list: List[Thread] = None
    _running: bool = False
    _debug_mode = False

    max_queue_size = None
    threads = None
    is_library_network_path = False
    download_dir: Path = None
    task_list = {}

    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        cls._queue = Queue(maxsize=cls.max_queue_size)
        cls._worker_list = []
        cls._running = True

        for i in range(cls.threads):
            if not cls._debug_mode:
                worker = Thread(target=cls.process, name=f'MTT-{i}', daemon=True)
            else:
                worker = Thread(target=cls.dummy_process, name=f'MTT-{i}', daemon=True)
            cls._log.debug(f'Worker thread {worker.name} has been initialized')
            cls._worker_list.append(worker)

        if cls.is_library_network_path:
            cls._observer = PollingObserver()
        else:
            cls._observer = Observer()

        cls._observer.schedule(SeriesHandler(cls._queue), cls.download_dir, True)

    @classmethod
    def load_task_queue(cls):
        TaskQueueTable.load(cls.task_list)

        for task in cls.task_list.values():
            event = QueueEvent(task, QueueEventOrigin.FROM_DB)
            cls._log.info(f'{event} has been added to the task queue')
            cls._queue.put(event)

        TaskQueueTable.delete_all()

    @classmethod
    def save_task_queue(cls):
        TaskQueueTable.save(cls._queue)
        with cls._queue.mutex:
            cls._queue.queue.clear()

    @classmethod
    def add_to_task_queue(cls, manga_chapter):
        event = QueueEvent(manga_chapter, QueueEventOrigin.SCAN)
        cls._log.info(f'{event} has been added to the task queue')
        cls._queue.put(event)

    @classmethod
    def exit(cls):
        # Stop worker threads from picking new items from the queue in process()
        cls._log.info('Stopping processing...')
        cls._running = False

        # Stop watchdog from adding new events to the queue
        cls._log.debug('Stopping watchdog...')
        cls._observer.stop()
        cls._observer.join()

        # Save and empty task queue
        cls.save_task_queue()

        # Finish current running jobs and stop worker threads
        cls._log.info('Stopping worker threads...')
        for worker in cls._worker_list:
            worker.join()
            cls._log.debug(f'Worker thread {worker.name} has been shut down')

    @classmethod
    def run(cls):
        for worker in cls._worker_list:
            worker.start()

        cls._observer.start()

        cls._log.info(f'Watching "{cls.download_dir}" for new downloads')

        while cls._running:
            time.sleep(1)

    @classmethod
    def dummy_process(cls):
        pass

    @classmethod
    def process(cls):
        while cls._running:
            if not cls._queue.empty():
                event = cls._queue.get()

                if event.event_type == 'created':
                    cls._log.info(f'Pulling "file {event.event_type}" event from the queue for "{event.src_path}"')
                    path = Path(event.src_path)
                elif event.event_type == 'moved':
                    cls._log.info(f'Pulling "file {event.event_type}" event from the queue for "{event.dest_path}"')
                    path = Path(event.dest_path)
                else:
                    cls._log.error('Event was passed, but Manga Tagger does not know how to handle it. Please open an '
                                   'issue for further investigation.')
                    cls._queue.task_done()
                    return

                current_size = -1
                try:
                    destination_size = path.stat().st_size
                    while current_size != destination_size:
                        current_size = destination_size
                        time.sleep(1)
                except FileNotFoundError as fnfe:
                    cls._log.exception(fnfe)

                try:
                    MangaTaggerLib.process_manga_chapter(path, uuid.uuid1())
                except Exception as e:
                    cls._log.exception(e)
                    cls._log.warning('Manga Tagger is unfamiliar with this error. Please log an issue for '
                                     'investigation.')

                cls._queue.task_done()


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
        self._log.debug(f'{self.class_name()} class has been initialized')

    def on_created(self, event):
        self._log.debug(f'Event Type: {event.event_type}')
        self._log.debug(f'Event Path: {event.src_path}')

        self.queue.put(QueueEvent(event, QueueEventOrigin.WATCHDOG))
        self._log.info(f'Creation event for "{event.src_path}" will be added to the queue')

    def on_moved(self, event):
        self._log.debug(f'Event Type: {event.event_type}')
        self._log.debug(f'Event Source Path: {event.src_path}')
        self._log.debug(f'Event Destination Path: {event.dest_path}')

        if Path(event.src_path) == Path(event.dest_path) and '-.-' in event.dest_path:
            self.queue.put(QueueEvent(event, QueueEventOrigin.WATCHDOG))
        self._log.info(f'Moved event for "{event.dest_path}" will be added to the queue')
