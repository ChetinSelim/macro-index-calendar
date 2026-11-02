"""MSCI's published structured schedule, with distinct review phases."""
import csv
import io
import re
from datetime import date, datetime, timedelta

from src.models import Event, SourceResult
from src.sources.http import get

URL = 'https://www.msci.com/eqb/pressreleases/archive/ir_dates.csv'
PAGE = 'https://www.msci.com/eqb/fm/index_review.html'


def parse_csv(text: str) -> list[Event]:
    events = []
    for row in csv.reader(io.StringIO(text.lstrip('\ufeff'))):
        if not row:
            continue
        cells = row[0].split('|')
        if len(cells) != 4 or not re.fullmatch(r'[A-Za-z]{3}, 20\d{2}', cells[0].strip()):
            continue
        period = datetime.strptime(cells[0].strip(), '%b, %Y')
        announcement = datetime.strptime(cells[2].strip(), '%m-%d-%Y').date()
        effective = datetime.strptime(cells[3].strip(), '%m-%d-%Y').date()
        if not announcement < effective or (effective - announcement).days > 60:
            raise ValueError('Implausible MSCI review dates')
        key = f'msci:{period:%Y-%m}'
        name = f'MSCI {period:%B %Y} Index Review'
        events.extend([
            Event(f'{key}:announcement', 'msci', f'{name} — announcement', announcement,
                  URL, 'Official announcement date from MSCI\'s next-eight-review CSV. '
                  'Date only; exact publication time is not supplied. MSCI may change the schedule.',
                  'confirmed', 'announcement'),
            Event(f'{key}:effective', 'msci', f'{name} — effective', effective, URL,
                  'Official effective date. Review implementation occurs at the relevant market '
                  'close before this effective date; this is a separate phase from announcement. '
                  'No single global close time is assumed.', 'confirmed', 'effective'),
        ])
        implementation = effective - timedelta(days=1)
        while implementation.weekday() >= 5:
            implementation -= timedelta(days=1)
        events.append(Event(f'{key}:implementation', 'msci',
                            f'{name} — implementation window (calculated)', implementation, URL,
                            'Calculated prior-weekday implementation window from the published effective date. '
                            'This is an indicative close window, not an official published implementation date '
                            'or a common timestamp across global markets. Local holidays and index-specific '
                            'notices can alter market treatment; consult the review announcement. '
                            f'Official effective date: {effective}.', 'calculated', 'implementation'))
    if len(events) < 6 or len({e.key for e in events}) != len(events):
        raise ValueError('MSCI CSV empty, duplicated or changed')
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    try:
        events = parse_csv(get(URL).text)
        return [SourceResult('msci', [e for e in events if today <= e.start <= horizon], [URL, PAGE],
                             ['Announcement/effective dates are official; implementation windows are calculated and require local-market confirmation.'])]
    except Exception as exc:
        return [SourceResult('msci', source_urls=[URL, PAGE], status='unavailable',
                             notes=[f'Official MSCI structured schedule unavailable: {type(exc).__name__}: {exc}. No dates invented.'])]
