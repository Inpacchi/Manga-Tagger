import logging
import re
from datetime import datetime

from jikanpy import Jikan, APIException
from pytz import timezone

from MangaTaggerLib.api import MTJikan
from MangaTaggerLib.errors import MetadataNotCompleteError
from MangaTaggerLib.utils import AppSettings, compare
from googletrans import Translator

anilistpreferences = ["english", "romaji", "native"]

class Metadata:
    _log = None

    @classmethod
    def fully_qualified_class_name(cls):
        return f'{cls.__module__}.{cls.__name__}'

    def __init__(self, manga_title, logging_info, details=None, db_details=None):
        Metadata._log = logging.getLogger(self.fully_qualified_class_name())

        self.search_value = manga_title
        self.title = None
        Metadata._log.info(f'Creating Metadata model for series "{manga_title}"...', extra=logging_info)

        if details:  # If details are grabbed from Jikan and Anilist APIs
            self._construct_api_metadata(details, logging_info)
        elif db_details:  # If details were stored in the database
            self._construct_database_metadata(db_details)
        else:
            Metadata._log.exception(MetadataNotCompleteError, extra=logging_info)
        Metadata._log.debug(f'{self.search_value} Metadata Model: {self.__dict__.__str__()}')

        logging_info['metadata'] = self.__dict__
        Metadata._log.info('Successfully created Metadata model.', extra=logging_info)

    def _construct_api_metadata(self, details, logging_info):
        self.source = details["source"]
        #self._id = tryKey(details, "mal_id")
        self.series_title = tryKey(details, "series_title")

        if tryKey(details, "series_title_eng") is None:
            self.series_title_eng = None
        else:
            self.series_title_eng = tryKey(details, "series_title_eng")

        if tryKey(details, "series_title_jap") is None:
            self.series_title_jap = None
        else:
            self.series_title_jap = tryKey(details, "series_title_jap")

        self.status = tryKey(details, "status")
        self.type = tryKey(details, "type")
        self.description = tryKey(details, "description")
        self.mal_url = tryKey(details, "mal_url")
        self.anilist_url = tryKey(details, "anilist_url")
        if tryKey(details, "mangaupdates_url") is not None:
            self.mal_url = details["mangaupdates_url"]
        self.publish_date = tryKey(details, "publish_date")
        self.genres = tryKey(details, "genres")
        staff = tryKey(details, "staff")
        if staff is not None:
            self.staff = {"story": tryKey(staff, "story"), "art": tryKey(staff, "art")}
        else:
            self.staff = {}
        self.serializations = tryKey(details, "serializations")

        # self._construct_publish_date(details['published']['from'])
        # self._parse_genres(details['genres'], logging_info)
        # self._parse_staff(details['staff']['edges'], details['authors'], logging_info)
        # self._parse_serializations(details['serializations'], logging_info)

        # self.scrape_date = datetime.now().date().strftime('%Y-%m-%d %I:%M %p')
        self.scrape_date = timezone(AppSettings.timezone).localize(datetime.now()).strftime('%Y-%m-%d %I:%M %p %Z')

    def _construct_database_metadata(self, details):
        self.source = details["source"]
        self._id = details['_id']
        self.series_title = details['series_title']
        self.series_title_eng = details['series_title_eng']
        self.series_title_jap = details['series_title_jap']
        self.status = details['status']
        self.type = details['type']
        self.description = details['description']
        self.mal_url = details['mal_url']
        self.anilist_url = details['anilist_url']
        self.publish_date = details['publish_date']
        self.genres = details['genres']
        self.staff = details['staff']
        self.serializations = details['serializations']
        self.publish_date = details['publish_date']
        self.scrape_date = details['scrape_date']

    def _construct_publish_date(self, date):
        date = date[:date.index('T')]
        self.publish_date = datetime.strptime(date, '%Y-%m-%d').strftime('%Y-%m-%d')
        Metadata._log.debug(f'Publish date constructed: {self.publish_date}')

    def _parse_genres(self, genres, logging_info):
        Metadata._log.info('Parsing genres...', extra=logging_info)
        for genre in genres:
            Metadata._log.debug(f'Genre found: {genre}')
            self.genres.append(genre['name'])

    def _parse_staff(self, anilist_staff, jikan_staff, logging_info):
        Metadata._log.info('Parsing staff roles...', extra=logging_info)

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
                                                  f' found "{role}"', extra=logging_info)
                            break

        # Validate expected roles for staff members
        role_set = ['story', 'art']

        if set(roles) != set(role_set):
            Metadata._log.warning(f'Not all expected roles are present for series "{self.search_value}"; '
                                  f'double check ID "{self._id}"', extra=logging_info)

    def _add_staff_member(self, role, a_staff, j_staff):
        self.staff[role][a_staff['node']['name']['full']] = {
            'mal_id': j_staff['mal_id'],
            'first_name': a_staff['node']['name']['first'],
            'last_name': a_staff['node']['name']['last'],
            'anilist_url': a_staff['node']['siteUrl'],
            'mal_url': j_staff['url']
        }

    def _parse_serializations(self, serializations, logging_info):
        Metadata._log.info('Parsing serializations...', extra=logging_info)
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


