"""Standard US monthly expiry concentration dates, never a contract settlement feed."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xcals
from bs4 import BeautifulSoup

from src.models import Event, SourceResult
from src.sources.http import get

RULE_URL = 'https://www.optionseducation.org/optionsoverview/options-basics'
HOLIDAY_URL = 'https://www.cboe.com/about/hours/us-options'
CALENDAR_URL = 'https://www.optionseducation.org/referencelibrary/expiration-calendar'
REVIEWED_AT = '2026-11-02T18:35:00+00:00'


def nth_friday(year: int, month: int, n: int = 3) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 7 * (n - 1))


@lru_cache(maxsize=16)
def market_calendar(year: int):
    # Explicit bounds avoid the library's moving default date window.
    cal = xcals.get_calendar('XNYS', start=f'{year-1}-01-01', end=f'{year+1}-12-31')
    # Python dates also avoid pandas datetime-resolution mismatches in is_session.
    return frozenset(cal.sessions.date)


def previous_session(day: date, *, inclusive: bool = True) -> date:
    candidate = day if inclusive else day - timedelta(days=1)
    cal = market_calendar(day.year)
    while candidate not in cal:
        candidate -= timedelta(days=1)
    return candidate


def next_session(day: date) -> date:
    candidate = day + timedelta(days=1)
    cal = market_calendar(day.year)
    while candidate not in cal:
        candidate += timedelta(days=1)
    return candidate


def parse_closures(html: str) -> tuple[set[date], set[int]]:
    """Read Cboe's full-day RTH closures; early closes remain trading sessions."""
    soup = BeautifulSoup(html, 'html.parser')
    closures, years = set(), set()
    import re
    from datetime import datetime
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        match = re.search(r'(20\d{2}) Options Holiday Schedule', heading.get_text(' ', strip=True))
        if not match:
            continue
        year = int(match[1])
        table = heading.find_next('table')
        if table is None:
            continue
        count = 0
        for row in table.find_all('tr'):
            cells = [x.get_text(' ', strip=True) for x in row.find_all('td')]
            if len(cells) >= 3 and cells[2].strip().lower() == 'none':
                day = datetime.strptime(f'{cells[1]} {year}', '%B %d %Y').date()
                closures.add(day)
                count += 1
        if count >= 8:
            years.add(year)
    if not years:
        raise ValueError('Cboe holiday tables missing or changed')
    return closures, years


def calculate(today: date, horizon: date, closures: set[date] | None = None) -> list[Event]:
    events = []
    closures = closures or set()
    for year in range(today.year, horizon.year + 1):
        for month in range(1, 13):
            nominal = nth_friday(year, month)
            day = previous_session(nominal)
            while day in closures:
                day = previous_session(day, inclusive=False)
            if not today <= day <= horizon:
                continue
            quarterly = month in (3, 6, 9, 12)
            title = ('US quarterly expiry concentration / triple witching' if quarterly
                     else 'US standard monthly options expiry')
            description = (
                'Calculated from the standard third-Friday US equity-option convention, '
                'adjusted to the preceding exchange session for a holiday using the XNYS '
                'calendar and, when fetched, Cboe full-day options closures. '
                f'Nominal third Friday: {nominal.isoformat()}. '
                'All-day market-calendar marker; contracts have different last-trading, '
                'exercise and AM/PM settlement rules. This excludes daily/weekly, VIX and '
                'end-of-quarter option series. '
            )
            if quarterly:
                description += (
                    'March/June/September/December concentration is commonly called triple '
                    'witching (sometimes historically quad witching). This label does not '
                    'assert that every futures or option contract expires or settles together. '
                )
            description += f'Rules: {RULE_URL}; holiday source: {HOLIDAY_URL}.'
            events.append(Event(f'options:{year}-{month:02d}:monthly', 'options', title, day,
                                CALENDAR_URL, description, 'calculated', 'expiry'))
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    notes = ['Calculated market markers, not confirmed contract-specific expirations or settlement times.']
    closures, covered = set(), set()
    verified = None
    try:
        closures, covered = parse_closures(get(HOLIDAY_URL).text)
        rule = BeautifulSoup(get(RULE_URL).text, 'html.parser').get_text(' ', strip=True).lower()
        if 'third friday' not in rule or 'thursday' not in rule:
            raise ValueError('Official expiry convention text missing or changed')
        verified = datetime.now(timezone.utc).isoformat()
        notes.append('Official OIC convention and Cboe holiday tables retrieved live; dates remain rule calculations.')
    except Exception as exc:
        notes.append(f'Live official rule/holiday refresh incomplete ({type(exc).__name__}: {exc}); '
                     f'using reviewed rule from {REVIEWED_AT} and exchange-calendars XNYS. Not a fresh official schedule.')
        verified = REVIEWED_AT
    missing = sorted(set(range(today.year, horizon.year + 1)) - covered)
    if missing:
        notes.append(f'Cboe full-year holiday coverage not parsed for {missing}; those dates use XNYS rules and may change.')
    return [SourceResult('options', calculate(today, horizon, closures),
                         [RULE_URL, CALENDAR_URL, HOLIDAY_URL], notes, 'partial', verified_at=verified)]
