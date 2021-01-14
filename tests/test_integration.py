import json
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from MangaTaggerLib.api import AniList
from MangaTaggerLib.MangaTaggerLib import metadata_tagger
from MangaTaggerLib.models import Metadata
from tests.database import MetadataTable as MetadataTableTest


# noinspection DuplicatedCode
class TestMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_dir = 'data'
        cls.data_file = 'data.json'
        cls.staff_file = 'staff.json'

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        AniList.initialize()

        patch1 = patch('MangaTaggerLib.models.AppSettings')
        self.AppSettings = patch1.start()
        self.addCleanup(patch1.stop)
        self.AppSettings.timezone = 'America/New_York'

        patch2 = patch('MangaTaggerLib.MangaTaggerLib.MetadataTable')
        self.MetadataTable = patch2.start()
        self.addCleanup(patch2.stop)
        self.MetadataTable.search_by_search_value = MetadataTableTest.search_return_no_results
        self.MetadataTable.search_by_series_title = MetadataTableTest.search_return_no_results
        self.MetadataTable.search_by_series_title_eng = MetadataTableTest.search_return_no_results

        patch3 = patch('MangaTaggerLib.MangaTaggerLib.CURRENTLY_PENDING_DB_SEARCH', new_callable=list)
        self.CURRENTLY_PENDING_DB_SEARCH = patch3.start()
        self.addCleanup(patch3.stop)

    def test_metadata_case_1(self):
        title = 'Absolute Boyfriend'
        self.CURRENTLY_PENDING_DB_SEARCH.append(title)

        with open(Path(self.data_dir, title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        expected_manga_metadata = Metadata(title, {}, jikan_details, anilist_details)
        actual_manga_metadata = metadata_tagger(title, '001', {})

        self.assertEqual(expected_manga_metadata.test_value(), actual_manga_metadata.test_value())

    def test_metadata_case_2(self):
        title = 'Peach Girl Next [EN]'
        self.CURRENTLY_PENDING_DB_SEARCH.append(title)

        with open(Path(self.data_dir, title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        expected_manga_metadata = Metadata(title, {}, jikan_details, anilist_details)
        actual_manga_metadata = metadata_tagger(title, '001', {})

        self.assertEqual(expected_manga_metadata.test_value(), actual_manga_metadata.test_value())
