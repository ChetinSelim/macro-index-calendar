"""BLS Employment Situation and CPI; official feed, HTML, then reviewed seed.

A blocked source is never worked around. Offline records retain their review
stamp and are partial, with a bounded maximum age.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from icalendar import Calendar
from src.models import Event, SourceResult
from src.sources.http import get

ICS_URL = 'https://www.bls.gov/schedule/news_release/bls.ics'
URLS = {'nfp': 'https://www.bls.gov/schedule/news_release/empsit.htm', 'cpi': 'https://www.bls.gov/schedule/news_release/cpi.htm'}
NAMES = {'nfp': 'Employment Situation', 'cpi': 'Consumer Price Index'}
SEED = Path(__file__).resolve().parents[2] / 'data' / 'macro-bls-reviewed.json'
MAX_SEED_AGE = timedelta(days=90)
NY = ZoneInfo('America/New_York')


def _event(category: str, period: str, start: datetime, source: str) -> Event:
    if start.tzinfo is None:
        raise ValueError('BLS event has no timezone')
    return Event(f'{category}:{period}', category, f'US {NAMES[category]} ({period})', start, source,
        f'{NAMES[category]} for reporting month {period}. BLS times are Eastern Time (America/New_York).')


def parse_ics(content: bytes | str) -> dict[str, list[Event]]:
    events = {k: [] for k in URLS}
    for item in Calendar.from_ical(content).walk('VEVENT'):
        title = str(item.get('SUMMARY', ''))
        for category, name in NAMES.items():
            if not title.lower().startswith(name.lower()):
                continue
            text = title + ' ' + str(item.get('DESCRIPTION', ''))
            period_match = re.search(r'\bfor\s+([A-Za-z]+)\s+(\d{4})\b', text, re.I)
            if not period_match:
                raise ValueError(f'BLS {category} release lost reporting month: {title}')
            period = datetime.strptime(f'{period_match[1]} {period_match[2]}', '%B %Y').strftime('%Y-%m')
            start = item.decoded('DTSTART')
            if not isinstance(start, datetime):
                raise ValueError(f'BLS {category} release lost time')
            # The official feed may encode floating Eastern times. Its HTML
            # calendar explicitly states that all calendar times are Eastern.
            if start.tzinfo is None:
                start = start.replace(tzinfo=NY)
            events[category].append(_event(category, period, start, ICS_URL))
    for category, found in events.items():
        if not found:
            raise ValueError(f'No {category} releases in BLS ICS')
    return events


def parse_html(html: str, category: str) -> list[Event]:
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    for row in soup.select('table tr'):
        cells = row.find_all('td')
        if len(cells) != 3:
            continue
        period, day, clock = [' '.join(c.get_text(' ', strip=True).split()) for c in cells]
        if not re.fullmatch(r'[A-Za-z]+ \d{4}', period):
            continue
        period_key = datetime.strptime(period, '%B %Y').strftime('%Y-%m')
        day = day.replace('.', '')
        try:
            start = datetime.strptime(day + ' ' + clock, '%b %d, %Y %I:%M %p')
        except ValueError:
            start = datetime.strptime(day + ' ' + clock, '%B %d, %Y %I:%M %p')
        events.append(_event(category, period_key, start.replace(tzinfo=NY), URLS[category]))
    if not events:
        raise ValueError(f'No {category} rows in BLS reference-month table')
    return events


def _seed(category: str, today: date, horizon: date, errors: list[str]) -> SourceResult:
    data = json.loads(SEED.read_text())
    reviewed = datetime.fromisoformat(data['verified_at'].replace('Z', '+00:00'))
    # Use requested as-of date for deterministic builds; never refresh the stamp.
    if today > (reviewed + MAX_SEED_AGE).date():
        return SourceResult(category, source_urls=[ICS_URL, URLS[category]], notes=errors + ['Reviewed fallback expired after 90 days; manual official-source review required.'], status='unavailable')
    events = [_event(category, row['period'], datetime.fromisoformat(row['start']).astimezone(NY), URLS[category]) for row in data['releases'][category]]
    events = [e for e in events if today <= e.start.date() <= horizon]
    for event in events:
        event.description += f' Offline official schedule last reviewed {data["verified_at"]}; runtime source access is unavailable, so this event has not been freshly reconfirmed.'
    if not events:
        return SourceResult(category, source_urls=[ICS_URL, URLS[category]], notes=errors + ['No reviewed fallback events in requested window.'], status='unavailable')
    return SourceResult(category, events, [ICS_URL, URLS[category]], errors + [
        f'Offline official schedule reviewed {data["verified_at"]}; NOT freshly network verified. Automatic access unavailable; review needed within 90 days.',
        f'Reviewed published coverage ends {max(e.start.date() for e in events)}; later dates are not inferred.'
    ], 'partial', verified_at=data['verified_at'])


def fetch(today: date, horizon: date) -> list[SourceResult]:
    try:
        parsed = parse_ics(get(ICS_URL).content)
        return [SourceResult(category, [e for e in events if today <= e.start.date() <= horizon], [ICS_URL], [f'Official BLS feed. Published coverage ends {max(e.start.date() for e in events)}; later dates are not inferred.'], 'ok' if any(today <= e.start.date() <= horizon for e in events) else 'unavailable') for category, events in parsed.items()]
    except Exception as exc:
        feed_error = f'BLS ICS unavailable ({type(exc).__name__}: {exc}).'
    results = []
    for category, url in URLS.items():
        try:
            events = [e for e in parse_html(get(url).text, category) if today <= e.start.date() <= horizon]
            results.append(SourceResult(category, events, [ICS_URL, url], [feed_error, 'Using freshly fetched official HTML schedule.', f'Published coverage ends {max(e.start.date() for e in events)}; later dates are not inferred.' if events else 'No published releases in requested window.'], 'ok' if events else 'unavailable'))
        except Exception as exc:
            errors = [feed_error, f'BLS HTML unavailable ({type(exc).__name__}: {exc}).']
            results.append(_seed(category, today, horizon, errors))
    return results
