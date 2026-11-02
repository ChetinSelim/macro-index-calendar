"""Bank of England official MPC announcement calendar."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from src.models import Event, SourceResult
from src.sources.http import get

URL = 'https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates'
TIME_URL = 'https://www.bankofengland.co.uk/monetary-policy'


def parse(html: str) -> list[Event]:
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    for heading in soup.find_all(re.compile('^h[1-6]$')):
        match = re.fullmatch(r'(\d{4})\s+(confirmed|provisional)\s+dates', heading.get_text(' ', strip=True), re.I)
        if not match:
            continue
        year, certainty = int(match[1]), match[2].lower()
        table = heading.find_next('table')
        if table is None:
            raise ValueError(f'Missing MPC table for {year}')
        ordinal = 0
        for row in table.select('tr'):
            cells = row.find_all('td')
            if not cells:
                continue
            day = ' '.join(cells[0].get_text(' ', strip=True).split())
            parsed = datetime.strptime(f'{day} {year}', '%A %d %B %Y')
            ordinal += 1
            start = parsed.replace(hour=12, tzinfo=ZoneInfo('Europe/London'))
            events.append(Event(f'boe:{year}:meeting-{ordinal}', 'boe', 'Bank of England MPC decision', start, URL,
                f'MPC policy decision and minutes, published at 12 noon Europe/London. Time policy: {TIME_URL}', certainty))
        if ordinal != 8:
            raise ValueError(f'Expected eight published MPC dates for {year}, found {ordinal}')
    if not events:
        raise ValueError('No MPC date tables found')
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    events = [e for e in parse(get(URL).text) if today <= e.start.date() <= horizon]
    return [SourceResult('boe', events, [URL, TIME_URL], [f'Published coverage ends {max(e.start.date() for e in events)}; later dates are not inferred.'] if events else ['No published MPC dates in requested window.'], 'ok' if events else 'unavailable')]
