from datetime import datetime


class ProcFilesTable:
    @classmethod
    def search_return_results(cls, manga_title, chapter_number):
        return {
            "chapter_number": "001",
            "new_filename": "Absolute Boyfriend 001.cbz",
            "old_filename": "Absolute Boyfriend -.- Absolute Boyfriend 01 Lover Shop.cbz",
            "process_date": datetime.now().strftime('%Y-%m-%d'),
            "series_title": "Absolute Boyfriend"
        }

    @classmethod
    def search_return_results_version(cls, manga_title, chapter_number):
        return {
            "chapter_number": "001",
            "new_filename": "Absolute Boyfriend 001.cbz",
            "old_filename": "Absolute Boyfriend -.- Absolute Boyfriend 01 Lover Shop v2.cbz",
            "process_date": datetime.now().strftime('%Y-%m-%d'),
            "series_title": "Absolute Boyfriend"
        }

    @classmethod
    def search_return_no_results(cls, manga_title, chapter_number):
        return None
