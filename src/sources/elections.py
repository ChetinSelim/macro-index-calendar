"""US federal general-election days; no statewide polling-hour assumptions."""
from datetime import date, datetime, timedelta, timezone
import re
from bs4 import BeautifulSoup
from src.models import Event, SourceResult
from src.sources.http import get
from src.state import IntegrityError

FEC_URL = 'https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/'
PRESIDENT_URL = 'https://www.usa.gov/presidential-general-election'
MIDTERM_URL = 'https://www.usa.gov/midterm-elections'
# FEC's explicit national date, reviewed through official web retrieval.
REVIEWED_AT = '2026-11-02T21:46:29+00:00'
REVIEWED_DATES = {2026: date(2026, 11, 3)}


def election_day(year: int) -> date:
    if year % 2:
        raise ValueError('Regular federal general elections require an even year')
    first = date(year, 11, 1)
    return first + timedelta(days=(0 - first.weekday()) % 7 + 1)


def parse_fec(html: str) -> dict[int, date]:
    text = ' '.join(BeautifulSoup(html, 'html.parser').get_text(' ', strip=True).split())
    matches = re.findall(r'(November \d{1,2}, \d{4})\s*,?\s+is the next regularly scheduled federal General Election date', text, re.I)
    if not matches:
        raise ValueError('Explicit FEC general-election date missing or changed')
    result = {}
    for value in matches:
        day = datetime.strptime(value, '%B %d, %Y').date()
        if day != election_day(day.year):
            raise IntegrityError('FEC election date differs from the current rule; review required')
        result[day.year] = day
    return result


def validate_rules(president_html: str, midterm_html: str):
    president = ' '.join(BeautifulSoup(president_html, 'html.parser').get_text(' ', strip=True).lower().split())
    midterm = ' '.join(BeautifulSoup(midterm_html, 'html.parser').get_text(' ', strip=True).lower().split())
    if not ('every four years' in president and 'first tuesday after the first monday in november' in president
            and 'congressional elections happen every two years' in midterm):
        raise ValueError('Official election timing rules missing or changed')


def fetch(today: date, horizon: date) -> list[SourceResult]:
    notes = [
        'US federal general-election days only: midterms and presidential elections. Elections have a separate 48-month lookahead.',
        'All-day US election-date markers. Poll opening/closing times vary by jurisdiction; results may arrive overnight in London or later. Primaries, runoffs, special elections and certification dates are not included.',
    ]
    verified = REVIEWED_AT
    rule_live = False
    try:
        validate_rules(get(PRESIDENT_URL).text, get(MIDTERM_URL).text)
        rule_live = True
        verified = datetime.now(timezone.utc).isoformat()
        notes.append('USAGov election timing rules checked live; dates without an explicit national schedule entry remain calculated.')
    except Exception as exc:
        notes.append(f'Live rule refresh unavailable ({type(exc).__name__}: {exc}); using rules reviewed {REVIEWED_AT}.')
    confirmed = dict(REVIEWED_DATES)
    fec_live = False
    try:
        confirmed.update(parse_fec(get(FEC_URL).text))
        fec_live = True
    except IntegrityError:
        raise
    except Exception as exc:
        notes.append(f'Live FEC date refresh unavailable ({type(exc).__name__}: {exc}); only the 2026 date was explicitly verified on {REVIEWED_AT}. Later dates are calculated from the official rule.')
    events = []
    for year in range(today.year, horizon.year + 1):
        if year % 2:
            continue
        day = election_day(year)
        if not today <= day <= horizon:
            continue
        presidential = year % 4 == 0
        kind = 'Presidential & Congressional Elections' if presidential else 'Midterm Elections'
        certainty = 'confirmed' if year in confirmed else 'calculated'
        source = FEC_URL if certainty == 'confirmed' else PRESIDENT_URL
        evidence = (f'Explicit national date published by the FEC; reviewed {REVIEWED_AT}.' if year in REVIEWED_DATES and not fec_live
                    else 'Explicit national date retrieved from the FEC.' if certainty == 'confirmed'
                    else 'Calculated from the official first-Tuesday-after-first-Monday November rule; presidential elections every four years and congressional elections every two years.')
        events.append(Event(f'us-federal-general:{year}', 'elections', f'US | {year} {kind}', day, source,
            evidence + ' All-day US election-date marker, not a nationwide poll-closing time or a forecast result announcement. State/local polling hours, early voting, mail ballots and result/certification schedules differ. '
            + f'Official timing information: {PRESIDENT_URL}; {MIDTERM_URL}.', certainty, 'election-day'))
    return [SourceResult('elections', events, [FEC_URL, PRESIDENT_URL, MIDTERM_URL], notes,
                         'ok' if rule_live and fec_live else 'partial', verified_at=verified)]
