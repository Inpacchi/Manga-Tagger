"""Exceptions raised by Manga Tagger"""


class MangaNotFoundError(Exception):
    """
    Exception raised when the manga cannot be found in the results from MyAnimeList (Jikan).
    """
    def __init__(self, manga_title):
        super().__init__(f'"{manga_title}" was not found in the returned results from MyAnimeList (using Jikan API.) '
                         f'This may be due to a difference in manga series titles, or may be something else entirely. '
                         f'Please open an issue for investigation.')


class MetadataNotCompleteError(Exception):
    """
    Exception raised when not enough data is given to create a Metadata object.
    """

    def __init__(self, current_directory):
        super().__init__('Tried to create Metadata object, but was not given the proper data to interpret')


class UnparsableFilenameError(Exception):
    """
    Exception raised when the chapter filename is unparsable; specifically when 'chapter' is not found in the filename.

    Attributes:
        filename - Name of the file
        delimiter_key - The sequence of characters not found that triggered the error
    """

    def __init__(self, filename, delimiter_key):
        super().__init__(f'Unable to parse filename "{filename}" due to delimiter "{delimiter_key}" missing')


class FileAlreadyProcessedError(FileExistsError):
    """
    Exception raised when the chapter currently being processed has already been processed and the filename does not
    indicate a different version from what was previously processed.

    Attributes:
        filename - Name of the file
    """
    def __init__(self, filename):
        super().__init__(f'"{filename}" has already been processed by Manga Tagger; skipping')


class FileUpdateNotRequiredError(FileExistsError):
    """
    Exception raised when the chapter currently being processed has been found to be older than the chapter that was
    previously processed.

    Attributes:
        filename - Name of the file
    """
    def __init__(self, filename):
        super().__init__(f'"{filename}" is older than or the same as the current existing chapter; skipping')
