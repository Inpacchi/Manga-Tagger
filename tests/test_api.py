import logging
import unittest
from unittest.mock import patch

from MangaTaggerLib.api import AniList, MTJikan
from MangaTaggerLib.MangaTaggerLib import metadata_tagger
from MangaTaggerLib.models import Metadata
from tests.database import MetadataTable as MetadataTableTest


class TestMangaSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)
        AniList.initialize()

    @patch('MangaTaggerLib.MangaTaggerLib.CURRENTLY_PENDING_DB_SEARCH', new_callable=list)
    @patch('MangaTaggerLib.models.AppSettings')
    @patch('MangaTaggerLib.MangaTaggerLib.MetadataTable')
    def test_integration(self, MetadataTable, AppSettings, CURRENTLY_PENDING_DB_SEARCH: list):
        MetadataTable.search_by_search_value = MetadataTableTest.search_return_no_results
        MetadataTable.search_by_series_title = MetadataTableTest.search_return_no_results
        MetadataTable.search_by_series_title_eng = MetadataTableTest.search_return_no_results

        AppSettings.timezone = 'America/New_York'

        CURRENTLY_PENDING_DB_SEARCH.append('Absolute Boyfriend')

        jikan_details = MTJikan().manga(71)
        anilist_details = AniList.search_staff_by_mal_id(71, {})

        expected_manga_metadata = Metadata('Absolute Boyfriend', {}, jikan_details, anilist_details)
        actual_manga_metadata = metadata_tagger('Absolute Boyfriend', '001', {})

        self.assertEqual(expected_manga_metadata.__dict__, actual_manga_metadata.__dict__)