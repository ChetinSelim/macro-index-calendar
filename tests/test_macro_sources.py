"""Focused official-source parsing, identity, DST, and degraded-fetch checks."""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from src.sources import fomc, boe, bls, bea

FIXTURES = Path(__file__).resolve().parents[1] / 'data' / 'macro-fixtures'
TODAY, HORIZON = date(2026, 11, 2), date(2028, 5, 2)


def fixture(name):
    return (FIXTURES / name).read_text()


def test_fomc_official_rows_last_meeting_day_and_prose_next_year():
    events = fomc.parse(fixture('fomc.html'))
    upcoming = [e for e in events if TODAY <= e.start.date() <= HORIZON]
    assert len(upcoming) == 10
    assert upcoming[0].start.isoformat() == '2026-12-09T14:00:00-05:00'
    assert upcoming[-1].key == 'fomc:2028:meeting-1'
    assert upcoming[-1].start.date() == date(2028, 1, 26)
    assert all(e.certainty == 'provisional' for e in upcoming)
    march = next(e for e in upcoming if e.start.date() == date(2027, 3, 17))
    assert march.start.astimezone(timezone.utc).hour == 18
    moved = fomc.parse(fixture('fomc.html').replace('26-27</div>', '25-26</div>', 1))
    assert [e.key for e in moved] == [e.key for e in events]


def test_fomc_cross_month_meeting_and_unknown_layout_fail():
    html = '<div class="panel"><h4>2028 FOMC Meetings</h4><div class="fomc-meeting"><div class="fomc-meeting__month">Jan/Feb</div><div class="fomc-meeting__date">31-1*</div></div></div>'
    assert fomc.parse(html)[0].start.date() == date(2028, 2, 1)
    with pytest.raises(ValueError):
        fomc.parse('<p>Access denied</p>')


def test_boe_official_dates_and_london_dst():
    events = boe.parse(fixture('boe.html'))
    upcoming = [e for e in events if TODAY <= e.start.date() <= HORIZON]
    assert len(upcoming) == 10
    assert upcoming[0].start.isoformat() == '2026-11-05T12:00:00+00:00'
    april = next(e for e in upcoming if e.start.date() == date(2027, 4, 29))
    assert april.start.astimezone(timezone.utc).hour == 11
    assert all(e.certainty == 'confirmed' for e in events)
    moved = boe.parse(fixture('boe.html').replace('5 November', '6 November'))
    assert [e.key for e in moved] == [e.key for e in events]


def test_boe_missing_date_rejected():
    with pytest.raises(ValueError):
        boe.parse('<h2>2027 confirmed dates</h2><table></table>')


def test_bea_official_feed_agrees_with_html_and_coverage():
    feed = {e.key: e for e in bea.parse_ics((FIXTURES / 'bea.ics').read_bytes()) if TODAY <= e.start.date() <= HORIZON}
    html = {e.key: e for e in bea.parse_html(fixture('bea.html')) + bea.parse_html(fixture('bea-next.html'))}
    assert len(feed) == 14
    assert feed.keys() == html.keys()
    assert all(feed[k].start == html[k].start for k in feed)
    assert feed['pce:2026-10'].start.isoformat() == '2026-11-25T08:30:00-05:00'
    assert feed['pce:2027-02'].start.isoformat() == '2027-03-31T08:30:00-04:00'
    assert max(e.start.date() for e in feed.values()) == date(2027, 12, 22)
    assert any(e.key == 'pce:2025-10+2025-11' for e in bea.parse_ics((FIXTURES / 'bea.ics').read_bytes()))


def test_bea_ics_failure_uses_fresh_html(monkeypatch):
    def fake_get(url):
        if url == bea.ICS_URL:
            raise OSError('test failure')
        return SimpleNamespace(text=fixture('bea-next.html' if url == bea.NEXT_URL else 'bea.html'))
    monkeypatch.setattr(bea, 'get', fake_get)
    result, = bea.fetch(TODAY, HORIZON)
    assert result.status == 'ok'
    assert len(result.events) == 14
    assert 'fresh official HTML' in result.notes[0]


def test_bls_html_reporting_period_identity_survives_reschedule():
    html = '<table><tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr><tr><td>October 2026</td><td>Nov. 06, 2026</td><td>08:30 AM</td></tr></table>'
    event, = bls.parse_html(html, 'nfp')
    moved, = bls.parse_html(html.replace('06,', '09,'), 'nfp')
    assert event.key == moved.key == 'nfp:2026-10'
    assert event.start.isoformat() == '2026-11-06T08:30:00-05:00'
    assert event.start != moved.start


def test_bls_ics_uses_reporting_month_not_uid_or_release_date():
    ics = '''BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:date-based-uid
SUMMARY:Employment Situation
DESCRIPTION:Employment Situation for October 2026
DTSTART:20261106T133000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Consumer Price Index for October 2026
DTSTART:20261110T083000
END:VEVENT
END:VCALENDAR'''
    events = bls.parse_ics(ics)
    assert events['nfp'][0].key == 'nfp:2026-10'
    assert events['cpi'][0].start.isoformat() == '2026-11-10T08:30:00-05:00'
    assert events['cpi'][0].key == 'cpi:2026-10'
    with pytest.raises(ValueError):
        bls.parse_ics(ics.replace('for October 2026', 'no reporting month'))


def test_bls_blocked_live_preserves_review_stamp_and_expires(monkeypatch):
    def blocked(_):
        raise OSError('403 forbidden fixture')
    monkeypatch.setattr(bls, 'get', blocked)
    results = bls.fetch(TODAY, HORIZON)
    assert [r.category for r in results] == ['nfp', 'cpi']
    for result in results:
        assert result.status == 'partial'
        assert result.verified_at == '2026-11-02T18:32:34Z'
        assert len(result.events) == 14
        assert any('NOT freshly network verified' in n for n in result.notes)
    assert all(r.status == 'unavailable' and not r.events for r in bls.fetch(date(2027, 3, 1), HORIZON))


def test_bls_feed_failure_still_allows_independent_html_categories(monkeypatch):
    def fake_get(url):
        if url != bls.URLS['cpi']:
            raise OSError('403 fixture')
        return SimpleNamespace(text='<table><tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr></table>')
    monkeypatch.setattr(bls, 'get', fake_get)
    nfp, cpi = bls.fetch(TODAY, HORIZON)
    assert nfp.status == 'partial'
    assert cpi.status == 'ok'
    assert cpi.verified_at is None