class Data:
    source = None
    anilist_id = None
    mal_id = None
    mangaupdates_id = None
    series_title = None
    series_title_eng = None
    series_title_jap = None
    status = None
    type = None
    description = None
    mal_url = None
    anilist_url = None
    mangaupdates_url = None
    publish_date = None
    genres = []
    staff = {"story": [], "art": []}
    serializations = {}

    def __init__(self, details, title, MU_id=None):
        if details["source"] == "AniList":
            source = details["source"]
            if details["format"] == "ONE_SHOT":
                for x in details["relations"]["edges"]:
                    if x["relationType"] == "ALTERNATIVE":
                        details = x["node"]
                        details["source"] = source
            self.series_title = title
            self.anilist_id = details["id"]
            self.mal_id = details["idMal"]
            self.series_title_eng = details["title"]["english"]
            if self.series_title_eng is None or self.series_title_eng == "null":
                for x in details["synonyms"]:
                    if Translator().detect(x).lang == "en":
                        self.series_title_eng = x
                        break
            self.series_title_jap = details["title"]["romaji"]
            pref = {"english": self.series_title_eng, "romaji": details["title"]["romaji"], "native": details["title"]["native"]}
            for x in anilistpreferences:
                if pref[x] is not None and pref[x] != "null":
                    self.series_title = pref[x]
                    break
            self.status = details["status"]
            self.type = details["type"]
            if details["description"]:
                self.description = cleanDescription(details["description"])
            if self.mal_id is not None:
                self.mal_url = r"myanimelist.net/manga/" + str(self.mal_id)
            self.anilist_url = details["siteUrl"]
            self.publish_date = datetime.strptime(
                str(details["startDate"]["year"]) + "-" + str(details["startDate"]["month"]) + "-" + str(
                    details["startDate"]["day"]),
                '%Y-%m-%d').strftime('%Y-%m-%d')
            self.genres = details["genres"]
            staff = details["staff"]["edges"]
            for person in staff:
                if person["role"] == "Story & Art":
                    self.staff["art"].append(person["node"]["name"]["full"])
                    self.staff["story"].append(person["node"]["name"]["full"])
                elif person["role"] == "Art":
                    self.staff["art"].append(person["node"]["name"]["full"])
                elif person["role"] == "Story":
                    self.staff["story"].append(person["node"]["name"]["full"])
            if self.mal_id is not None:
                try:
                    self.serializations = ", ".join([x["name"] for x in MTJikan().manga(self.mal_id)["serializations"]])
                except APIException:
                    pass
        elif details["source"] == "MangaUpdates":
            self.series_title = title
            self.mangaupdates_id = MU_id
            if "Complete" in details["status"]:
                self.status = "Finished"
            else:
                self.status = "Publishing"
            self.type = details["type"]
            if details["description"]:
                self.description = cleanDescription(details["description"])
            self.mangaupdates_url = r"https://www.mangaupdates.com/series.html?id=" + str(MU_id)
            self.publish_date = details["year"]
            self.genres = details["genres"]
            self.staff["story"] = [x for x in details["authors"]]
            self.staff["art"] = [x for x in details["artists"]]
            self.serializations = details["serialized"]["name"]
        elif details["source"] == "MAL":
            self.series_title = title
            self.mal_id = details["mal_id"]
            self.series_title_eng = details["title_english"]
            self.series_title_jap = details["title_japanese"]
            self.status = details["status"]
            self.type = details["type"]
            if details["synopsis"]:
                self.description = cleanDescription(details["synopsis"])
            self.mal_url = details["url"]
            date = details["published"]["from"]
            date = date[:date.index('T')]
            self.publish_date = datetime.strptime(date, '%Y-%m-%d').strftime('%Y-%m-%d')
            self.genres = [x["name"] for x in details["genres"]]
            query = '''
            query search_manga_by_mal_id ($mal_id: Int) {
              Media (idMal: $mal_id, type: MANGA) {
                title {
                  romaji
                  english
                  native
                }
              }
            }
            '''

            variables = {
                'mal_id': self.mal_id
            }
            asd = MTJikan().manga(self.mal_id)
            authors1 = asd["authors"]
            authors2 = [x["mal_id"] for x in authors1]
            people = [Jikan().person(x) for x in authors2]
            staff = {}
            for x in people:
                for y in x["published_manga"]:
                    if y["manga"]["mal_id"] == self.mal_id:
                        staff[x["name"]] = y["position"]
            for person in staff.items():
                if person[1] == "Story & Art":
                    self.staff["art"].append(person[0])
                    self.staff["story"].append(person[0])
                elif person[1] == "Art":
                    self.staff["art"].append(person[0])
                elif person[1] == "Story":
                    self.staff["story"].append(person[0])
            self.serializations = ", ".join([x["name"] for x in MTJikan().manga(self.mal_id)["serializations"]])
        elif details["source"] == "NHentai" or details["source"] == "Fakku":
            self.series_title = details["series_title"]
            self.mangaupdates_id = None
            self.status = None
            self.type = details["type"]
            if details["description"]:
                self.description = cleanDescription(details["description"])
            self.mal_url = details["mal_url"]
            self.publish_date = None
            self.genres = details["genres"]
            self.staff["story"] = [x for x in details["staff"]["story"]]
            self.staff["art"] = [x for x in details["staff"]["art"]]
            self.serializations = details["serializations"]
        self.source = details["source"]

    def toDict(self):
        dataDict = {
            "source": self.source,
            "anilist_id": self.anilist_id,
            "mal_id": self.mal_id,
            "mangaupdates_id": self.mangaupdates_id,
            "series_title": self.series_title,
            "series_title_eng": self.series_title_eng,
            "series_title_jap": self.series_title_jap,
            "status": self.status,
            "type": self.type,
            "description": self.description,
            "mal_url": self.mal_url,
            "anilist_url": self.anilist_url,
            "mangaupdates_url": self.mangaupdates_url,
            "publish_date": self.publish_date,
            "genres": self.genres,
            "staff": self.staff,
            "serializations": self.serializations
        }
        return dataDict


def tryKey(dct, x):
    try:
        return dct[x]
    except KeyError:
        return None
    
def cleanDescription(x):
    raw = x
    cleaned = re.sub(r'& ?(ld|rd)quo ?[;\]]', '\"', raw)
    cleaned = re.sub(r'& ?(ls|rs)quo ?;', '\'', cleaned)
    cleaned = re.sub(r'& ?ndash ?;', '-', cleaned)
    toDelete = ["<i>", "</i>", "<b>", "</b>"]
    for x in toDelete:
        cleaned = cleaned.replace(x, "")
    cleaned = cleaned.replace("<br>", "\n")
    return cleaned
