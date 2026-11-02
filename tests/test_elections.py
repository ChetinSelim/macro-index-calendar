from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from src.sources import elections
from src.models import CATEGORIES, Event, SourceResult
from src.state import reconcile, IntegrityError
from src.calendar import build_calendar, validate_ics

PRESIDENT = '<p>Every four years, voters participate. Election Day is the first Tuesday after the first Monday in November.</p>'
MIDTERM = '<p>Congressional elections happen every two years.</p>'
FEC = '<p>Tuesday, <strong>November 3, 2026</strong>, is the next regularly scheduled federal General Election date.</p>'
TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 22, tzinfo=timezone.utc)
HORIZON = date(2028, 5, 2)
EXTENDED = date(2030, 11, 2)

@pytest.mark.parametrize('year,expected', [(2022,'2022-11-08'),(2024,'2024-11-05'),(2026,'2026-11-03'),(2028,'2028-11-07'),(2030,'2030-11-05')])
def test_election_day_rule(year, expected):
    assert elections.election_day(year)==date.fromisoformat(expected)
    with pytest.raises(ValueError):
        elections.election_day(year+1)

def fake_get(url):
    return SimpleNamespace(text={elections.PRESIDENT_URL:PRESIDENT, elections.MIDTERM_URL:MIDTERM, elections.FEC_URL:FEC}[url])

def all_results(result):
    macro=Event('test-2027','fomc','FOMC test decision',date(2027,1,27),'https://www.federalreserve.gov/','Verified macro event to check migration preserves its identity.')
    return [result if c=='elections' else SourceResult(c,[macro] if c=='fomc' else []) for c in CATEGORIES]

def test_live_dates_and_presidential_extended_horizon(monkeypatch):
    monkeypatch.setattr(elections,'get',fake_get)
    result=elections.fetch(TODAY,EXTENDED)[0]
    assert result.status=='ok'
    assert [(e.start,e.certainty) for e in result.events]==[(date(2026,11,3),'confirmed'),(date(2028,11,7),'calculated')]
    assert 'Midterm' in result.events[0].title
    assert 'Presidential' in result.events[1].title
    state=reconcile(all_results(result),None,NOW,HORIZON,category_horizons={'elections':EXTENDED})
    assert len(state['events'])==3
    cal=validate_ics(build_calendar(state['events'],NOW),3)
    rows=[e for e in cal.walk('VEVENT') if str(e['x-source-category'])=='elections']
    assert {e.decoded('dtstart') for e in rows}=={date(2026,11,3),date(2028,11,7)}
    assert all(type(e.decoded('dtstart')) is date for e in rows)
    assert all(e.decoded('dtend')==e.decoded('dtstart')+timedelta(days=1) for e in rows)
    assert all(e.walk('VALARM')[0].decoded('trigger')==-timedelta(hours=24) for e in rows)
    assert state['horizon']==HORIZON.isoformat()
    assert state['category_horizons']['elections']==EXTENDED.isoformat()
    failed=SourceResult('elections',status='unavailable',notes=['Temporary outage'])
    retained=reconcile(all_results(failed),state,NOW+timedelta(hours=1),HORIZON,category_horizons={'elections':EXTENDED})
    assert {e['uid'] for e in retained['events']}=={e['uid'] for e in state['events']}
    assert retained['health']['elections']['retained']==2

def test_missing_sources_use_dated_fallback(monkeypatch):
    monkeypatch.setattr(elections,'get',lambda _: (_ for _ in ()).throw(RuntimeError('offline')))
    result=elections.fetch(TODAY,EXTENDED)[0]
    assert result.status=='partial'
    assert result.verified_at==elections.REVIEWED_AT
    assert len(result.events)==2
    assert 'reviewed' in result.events[0].description

def test_fec_disagreement_fails_publication(monkeypatch):
    def wrong(url):
        return SimpleNamespace(text=FEC.replace('November 3','November 4')) if url==elections.FEC_URL else fake_get(url)
    monkeypatch.setattr(elections,'get',wrong)
    with pytest.raises(IntegrityError,match='differs'):
        elections.fetch(TODAY,EXTENDED)

def test_elections_roll_forward_and_stable_identity(monkeypatch):
    monkeypatch.setattr(elections,'get',fake_get)
    initial=elections.fetch(TODAY,EXTENDED)[0].events
    later=elections.fetch(date(2026,11,4),date(2030,11,4))[0].events
    assert len(later)==1
    assert later[0].key==initial[1].key
    future=elections.fetch(date(2026,11,6),date(2030,11,6))[0].events
    assert [e.start for e in future]==[date(2028,11,7),date(2030,11,5)]
