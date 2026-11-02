"""Index adapters fail closed and retain review identities when dates move."""
from datetime import date, datetime
import json

import pytest

from src.sources import msci, options, russell, sp500

MSCI = '''MSCI Announces the Next Eight Index Review Dates,,,,
#BOD,,,,
Quarter|Event|Announcement Date|Effective Date,,,,
"Nov, 2026|""Index Review""|11-11-2026|12-01-2026",,,,
"Feb, 2027|""Index Review""|02-09-2027|03-01-2027",,,,
#EOD,,,,
'''


def russell_fixture():
    faq = 'A: Preliminary lists for the upcoming December 2026 Reconstitution will be communicated beginning November 13, with updates on November 20, November 27, December 4, and December 11. The newly reconstituted indexes take effect after the market close on December 11, 2026.'
    return '<h3>December 2026 Russell Reconstitution Calendar</h3><p>In 2026, the rank day falls on Friday, October 30.</p><script type="application/ld+json">' + json.dumps({'mainEntity': [{'name': 'Q: When are the reconstitutions this year?', 'acceptedAnswer': {'text': faq}}]}) + '</script>'


def test_msci_live_csv_shape_three_distinct_phases():
    events = msci.parse_csv(MSCI)
    assert len(events) == 6
    cycle = {e.phase: e for e in events if ':2026-11:' in e.key}
    assert cycle['announcement'].start == date(2026, 11, 11)
    assert cycle['implementation'].start == date(2026, 11, 30)
    assert cycle['effective'].start == date(2026, 12, 1)
    assert cycle['implementation'].certainty == 'calculated'
    assert cycle['effective'].certainty == 'confirmed'
    assert not isinstance(cycle['effective'].start, datetime)


def test_msci_rescheduled_release_keeps_same_keys():
    before = msci.parse_csv(MSCI)
    after = msci.parse_csv(MSCI.replace('11-11-2026', '11-12-2026'))
    assert [e.key for e in before] == [e.key for e in after]
    assert before[0].start != after[0].start


def test_msci_changed_csv_and_blocked_source_fail_closed(monkeypatch):
    with pytest.raises(ValueError):
        msci.parse_csv('<html>access denied</html>')
    monkeypatch.setattr(msci, 'get', lambda _: (_ for _ in ()).throw(RuntimeError('403 blocked')))
    result = msci.fetch(date(2026, 11, 2), date(2028, 5, 2))[0]
    assert result.status == 'unavailable'
    assert result.events == []


@pytest.mark.parametrize(('nominal', 'expected'), [
    (date(2025, 4, 18), date(2025, 4, 17)),  # Good Friday
    (date(2026, 6, 19), date(2026, 6, 18)),  # Juneteenth
    (date(2027, 6, 18), date(2027, 6, 17)),  # Juneteenth observed
    (date(2027, 3, 19), date(2027, 3, 19)),  # Good Friday is the following week
])
def test_standard_expiry_holiday_adjustments(nominal, expected):
    assert options.previous_session(nominal) == expected


def test_options_month_identity_and_no_common_settlement_claim():
    events = options.calculate(date(2027, 6, 1), date(2027, 6, 30))
    assert len(events) == 1
    event = events[0]
    assert event.key == 'options:2027-06:monthly'
    assert event.start == date(2027, 6, 17)
    assert 'triple witching' in event.title
    assert 'AM/PM' in event.description and 'does not assert' in event.description
    assert event.certainty == 'calculated'


def test_options_cboe_closures_exclude_early_close():
    rows = ''.join(f'<tr><td>Holiday</td><td>January {d}</td><td>None</td></tr>' for d in range(1, 9))
    html = '<h3>2027 Options Holiday Schedule</h3><table>' + rows + '<tr><td>Early</td><td>November 26</td><td>09:30:00 - 13:00:00</td></tr></table>'
    closures, years = options.parse_closures(html)
    assert years == {2027}
    assert date(2027, 11, 26) not in closures
    with pytest.raises(ValueError):
        options.parse_closures('<html>blocked</html>')


def test_russell_announced_december_transition_and_update_phases():
    events = russell.parse_announced(russell_fixture())
    assert len(events) == 7
    assert events[0].start == date(2026, 11, 13)
    assert events[-1].start == date(2026, 10, 30)
    close = next(e for e in events if e.phase == 'implementation')
    assert close.start == date(2026, 12, 11)
    assert close.certainty == 'confirmed'
    assert not any(e.phase == 'effective' for e in events)


def test_russell_future_rules_include_rank_and_both_reconstitutions():
    events = russell.calculate(date(2027, 1, 1), date(2027, 12, 31))
    mapping = {e.key: e.start for e in events}
    assert mapping['russell:2027-06:rank'] == date(2027, 4, 30)
    assert mapping['russell:2027-06:preliminary'] == date(2027, 5, 21)
    assert mapping['russell:2027-06:implementation'] == date(2027, 6, 25)
    assert mapping['russell:2027-12:implementation'] == date(2027, 12, 10)
    assert mapping['russell:2027-12:effective'] == date(2027, 12, 13)
    assert all(e.certainty == 'calculated' for e in events)


def test_sp_quarterly_maintenance_is_not_membership_announcement():
    events = sp500.calculate(date(2027, 6, 1), date(2027, 6, 30))
    assert [(e.phase, e.start) for e in events] == [
        ('implementation', date(2027, 6, 17)), ('effective', date(2027, 6, 21))]
    assert all(e.certainty == 'calculated' and 'not an S&P 500 membership' in e.description for e in events)


def test_sp_membership_rss_explicit_date_and_aware_publication():
    xml = '''<rss><channel><item><title>Example Set to Join S&amp;P 500</title>
    <link>https://www.spglobal.com/spdji/en/documents/indexnews/example.pdf</link>
    <guid>logical-notice-id</guid><pubDate>Mon, 02 Nov 2026 17:15:00 -0500</pubDate>
    <description>Example joins effective prior to the open of trading on Monday, November 9, 2026.</description>
    </item></channel></rss>'''
    events = sp500.parse_announcements(xml, date(2026, 11, 1), date(2026, 12, 1))
    assert len(events) == 2
    assert events[0].start == date(2026, 11, 9)
    assert events[1].start.tzinfo is not None
    after = sp500.parse_announcements(xml.replace('November 9', 'November 10'), date(2026, 11, 1), date(2026, 12, 1))
    assert [e.key for e in events] == [e.key for e in after]
    ambiguous = xml.replace('Example joins effective', 'Effective prior to the open of trading on November 12, 2026. Example joins effective')
    assert not sp500.parse_announcements(ambiguous, date(2026, 11, 1), date(2026, 12, 1))


def test_sp_blocked_fallback_remains_degraded(monkeypatch):
    monkeypatch.setattr(sp500, 'get', lambda _: (_ for _ in ()).throw(RuntimeError('403')))
    result = sp500.fetch(date(2026, 11, 2), date(2028, 5, 2))[0]
    assert result.status == 'partial'
    assert result.verified_at == sp500.REVIEWED_AT
    assert len(result.events) == 12
    assert any('not currently verified' in n for n in result.notes)
