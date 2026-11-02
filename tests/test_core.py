from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import pytest
from src.models import CATEGORIES, Event, SourceResult
from src.state import reconcile, IntegrityError
from src.calendar import build_calendar, validate_ics
from src.main import publish, load_previous

NOW = datetime(2026,11,2,18,tzinfo=timezone.utc)
HORIZON = date(2028,5,2)

def event(category='fomc', start=None, key='2027-03'):
    return Event(key, category, 'US | Test Announcement', start or datetime(2027,3,17,14,tzinfo=ZoneInfo('America/New_York')), 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm', 'Official scheduled release, with documented publication time.')

def results(events=None):
    events = [event()] if events is None else events
    return [SourceResult(c,[e for e in events if e.category==c],notes=['No future schedule published'] if not any(e.category==c for e in events) else []) for c in CATEGORIES]

@pytest.mark.parametrize('day,hour', [('2027-03-19',13),('2027-03-29',14),('2027-03-05',14),('2027-11-03',13),('2027-11-08',14)])
def test_us_uk_dst_mismatch(day,hour):
    # 08:30 Eastern: 13:30 normally, 12:30 during mismatch (test 09:30 instead).
    start = datetime.combine(date.fromisoformat(day),datetime.min.time()).replace(hour=9,minute=30,tzinfo=ZoneInfo('America/New_York'))
    state = reconcile(results([event(start=start)]),None,NOW,HORIZON)
    cal = validate_ics(build_calendar(state['events'],NOW),1)
    value = cal.walk('VEVENT')[0].decoded('dtstart')
    assert value.hour == hour
    assert value.minute == 30

@pytest.mark.parametrize('day,offset', [('2027-03-27',0),('2027-03-28',1),('2027-10-30',1),('2027-10-31',0)])
def test_london_dst_boundaries(day,offset):
    start = datetime.fromisoformat(day+'T12:00').replace(tzinfo=ZoneInfo('Europe/London'))
    state = reconcile(results([event(start=start)]),None,NOW,HORIZON)
    cal = validate_ics(build_calendar(state['events'],NOW),1)
    assert cal.walk('VEVENT')[0].decoded('dtstart').utcoffset()==timedelta(hours=offset)

def test_uid_stable_on_reschedule_and_sequence_changed():
    a = reconcile(results(),None,NOW,HORIZON)
    b = reconcile(results([event(start=datetime(2027,3,18,14,tzinfo=ZoneInfo('America/New_York')))]),a,NOW+timedelta(days=1),HORIZON)
    assert a['events'][0]['uid']==b['events'][0]['uid']
    assert b['events'][0]['sequence']==1
    assert b['changes'][0]['before'] != b['changes'][0]['after']
    c = reconcile(results([event(start=datetime(2027,3,18,14,tzinfo=ZoneInfo('America/New_York')))]),b,NOW+timedelta(days=2),HORIZON)
    assert c['events'][0]['modified']==b['events'][0]['modified']
    assert c['events'][0]['sequence']==1

def test_outage_preserves_previous_and_does_not_fake_freshness():
    a = reconcile(results(),None,NOW,HORIZON)
    failed = [SourceResult(c,status='unavailable',notes=['HTTP 503']) for c in CATEGORIES]
    b = reconcile(failed,a,NOW+timedelta(days=1),HORIZON)
    assert b['events'][0]['start']==a['events'][0]['start']
    assert b['events'][0]['retained']
    assert b['health']['fomc']['last_success']==NOW.isoformat()
    assert b['health']['fomc']['status']=='partial'

def test_successful_broken_parser_blocks_publication():
    a = reconcile(results(),None,NOW,HORIZON)
    with pytest.raises(IntegrityError,match='lost'):
        reconcile(results([]),a,NOW,HORIZON)

def test_empty_and_missing_categories_rejected():
    with pytest.raises(IntegrityError,match='empty'):
        reconcile(results([]),None,NOW,HORIZON)
    with pytest.raises(IntegrityError,match='category'):
        reconcile(results()[:-1],None,NOW,HORIZON)

def test_duplicate_dedup_and_conflicts():
    state = reconcile(results([event(),event()]),None,NOW,HORIZON)
    assert len(state['events'])==1
    with pytest.raises(IntegrityError,match='Conflicting'):
        reconcile(results([event(),event(start=date(2027,3,18))]),None,NOW,HORIZON)

def test_naive_datetime_rejected():
    with pytest.raises(IntegrityError,match='Naive'):
        reconcile(results([event(start=datetime(2027,3,18,14))]),None,NOW,HORIZON)

def test_all_day_provisional_and_alarm():
    e = event(start=date(2027,3,18)); e.certainty='calculated'
    state = reconcile(results([e]),None,NOW,HORIZON)
    cal = validate_ics(build_calendar(state['events'],NOW),1)
    row = cal.walk('VEVENT')[0]
    assert type(row.decoded('dtstart')) is date
    assert row.decoded('dtend')==date(2027,3,19)
    assert str(row['summary']).startswith('[CALCULATED]')
    assert row.walk('VALARM')[0].decoded('trigger')==-timedelta(hours=24)

def test_atomic_publication_integration(tmp_path):
    state = reconcile(results(),None,NOW,HORIZON)
    output = tmp_path/'site'
    publish(state,output,'https://example.org',NOW)
    validate_ics((output/'calendar.ics').read_bytes(),1)
    assert set(json.loads((output/'health.json').read_text())['categories'])==set(CATEGORIES)
    assert 'From URL' in (output/'index.html').read_text()
    before = (output/'calendar.ics').read_bytes()
    with pytest.raises((ValueError,IntegrityError)):
        publish(dict(state,events=[]),output,'https://example.org',NOW)
    assert (output/'calendar.ics').read_bytes()==before

def test_expired_events_not_retained():
    old = reconcile(results(),None,NOW,HORIZON)
    later = datetime(2027,4,1,tzinfo=timezone.utc)
    state = reconcile(results([event(start=date(2027,5,1),key='2027-05')]),old,later,HORIZON)
    assert len(state['events'])==1
    assert state['events'][0]['start']=='2027-05-01'

def test_old_fallback_cannot_overwrite_newer_verified_correction():
    newer = event(category='nfp', start=datetime(2026,11,9,8,30,tzinfo=ZoneInfo('America/New_York')))
    initial = reconcile(results([newer]),None,NOW+timedelta(days=1),HORIZON)
    fallback = results([event(category='nfp',start=datetime(2026,11,6,8,30,tzinfo=ZoneInfo('America/New_York')))])
    fallback[2].status='partial'
    fallback[2].verified_at=NOW.isoformat()
    updated = reconcile(fallback,initial,NOW+timedelta(days=2),HORIZON)
    assert updated['events'][0]['start']==newer.start.isoformat()
    assert updated['events'][0]['retained']
    assert updated['health']['nfp']['last_success']==(NOW+timedelta(days=1)).isoformat()
    assert updated['health']['nfp']['retained']==1

def test_live_calculation_cannot_replace_prior_confirmed_date():
    official=event(category='russell',start=date(2027,6,24))
    initial=reconcile(results([official]),None,NOW,HORIZON)
    projection=event(category='russell',start=date(2027,6,25)); projection.certainty='calculated'
    fallback=results([projection]); fallback[7].status='partial'; fallback[7].verified_at=(NOW+timedelta(days=1)).isoformat()
    updated=reconcile(fallback,initial,NOW+timedelta(days=1),HORIZON)
    assert updated['events'][0]['start']=='2027-06-24'
    assert updated['events'][0]['certainty']=='confirmed'
    assert updated['events'][0]['retained']
    assert updated['health']['russell']['last_success']==NOW.isoformat()
