"""RFC 5545 serialization with London wall times and explicit transition rules."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event as ICalEvent, Alarm, Timezone
from src.models import LABELS

LONDON = ZoneInfo('Europe/London')

def build_calendar(records: list[dict], generated_at: datetime) -> bytes:
    cal = Calendar()
    cal.add('prodid', '-//Macro and Index Events//Public Schedule//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', 'Macro & Index Events')
    cal.add('x-wr-timezone', 'Europe/London')
    cal.add('x-published-ttl', 'PT12H')
    cal.add('refresh-interval', timedelta(hours=12), parameters={'VALUE': 'DURATION'})
    years = [int(r['start'][:4]) for r in records]
    cal.add_component(Timezone.from_tzinfo(LONDON, first_date=date(min(years)-1, 1, 1), last_date=date(max(years)+2, 1, 1)))
    for r in sorted(records, key=lambda r: (r['start'], r['uid'])):
        item = ICalEvent()
        item.add('uid', r['uid'])
        # A stable DTSTAMP avoids clients treating unchanged events as new.
        item.add('dtstamp', datetime.fromisoformat(r['modified']))
        item.add('created', datetime.fromisoformat(r['created']))
        item.add('last-modified', datetime.fromisoformat(r['modified']))
        item.add('sequence', r['sequence'])
        start = date.fromisoformat(r['start']) if r['all_day'] else datetime.fromisoformat(r['start']).astimezone(LONDON)
        item.add('dtstart', start)
        item.add('dtend', start + (timedelta(days=1) if r['all_day'] else timedelta(minutes=15)))
        prefix = '' if r['certainty'] == 'confirmed' else f"[{r['certainty'].upper()}] "
        item.add('summary', prefix + r['title'])
        item.add('description', f"{r['description']}\n\nDate status: {r['certainty']}.\nPhase: {r['phase']}.\nSource: {r['source_url']}\n" + ('All-day: no exact official publication time is represented.' if r['all_day'] else 'Times displayed in Europe/London; converted with UK and source-zone daylight-saving rules.') + ('\nRetained from the last verified schedule; live source did not reconfirm this event.' if r.get('retained') else ''))
        item.add('categories', [LABELS[r['category']]])
        item.add('url', r['source_url'])
        item.add('status', 'CONFIRMED' if r['certainty'] == 'confirmed' else 'TENTATIVE')
        item.add('transp', 'TRANSPARENT')
        item.add('x-date-certainty', r['certainty'])
        item.add('x-source-category', r['category'])
        item.add('x-event-phase', r['phase'])
        if r.get('retained'):
            item.add('x-source-retained', 'TRUE')
        alarm = Alarm()
        alarm.add('action', 'DISPLAY')
        alarm.add('description', r['title'])
        alarm.add('trigger', -timedelta(hours=24))
        item.add_component(alarm)
        cal.add_component(item)
    return cal.to_ical()


def validate_ics(raw: bytes, expected_count: int | None = None):
    cal = Calendar.from_ical(raw)
    events = cal.walk('VEVENT')
    if not events or (expected_count is not None and len(events) != expected_count):
        raise ValueError('Calendar is empty or event count changed during serialization')
    uids = set()
    for event in events:
        uid = str(event['uid'])
        if uid in uids:
            raise ValueError(f'Duplicate UID: {uid}')
        uids.add(uid)
        for field in ('summary', 'description', 'dtstart', 'dtend', 'categories', 'url', 'last-modified'):
            if field not in event:
                raise ValueError(f'Missing {field}: {uid}')
        start, end = event.decoded('dtstart'), event.decoded('dtend')
        if end <= start:
            raise ValueError(f'Non-positive duration: {uid}')
        if isinstance(start, datetime):
            if start.tzinfo is None or event['dtstart'].params.get('TZID') != 'Europe/London':
                raise ValueError(f'Timed event lacks London timezone: {uid}')
        if len(event.walk('VALARM')) != 1:
            raise ValueError(f'Alarm missing: {uid}')
    return cal
