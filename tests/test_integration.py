import json
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from MangaTaggerLib.api import AniList
from MangaTaggerLib.MangaTaggerLib import metadata_tagger, construct_comicinfo_xml
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
        self.models_AppSettings = patch1.start()
        self.addCleanup(patch1.stop)
        self.models_AppSettings.timezone = 'America/New_York'

        patch2 = patch('MangaTaggerLib.MangaTaggerLib.MetadataTable')
        self.MetadataTable = patch2.start()
        self.addCleanup(patch2.stop)
        self.MetadataTable.search_by_search_value = MetadataTableTest.search_return_no_results
        self.MetadataTable.search_by_series_title = MetadataTableTest.search_return_no_results
        self.MetadataTable.search_by_series_title_eng = MetadataTableTest.search_return_no_results

        patch3 = patch('MangaTaggerLib.MangaTaggerLib.CURRENTLY_PENDING_DB_SEARCH', new_callable=list)
        self.CURRENTLY_PENDING_DB_SEARCH = patch3.start()
        self.addCleanup(patch3.stop)

        patch4 = patch('MangaTaggerLib.MangaTaggerLib.AppSettings')
        self.MangaTaggerLib_AppSettings = patch4.start()
        self.addCleanup(patch4.stop)

    def test_comicinfo_xml_creation_case_1(self):
        title = 'Absolute Boyfriend'

        self.MangaTaggerLib_AppSettings.mode_settings = {}

        with open(Path(self.data_dir, title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        manga_metadata = Metadata(title, {}, jikan_details, anilist_details)

        self.assertTrue(construct_comicinfo_xml(manga_metadata, '001', {}))

    def test_comicinfo_xml_creation_case_2(self):
        title = 'Peach Girl Next [EN]'

        self.MangaTaggerLib_AppSettings.mode_settings = {}

        with open(Path(self.data_dir, title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        manga_metadata = Metadata(title, {}, jikan_details, anilist_details)

        self.assertTrue(construct_comicinfo_xml(manga_metadata, '001', {}))

    def test_comicinfo_xml_creation_case_3(self):
        title = 'G-Maru Edition'

        self.MangaTaggerLib_AppSettings.mode_settings = {}

        with open(Path(self.data_dir, title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        manga_metadata = Metadata(title, {}, jikan_details, anilist_details)

        self.assertTrue(construct_comicinfo_xml(manga_metadata, '001', {}))

    def test_metadata_case_1(self):
        title = 'Absolute Boyfriend'

        self.CURRENTLY_PENDING_DB_SEARCH.append(title)

        self.MangaTaggerLib_AppSettings.mode_settings = { 'write_comicinfo': False }

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

        self.MangaTaggerLib_AppSettings.mode_settings = { 'write_comicinfo': False }

        with open(Path(self.data_dir, title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        expected_manga_metadata = Metadata(title, {}, jikan_details, anilist_details)
        actual_manga_metadata = metadata_tagger(title, '001', {})

        self.assertEqual(expected_manga_metadata.test_value(), actual_manga_metadata.test_value())

    def test_metadata_case_3(self):
        actual_title = 'G-Maru Edition'
        downloaded_title = '(G) Edition'

        self.CURRENTLY_PENDING_DB_SEARCH.append(downloaded_title)

        self.MangaTaggerLib_AppSettings.mode_settings = { 'write_comicinfo': False }

        with open(Path(self.data_dir, actual_title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, actual_title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        expected_manga_metadata = Metadata(actual_title, {}, jikan_details, anilist_details)
        actual_manga_metadata = metadata_tagger(downloaded_title, '001', {})

        self.assertEqual(expected_manga_metadata.test_value(), actual_manga_metadata.test_value())

    def test_metadata_case_4(self):
        actual_title = 'Absolute Boyfriend'
        downloaded_title = 'Boyfriend'

        self.CURRENTLY_PENDING_DB_SEARCH.append(downloaded_title)

        self.MangaTaggerLib_AppSettings.mode_settings = { 'write_comicinfo': False }

        with open(Path(self.data_dir, actual_title, self.data_file), encoding='utf-8') as data:
            jikan_details = json.load(data)

        with open(Path(self.data_dir, actual_title, self.staff_file), encoding='utf-8') as data:
            anilist_details = json.load(data)

        expected_manga_metadata = Metadata(actual_title, {}, jikan_details, anilist_details)
        actual_manga_metadata = metadata_tagger(downloaded_title, '001', {})

        self.assertNotEqual(expected_manga_metadata.test_value(), actual_manga_metadata.test_value())
