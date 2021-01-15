import logging
import shutil
import unittest
from pathlib import Path
from typing import List
from unittest.mock import patch

from MangaTaggerLib.MangaTaggerLib import file_renamer, rename_action
from MangaTaggerLib.errors import FileAlreadyProcessedError, FileUpdateNotRequiredError
from tests.database import ProcFilesTable as ProcFilesTableTest


class TestMangaRename(unittest.TestCase):
    correct_filename = 'Absolute Boyfriend 001.cbz'
    special_filename = '.hackg.u.+ 001.cbz'

    def test_verify_filename_series_name(self):
        """
        Tests for the series title as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Absolute Boyfriend 01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_chapter(self):
        """
        Tests for "Chapter" as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Chapter 01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_ch_period(self):
        """
        Tests for "Ch. " (note the space) as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Ch. 01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_ch_period_spaceless(self):
        """
        Tests for "Ch." as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Ch.01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_ch(self):
        """
        Tests for "Ch " (note the space) as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Ch 01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_ch_spaceless(self):
        """
        Tests for "Ch" as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Ch01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_act(self):
        """
        Tests for "Act" as the delimiter in the filename.
        """
        filename = file_renamer('Absolute Boyfriend -.- Act 01 Lover Shop.cbz', {})[0]
        self.assertEqual(filename, self.correct_filename)

    def test_verify_filename_special_characters(self):
        """
        Tests for special characters in the chapter title portion of the filename.
        """
        filename = file_renamer('.hackg.u.+ -.- .hackg.u.+ Chapter 001.cbz', {})[0]
        self.assertEqual(filename, self.special_filename)


class TestMangaRenameAction(unittest.TestCase):
    download_dir = Path('downloads')
    library_dir = Path('library')
    current_file = None
    new_file = None

    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)
        cls.current_file = Path(cls.download_dir, 'Absolute Boyfriend -.- Absolute Boyfriend 01 Lover Shop.cbz')
        cls.new_file = Path(cls.library_dir, 'Absolute Boyfriend 001.cbz')

    def setUp(self) -> None:
        self.download_dir.mkdir()
        self.library_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.download_dir)
        shutil.rmtree(self.library_dir)

    @patch('MangaTaggerLib.MangaTaggerLib.ProcFilesTable')
    @patch('MangaTaggerLib.MangaTaggerLib.CURRENTLY_PENDING_RENAME', new_callable=list)
    def test_rename_action_initial(self, CURRENTLY_PENDING_RENAME: List, ProcFilesTable):
        """
        Tests for initial file rename when no results are returned from the database. Test should execute without error.
        """
        self.current_file.touch()
        ProcFilesTable.search = ProcFilesTableTest.search_return_no_results

        CURRENTLY_PENDING_RENAME.append(self.new_file)

        self.assertFalse(rename_action(self.current_file, self.new_file, 'Absolute Boyfriend', '01', {}))

    @patch('MangaTaggerLib.MangaTaggerLib.ProcFilesTable')
    def test_rename_action_duplicate(self, ProcFilesTable):
        """
        Tests for duplicate file rename when results are returned from the database. Test should assert
        FileAlreadyProcessedError.
        """
        self.current_file.touch()
        ProcFilesTable.search = ProcFilesTableTest.search_return_results

        with self.assertRaises(FileAlreadyProcessedError):
            rename_action(self.current_file, self.new_file, 'Absolute Boyfriend', '01', {})

    @patch('MangaTaggerLib.MangaTaggerLib.ProcFilesTable')
    def test_rename_action_downgrade(self, ProcFilesTable):
        """
        Tests for version in file rename when results are returned from the database. Since the current file is a
        lower version than the existing file, test should assert FileUpdateNotRequiredError.
        """
        self.current_file.touch()
        ProcFilesTable.search = ProcFilesTableTest.search_return_results_version

        with self.assertRaises(FileUpdateNotRequiredError):
            rename_action(self.current_file, self.new_file, 'Absolute Boyfriend', '01', {})

    @patch('MangaTaggerLib.MangaTaggerLib.ProcFilesTable')
    def test_rename_action_version_duplicate(self, ProcFilesTable):
        """
        Tests for version and duplicate file rename when results are returned from the database. Since the current
        version is the same as the one in the database, test should assert FileUpdateNotRequiredError.
        """
        self.current_file = Path(self.download_dir, 'Absolute Boyfriend -.- Absolute Boyfriend 01 Lover Shop v2.cbz')
        self.current_file.touch()

        ProcFilesTable.search = ProcFilesTableTest.search_return_results_version

        with self.assertRaises(FileUpdateNotRequiredError):
            rename_action(self.current_file, self.new_file, 'Absolute Boyfriend', '01', {})

    @patch('MangaTaggerLib.MangaTaggerLib.ProcFilesTable')
    @patch('MangaTaggerLib.MangaTaggerLib.CURRENTLY_PENDING_RENAME', new_callable=list)
    def test_rename_action_upgrade(self, CURRENTLY_PENDING_RENAME: List, ProcFilesTable):
        """
        Tests for version in file rename when results are returned from the database. Since the current file is a
        higher version than the exisitng file, test should execute without error.
        """
        self.current_file = Path(self.download_dir, 'Absolute Boyfriend -.- Absolute Boyfriend 01 Lover Shop v3.cbz')
        self.current_file.touch()

        self.new_file.touch()
        CURRENTLY_PENDING_RENAME.append(self.new_file)

        ProcFilesTable.search = ProcFilesTableTest.search_return_results_version

        self.assertFalse(rename_action(self.current_file, self.new_file, 'Absolute Boyfriend', '01', {}))