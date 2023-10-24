import json
import logging
from datetime import datetime
from pytz import timezone

from MangaTaggerLib.errors import MetadataNotCompleteError
from MangaTaggerLib.utils import AppSettings, compare


class Metadata:
    _log = None

    @classmethod
    def fully_qualified_class_name(cls):
        return f'{cls.__module__}.{cls.__name__}'

    def __init__(self, manga_title, logging_info, jikan_details=None, anilist_details=None, details=None):
        Metadata._log = logging.getLogger(self.fully_qualified_class_name())

        self.search_value = manga_title
        Metadata._log.info(f'Creating Metadata model for series "{manga_title}"...')

        if jikan_details and anilist_details:  # If details are grabbed from Jikan and Anilist APIs
            self._construct_api_metadata(jikan_details, anilist_details, logging_info)
        elif details:  # If details were stored in the database
            self._construct_database_metadata(details)
        else:
            Metadata._log.exception(MetadataNotCompleteError)
        Metadata._log.debug(f'{self.search_value} Metadata Model: {self.__dict__.__str__()}')

        logging_info['metadata'] = self.__dict__
        Metadata._log.info('Successfully created Metadata model.')

    def _construct_api_metadata(self, jikan_details, anilist_details, logging_info):
        self._id = jikan_details['mal_id']
        self.mal_id = jikan_details['mal_id']
        self.series_title = jikan_details['title']

        if jikan_details['title_english'] == 'None' or jikan_details['title_english'] is None:
            self.series_title_eng = None
        else:
            self.series_title_eng = jikan_details['title_english']

        if jikan_details['title_japanese'] == 'None' or jikan_details['title_japanese'] is None:
            self.series_title_jap = None
        else:
            self.series_title_jap = jikan_details['title_japanese']

        self.status = jikan_details['status']
        self.type = jikan_details['type']
        self.description = jikan_details['synopsis']
        self.mal_url = jikan_details['url']
        self.anilist_url = anilist_details['siteUrl']
        self.genres = []
        self.staff = {}
        self.serializations = {}
        self._parse_genres(jikan_details['genres'], logging_info)
        self._parse_staff(anilist_details['staff']['edges'], jikan_details['authors'], logging_info)
        self._parse_serializations(jikan_details['serializations'], logging_info)
        self._construct_publish_date(jikan_details['published']['from'])
        # self.scrape_date = datetime.now().date().strftime('%Y-%m-%d %I:%M %p')
        self.scrape_date = timezone(AppSettings.timezone).localize(datetime.now()).strftime('%Y-%m-%d %I:%M %p %Z')

    def _construct_database_metadata(self, details):
        self._id = details['mal_id']
        self.mal_id = details['mal_id']
        self.series_title = details['series_title']
        self.series_title_eng = details['series_title_eng']
        self.series_title_jap = details['series_title_jap']
        self.status = details['status']
        self.type = details['type']
        self.description = details['description']
        self.mal_url = details['mal_url']
        self.anilist_url = details['anilist_url']
        self.genres = json.loads(details['genres'])
        self.staff = json.loads(details['staff'])
        self.serializations = details['serializations']
        self.publish_date = details['publish_date']
        self.scrape_date = details['scrape_date']

    def _construct_publish_date(self, date):
        date = date[:date.index('T')]
        self.publish_date = datetime.strptime(date, '%Y-%m-%d').strftime('%Y-%m-%d')
        Metadata._log.debug(f'Publish date constructed: {self.publish_date}')

    def _parse_genres(self, genres, logging_info):
        Metadata._log.info('Parsing genres...')
        for genre in genres:
            Metadata._log.debug(f'Genre found: {genre}')
            self.genres.append(genre['name'])

    def _parse_staff(self, anilist_staff, jikan_staff, logging_info):
        Metadata._log.info('Parsing staff roles...')

        roles = []

        self.staff = {
            'story': {},
            'art': {}
        }

        for a_staff in anilist_staff:
            Metadata._log.debug(f'Staff Member (Anilist): {a_staff}')

            anilist_staff_name = ''

            if a_staff['node']['name']['last'] is not None:
                anilist_staff_name = a_staff['node']['name']['last']

            if a_staff['node']['name']['first'] is not None:
                anilist_staff_name += ', ' + a_staff['node']['name']['first']

            names_to_compare = [anilist_staff_name]
            if '' not in a_staff['node']['name']['alternative']:
                for name in a_staff['node']['name']['alternative']:
                    names_to_compare.append(name)

            for j_staff in jikan_staff:
                for a_name in names_to_compare:
                    if compare(a_name, j_staff['name']) > .7:
                        Metadata._log.debug(f'Staff Member (MyAnimeList): {j_staff}')

                        role = a_staff['role'].lower()
                        if 'story & art' in role:
                            roles.append('story')
                            roles.append('art')
                            self._add_staff_member('story', a_staff, j_staff)
                            self._add_staff_member('art', a_staff, j_staff)
                            break
                        elif 'story' in role:
                            roles.append('story')
                            self._add_staff_member('story', a_staff, j_staff)
                            break
                        elif 'art' in role:
                            roles.append('art')
                            self._add_staff_member('art', a_staff, j_staff)
                            break
                        else:
                            Metadata._log.warning(f'Expected role not found for staff member "{a_name}"; instead'
                                                  f' found "{role}"')
                            break

        # Validate expected roles for staff members
        role_set = ['story', 'art']

        if set(roles) != set(role_set):
            Metadata._log.warning(f'Not all expected roles are present for series "{self.search_value}"; '
                                  f'double check ID "{self._id}"')

    def _add_staff_member(self, role, a_staff, j_staff):
        self.staff[role][a_staff['node']['name']['full']] = {
            'mal_id': j_staff['mal_id'],
            'first_name': a_staff['node']['name']['first'],
            'last_name': a_staff['node']['name']['last'],
            'anilist_url': a_staff['node']['siteUrl'],
            'mal_url': j_staff['url']
        }

    def _parse_serializations(self, serializations, logging_info):
        Metadata._log.info('Parsing serializations...')
        for serialization in serializations:
            Metadata._log.debug(serialization)
            self.serializations[serialization['name'].strip('.')] = {
                'mal_id': serialization['mal_id'],
                'url': serialization['url']
            }

    def test_value(self):
        return {
            'series_title': self.series_title,
            'series_title_eng': self.series_title_eng,
            'series_title_jap': self.series_title_jap,
            'status': self.status,
            'mal_url': self.mal_url,
            'anilist_url': self.anilist_url,
            'publish_date': self.publish_date,
            'genres': self.genres,
            'staff': self.staff,
            'serializations': self.serializations
        }