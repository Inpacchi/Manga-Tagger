import logging
import time
import uuid
from ntpath import dirname, getsize
from queue import Queue
from threading import Thread
from typing import List

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from MangaTaggerLib import MangaTaggerLib
from MangaTaggerLib.database import TaskQueueTable


class QueueEvent:
    def __init__(self, event, from_db=False):
        if not from_db:
            self.event_type = event.event_type
            self.src_path = event.src_path
            try:
                self.dest_path = event.dest_path
            except AttributeError:
                pass
        else:
            self.event_type = event['event_type']
            self.src_path = event['src_path']
            try:
                self.dest_path = event['dest_path']
            except KeyError:
                pass

    def __str__(self):
        if self.event_type == 'created':
            return f'File {self.event_type} event at {self.src_path}'
        elif self.event_type == 'modified':
            return f'File {self.event_type} event at {self.dest_path}'


class QueueWorker:
    _queue: Queue = None
    _observer: Observer = None
    _log: logging = None
    _worker_list: List[Thread] = None
    _running: bool = False

    max_queue_size = None
    threads = None
    is_library_network_path = False
    download_dir = None

    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        cls._queue = Queue(maxsize=cls.max_queue_size)
        cls._observer = Observer()
        cls._worker_list = []
        cls._running = True

    @classmethod
    def load_task_queue(cls):
        task_list = []
        TaskQueueTable.load(task_list)

        for task in task_list:
            cls._queue.put(QueueEvent(task, True))

        TaskQueueTable.delete_all()

    @classmethod
    def save_task_queue(cls):
        TaskQueueTable.save(cls._queue)
        with cls._queue.mutex:
            cls._queue.queue.clear()

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
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')
        for i in range(cls.threads):
            worker = Thread(target=cls.process, name=f'MTT-{i}', daemon=True)
            cls._log.debug(f'Worker thread {worker.name} has been initialized')
            cls._worker_list.append(worker)
            worker.start()

        if cls.is_library_network_path:
            cls._observer = PollingObserver()

        cls._observer.schedule(SeriesHandler(cls._queue), cls.download_dir, True)
        cls._observer.start()

        cls._log.info(f'Watching "{cls.download_dir}" for new downloads')

        while cls._running:
            time.sleep(1)

    @classmethod
    def process(cls):
        while cls._running:
            if not cls._queue.empty():
                event = cls._queue.get()

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

        self.queue.put(QueueEvent(event))
        self._log.info(f'Creation event for "{event.src_path}" will be added to the queue')

    def on_moved(self, event):
        self._log.debug(f'Event Type: {event.event_type}')
        self._log.debug(f'Event Source Path: {event.src_path}')
        self._log.debug(f'Event Destination Path: {event.dest_path}')

        if dirname(event.src_path) == dirname(event.dest_path) and '-.-' in event.dest_path:
            self.queue.put(QueueEvent(event))
        self._log.info(f'Moved event for "{event.dest_path}" will be added to the queue')
