"""Polite, bounded public-source requests. No access-control workarounds."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get(url: str) -> requests.Response:
    session = requests.Session()
    session.headers['User-Agent'] = 'MacroIndexCalendar/1.0 (+https://github.com/ChetinSelim/macro-index-calendar)'
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
    response = session.get(url, timeout=(15, 45))
    response.raise_for_status()
    return response
