"""Federal Reserve published FOMC decisions, never a generated meeting rule."""
import calendar
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from src.models import Event, SourceResult
from src.sources.http import get

URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
TIME_URL = 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20130313a.htm'
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})


def parse(html: str) -> list[Event]:
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    for panel in soup.select('div.panel'):
        heading = panel.find(re.compile('^h[1-6]$'))
        match = re.search(r'(\d{4}) FOMC Meetings', heading.get_text(' ', strip=True) if heading else '')
        if not match:
            continue
        year = int(match[1])
        ordinal = 0
        for row in panel.select('.fomc-meeting'):
            month_node, day_node = row.select_one('.fomc-meeting__month'), row.select_one('.fomc-meeting__date')
            if not month_node or not day_node:
                raise ValueError('FOMC meeting row lost month/date fields')
            days = day_node.get_text(' ', strip=True)
            # Notation votes are not scheduled rate-setting meetings.
            if 'notation vote' in days.lower():
                continue
            ordinal += 1
            month = month_node.get_text(' ', strip=True).split('/')[-1].lower()
            match_day = re.fullmatch(r'(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*\*?', days)
            if not match_day or month not in MONTHS:
                raise ValueError(f'Unrecognized FOMC date: {month} {days}')
            start = datetime.combine(date(year, MONTHS[month], int(match_day[2] or match_day[1])), time(14), ZoneInfo('America/New_York'))
            # Calendar explicitly says dates are tentative until the preceding meeting.
            events.append(Event(f'fomc:{year}:meeting-{ordinal}', 'fomc', 'FOMC policy decision', start, URL,
                'Policy statement on the final meeting day at 14:00 America/New_York. '
                'Published meeting date; tentative until confirmed at the preceding meeting. '
                f'Time policy: {TIME_URL}', 'provisional'))
    # Fed publishes the first meeting of the following year in a prose note.
    for match in re.finditer(r'(?:two-day meeting is scheduled for)\s+([A-Za-z]+)\s+(\d{1,2})[-–](\d{1,2}),?\s+(\d{4})', soup.get_text(' ', strip=True)):
        year, month, day = int(match[4]), MONTHS[match[1].lower()], int(match[3])
        key = f'fomc:{year}:meeting-1'
        if not any(e.key == key for e in events):
            events.append(Event(key, 'fomc', 'FOMC policy decision', datetime(year, month, day, 14, tzinfo=ZoneInfo('America/New_York')), URL,
                f'Published tentative meeting date. Policy statement at 14:00 America/New_York. Time policy: {TIME_URL}', 'provisional'))
    if not events:
        raise ValueError('No FOMC meeting rows found')
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    events = [e for e in parse(get(URL).text) if today <= e.start.date() <= horizon]
    if not events:
        return [SourceResult('fomc', source_urls=[URL, TIME_URL], status='unavailable', notes=['No published FOMC meetings in requested window.'])]
    return [SourceResult('fomc', events, [URL, TIME_URL], ['Only published dates included; future meetings marked provisional under the Fed calendar caveat.', f'Published coverage ends {max(e.start.date() for e in events)}; later dates are not inferred.'])]
