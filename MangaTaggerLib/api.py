import logging
import requests
import time
from datetime import datetime
from typing import Optional, Dict, Mapping, Union, Any

from jikanpy import Jikan


class MTJikan(Jikan):
    def __init__(
            self,
            selected_base: Optional[str] = None,
            session: Optional[requests.Session] = None,
    ) -> None:
        super(MTJikan, self).__init__(selected_base, session)
        self.calls_second = 0
        self.calls_minute = 0
        self.last_api_call = datetime.now()

    def search(
            self,
            search_type: str,
            query: str,
            page: Optional[int] = None,
            parameters: Optional[Mapping[str, Optional[Union[int, str, float]]]] = None,
    ) -> Dict[str, Any]:
        self._check_rate_seconds()
        self._check_rate_minutes()

        self.calls_second += 1
        self.calls_minute += 1
        self.last_api_call = datetime.now()
        return super(MTJikan, self).search(search_type, query, page, parameters)

    def manga(
            self, id: int, extension: Optional[str] = None, page: Optional[int] = None
    ) -> Dict[str, Any]:
        self._check_rate_seconds()
        self._check_rate_minutes()

        self.calls_second += 1
        self.calls_minute += 1
        self.last_api_call = datetime.now()
        return super(MTJikan, self).manga(id, extension, page)

    # Rate Limit: 2 requests/second
    def _check_rate_seconds(self):
        last_api_call_delta = (datetime.now() - self.last_api_call).total_seconds()

        if self.calls_second > 2 and last_api_call_delta < 1:
            time.sleep(1)
        elif last_api_call_delta > 1:
            self.calls_second = 0

    # Rate Limit: 30 requests/minute
    def _check_rate_minutes(self):
        last_api_call_delta = (datetime.now() - self.last_api_call).total_seconds()

        if self.calls_minute > 30 and last_api_call_delta < 60:
            time.sleep(61 - last_api_call_delta)
        elif last_api_call_delta > 60:
            self.calls_minute = 0


class AniList:
    _log = None

    @classmethod
    def initialize(cls):
        cls._log = logging.getLogger(f'{cls.__module__}.{cls.__name__}')

    @classmethod
    def _post(cls, query, variables, logging_info):
        try:
            response = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables})
        except Exception as e:
            cls._log.exception(e, extra=logging_info)
            cls._log.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.',
                             extra=logging_info)
            return None

        cls._log.debug(f'Query: {query}')
        cls._log.debug(f'Variables: {variables}')
        cls._log.debug(f'Response JSON: {response.json()}')

        return response.json()['data']['Media']

    @classmethod
    def search_staff_by_mal_id(cls, mal_id, logging_info):
        query = '''
        query search_staff_by_mal_id ($mal_id: Int) {
          Media (idMal: $mal_id, type: MANGA) {
            siteUrl
            staff {
              edges {
                node{
                  name {
                    first
                    last
                    full
                    alternative
                  }
                  siteUrl
                }
                role
              }
            }
          }
        }
        '''

        variables = {
            'mal_id': mal_id
        }

        return cls._post(query, variables, logging_info)

    @classmethod
    def search_for_manga_title_by_mal_id(cls, mal_id, logging_info):
        query = '''
        query search_manga_by_mal_id ($mal_id: Int) {
          Media (idMal: $mal_id, type: MANGA) {
            title {
              romaji
              english
            }
          }
        }
        '''

        variables = {
            'mal_id': mal_id
        }

        return cls._post(query, variables, logging_info)
