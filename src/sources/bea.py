"""Official BEA PCE release feed, with official schedule HTML as fallback."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from icalendar import Calendar
from src.models import Event, SourceResult
from src.sources.http import get

URL = 'https://www.bea.gov/news/schedule'
NEXT_URL = URL + '/next-year'
ICS_URL = URL + '/ics/online-calendar-subscription.ics'
NY = ZoneInfo('America/New_York')


def _event(title: str, start: datetime, source: str) -> Event:
    match = re.fullmatch(r'Personal Income and Outlays,\s*([A-Za-z]+(?:\s+and\s+[A-Za-z]+)?)\s+(\d{4})', title.strip(), re.I)
    if not match:
        raise ValueError(f'PCE release has unknown reporting period: {title}')
    periods = [datetime.strptime(f'{month} {match[2]}', '%B %Y').strftime('%Y-%m') for month in re.split(r'\s+and\s+', match[1], flags=re.I)]
    period = '+'.join(periods)
    if start.tzinfo is None:
        raise ValueError('BEA release time is timezone-naive')
    return Event(f'pce:{period}', 'pce', f'US PCE / Personal Income and Outlays ({period})', start.astimezone(NY), source,
        f'Personal Income and Outlays for {match[1]} {match[2]}, including PCE price indexes. Official release time in America/New_York.')


def parse_ics(content: bytes | str) -> list[Event]:
    events = []
    for item in Calendar.from_ical(content).walk('VEVENT'):
        title = str(item.get('SUMMARY', ''))
        if not title.lower().startswith('personal income and outlays,'):
            continue
        start = item.decoded('DTSTART')
        if not isinstance(start, datetime):
            raise ValueError('BEA PCE ICS event lost release time')
        events.append(_event(title, start, ICS_URL))
    if not events:
        raise ValueError('No PCE releases in BEA calendar')
    return events


def parse_html(html: str, source: str = URL) -> list[Event]:
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.select_one('#release-schedule-table')
    if table is None:
        raise ValueError('BEA release table missing')
    year = re.search(r'Year\s+(\d{4})', table.get_text(' ', strip=True))
    if not year:
        raise ValueError('BEA release table lost year')
    events = []
    for row in table.select('tbody tr'):
        title = row.select_one('.release-title')
        if not title or not title.get_text(' ', strip=True).lower().startswith('personal income and outlays,'):
            continue
        date_cell = row.select_one('.scheduled-date')
        day, clock = date_cell.select_one('.release-date'), date_cell.select_one('small')
        if day is None or clock is None:
            raise ValueError('BEA PCE date/time missing')
        start = datetime.strptime(f'{day.get_text(strip=True)} {year[1]} {clock.get_text(strip=True)}', '%B %d %Y %I:%M %p').replace(tzinfo=NY)
        events.append(_event(title.get_text(' ', strip=True), start, source))
    if not events:
        raise ValueError('No PCE releases in BEA HTML table')
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    notes = []
    urls = [ICS_URL]
    try:
        events = parse_ics(get(ICS_URL).content)
    except Exception as exc:
        notes.append(f'ICS fetch/parse failed ({type(exc).__name__}: {exc}); using fresh official HTML schedules.')
        events = []
        for url in (URL, NEXT_URL):
            urls.append(url)
            # Fail rather than silently drop one published year.
            events.extend(parse_html(get(url).text, url))
    events = sorted({e.key: e for e in events if today <= e.start.date() <= horizon}.values(), key=lambda e: e.start)
    notes.append(f'Published PCE coverage ends {max(e.start.date() for e in events)}; later dates are not inferred.' if events else 'No published PCE dates in requested window.')
    return [SourceResult('pce', events, urls, notes, 'ok' if events else 'unavailable')]
