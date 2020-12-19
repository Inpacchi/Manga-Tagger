import json
import requests


def search
try:
    response = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables})
except Exception as e:
    LOG.exception(e, extra=logging_info)
    LOG.warning('Manga Tagger is unfamiliar with this error. Please log an issue for investigation.',
                extra=logging_info)
    return None

LOG.debug(f'mal_id: {mal_id}')
LOG.debug(f'Response JSON: {response.json()}')

return response.json()['data']['Media']