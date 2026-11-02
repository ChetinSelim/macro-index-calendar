"""Russell US semiannual reconstitution: live announced dates plus rule projections."""
import calendar
import json
import re
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.models import Event, SourceResult
from src.sources.http import get
from src.sources.options import nth_friday, previous_session, next_session

URL = 'https://www.lseg.com/en/ftse-russell/russell-reconstitution'
RULE_URL = 'https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/russell-us-indexes-construction-and-methodology.pdf'
REVIEWED_AT = '2026-11-02T18:35:00+00:00'


def calculate(today: date, horizon: date) -> list[Event]:
    events = []
    for year in range(max(2026, today.year), horizon.year + 1):
        for month, rank_month, weeks in ((6, 4, 5), (12, 10, 4)):
            close = previous_session(nth_friday(year, month, 4 if month == 6 else 2))
            rank = previous_session(date(year, rank_month, calendar.monthrange(year, rank_month)[1]))
            prelim = previous_session(close - timedelta(weeks=weeks))
            effective = next_session(close)
            period = f'{year}-{month:02d}'
            description = (
                'Calculated from FTSE Russell US Equity Indices Ground Rules, August 2026, '
                'Appendix F: semiannual June/December reconstitution from 2026. Rank on '
                'last business day of April/October; preliminary information five/four '
                'weeks before implementation; implementation after close on fourth Friday '
                'in June/second Friday in December. XNYS sessions handle calendar holidays. '
                'These are projections until the specific cycle is officially announced. '
                'Weekly preliminary-list update dates are only added from an explicit notice. '
            )
            for phase, day, label in (
                ('rank', rank, 'rank day'), ('preliminary', prelim, 'preliminary lists'),
                ('implementation', close, 'implementation — after US close'),
                ('effective', effective, 'effective session'),
            ):
                if today <= day <= horizon:
                    events.append(Event(f'russell:{period}:{phase}', 'russell',
                                        f'Russell US {year} {calendar.month_name[month]} reconstitution — {label}',
                                        day, RULE_URL, description, 'calculated', phase))
    return events


def parse_announced(html: str) -> list[Event]:
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    current = re.search(r'(June|December) (20\d{2}) Russell Reconstitution Calendar', text)
    if not current:
        raise ValueError('Current Russell reconstitution calendar heading missing')
    month_name, year = current[1], int(current[2])
    month = 6 if month_name == 'June' else 12
    # FAQ JSON-LD is the structured statement, separate from visual calendar tables.
    faq = ''
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            blob = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        nodes = blob if isinstance(blob, list) else [blob]
        for node in nodes:
            for question in node.get('mainEntity', []):
                if 'When are the reconstitutions' in question.get('name', ''):
                    faq = question.get('acceptedAnswer', {}).get('text', '')
    if not faq:
        raise ValueError('Structured Russell calendar FAQ missing')
    relevant = faq.split('The newly reconstituted')[0]
    if f'{month_name} {year}' not in relevant:
        raise ValueError('Russell FAQ and current cycle disagree')
    dates = []
    active_month = None
    # Month names propagate across "November 20, November 27, December 4, and December 11".
    for match in re.finditer(r'(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})(?!\d)', relevant):
        if match[1]:
            active_month = match[1]
        if active_month:
            try:
                value = datetime.strptime(f'{active_month} {match[2]} {year}', '%B %d %Y').date()
                if value not in dates:
                    dates.append(value)
            except ValueError:
                pass
    # First match from "December 2026" must not be interpreted as day 20/26.
    dates = [d for d in dates if month-2 <= d.month <= month]
    if not dates:
        raise ValueError('No announced Russell preliminary dates')
    close_match = re.search(r'after (?:the )?(?:US )?market close on ([A-Za-z]+ \d{1,2})(?:, (20\d{2}))?', faq)
    if not close_match:
        raise ValueError('Russell implementation statement missing')
    close = datetime.strptime(f'{close_match[1]} {close_match[2] or year}', '%B %d %Y').date()
    if close.year != year or close.month != month:
        raise ValueError('Russell implementation cycle mismatch')
    dates = sorted(d for d in dates if d <= close)
    key = f'russell:{year}-{month:02d}'
    name = f'Russell US {year} {month_name} reconstitution'
    events = []
    for i, day in enumerate(dates):
        phase = 'preliminary' if i == 0 else f'preliminary-update-{i}'
        label = 'preliminary lists' if i == 0 else f'preliminary lists update {i}'
        events.append(Event(f'{key}:{phase}', 'russell', f'{name} — {label}', day, URL,
                            'Explicit date in the official LSEG reconstitution calendar FAQ. '
                            'List publication has no exact time supplied.', 'confirmed', 'preliminary'))
    events.append(Event(f'{key}:implementation', 'russell', f'{name} — implementation after US close',
                        close, URL, 'Official implementation day, after US market close. '
                        'All-day marker avoids inventing an exact publication or closing timestamp.', 'confirmed', 'implementation'))
    rank_match = re.search(r'rank day.*?falls on.*?([A-Za-z]+ \d{1,2})', text, re.I)
    if rank_match:
        rank = datetime.strptime(f'{rank_match[1]} {year}', '%B %d %Y').date()
        events.append(Event(f'{key}:rank', 'russell', f'{name} — rank day', rank, URL,
                            'Explicit rank day in the official LSEG reconstitution calendar.', 'confirmed', 'rank'))
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    events = {e.key: e for e in calculate(today, horizon)}
    notes = ['June and December semiannual reconstitution from 2026; older notices mentioning November are superseded.',
             'Specific live announced phases are confirmed; future cycles and effective-session dates are calculated from the methodology.']
    verified = None
    try:
        live = parse_announced(get(URL).text)
        events.update({e.key: e for e in live if today <= e.start <= horizon})
        verified = datetime.now(timezone.utc).isoformat()
        notes.append('Official current-cycle structured FAQ retrieved live.')
    except Exception as exc:
        notes.append(f'Live announced calendar unavailable: {type(exc).__name__}: {exc}. No confirmed dates invented.')
        verified = REVIEWED_AT
    try:
        reader = PdfReader(BytesIO(get(RULE_URL).content))
        page = ' '.join(p.extract_text() or '' for p in reader.pages[-8:])
        normalized = ' '.join(page.split()).lower()
        if not all(s in normalized for s in ('last business day of april', 'last business day of october', 'four weeks prior')):
            raise ValueError('Russell Appendix F rule changed or missing')
        verified = datetime.now(timezone.utc).isoformat()
        notes.append('Official methodology Appendix F retrieved live. Future dates repeat its rules until a newer notice changes them; they are not confirmed schedules.')
    except Exception as exc:
        verified = REVIEWED_AT
        notes.append(f'Live methodology refresh incomplete ({type(exc).__name__}: {exc}); '
                     f'projections use rules reviewed at {REVIEWED_AT}, not a fresh official schedule.')
    return [SourceResult('russell', sorted(events.values(), key=lambda e: (e.start, e.key)),
                         [URL, RULE_URL], notes, 'partial', verified_at=verified)]
