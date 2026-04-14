# knowledge/etl/scraping/simcv_client.py
"""SimCV Client — searches the UNESA SimCV system for lecturer NIP/NIDN data."""

import requests
from .config import HEADERS


class SimCVClient:
    def __init__(self):
        self.url = 'https://cv.unesa.ac.id/'
        
    def search(self, query):
        if not query or len(str(query)) < 3: return []
        try:
            params = {
                'draw': 1, 'start': 0, 'length': 5,
                'search[value]': query, 'search[regex]': 'false',
                'columns[0][data]': 'namalengkap', 'columns[0][searchable]': 'true',
                'order[0][column]': 0, 'order[0][dir]': 'asc',
            }
            headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': HEADERS['User-Agent']
            }
            resp = requests.get(self.url, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get('data', [])
                return data if isinstance(data, list) else []
        except: pass
        return []
