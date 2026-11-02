"""Quarterly maintenance markers; membership changes have no predictable schedule."""
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from io import BytesIO

from pypdf import PdfReader

from src.models import Event, SourceResult
from src.sources.http import get
from src.sources.options import nth_friday, previous_session, next_session

URL = 'https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-equity-indices-policies-practices.pdf'
US_URL = 'https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf'
NEWS_URL = 'https://www.spglobal.com/spdji/en/index-announcements/'
RSS_URL = 'https://www.spglobal.com/spdji/en/rss/rss-details/?rssFeedName=index-news-announcements'
REVIEWED_AT = '2026-11-02T18:35:00+00:00'


def calculate(today: date, horizon: date) -> list[Event]:
    events = []
    for year in range(today.year, horizon.year + 1):
        for month in (3, 6, 9, 12):
            nominal = nth_friday(year, month)
            implementation = previous_session(nominal)
            effective = next_session(implementation)
            period = f'{year}-Q{month//3}'
            explanation = (
                'Calculated quarterly share/IWF maintenance window, based on the S&P DJI '
                'Equity Indices Policies & Practices quarterly rule (third Friday of the '
                'third month of the quarter), with a preceding XNYS session used when closed. '
                f'Nominal rule date: {nominal}; implementation after close: {implementation}; '
                f'next trading session: {effective}. Dates require confirmation against provider '
                'notices, especially holiday adjustments. This is not an S&P 500 membership '
                'reconstitution or a forecast addition/deletion announcement. Membership changes '
                'are committee decisions on an as-needed basis and can occur between quarters. '
            )
            for phase, day, label in (
                ('implementation', implementation, 'quarterly maintenance — after close'),
                ('effective', effective, 'quarterly maintenance — effective session'),
            ):
                if today <= day <= horizon:
                    events.append(Event(f'sp500:{period}:maintenance:{phase}', 'sp500',
                                        f'S&P 500 {label} (calculated)', day, URL,
                                        explanation, 'calculated', phase))
    return events


def parse_announcements(xml: str, today: date, horizon: date) -> list[Event]:
    """Only explicit S&P 500 membership stories with a unique effective date.

    The RSS source may block automated access; failures are reported as degraded.
    We deliberately skip ambiguous multi-date announcements for manual review.
    """
    root = ET.fromstring(xml)
    if root.tag not in ('rss', 'feed'):
        raise ValueError('S&P announcement feed is not RSS/Atom')
    events = []
    for item in root.findall('.//item'):
        title = item.findtext('title') or ''
        if not (re.search(r'S&P\s*500\b', title, re.I)
                and re.search(r'join|replace|additions|deletions|changes', title, re.I)):
            continue
        link = item.findtext('link') or ''
        if urlparse(link).hostname != 'www.spglobal.com':
            continue
        body = BeautifulSoup(item.findtext('description') or '', 'html.parser').get_text(' ', strip=True)
        if 'effective' not in body.lower():
            response = get(link)
            if response.content.startswith(b'%PDF'):
                body = ' '.join(p.extract_text() or '' for p in PdfReader(BytesIO(response.content)).pages)
            else:
                body = BeautifulSoup(response.text, 'html.parser').get_text(' ', strip=True)
        body = ' '.join(body.split())
        values = re.findall(
            r'effective\s+(?:prior to|before)\s+the\s+(?:market\s+)?open(?:\s+of\s+trading)?\s+on\s+'
            r'(?:[A-Za-z]+,?\s+)?([A-Za-z]+\s+\d{1,2},\s+20\d{2})', body, re.I)
        dates = {datetime.strptime(v, '%B %d, %Y').date() for v in values}
        if len(dates) != 1:
            continue
        effective = dates.pop()
        identity = item.findtext('guid') or link
        key = 'sp500:membership:' + hashlib.sha256(identity.encode()).hexdigest()[:20]
        if today <= effective <= horizon:
            events.append(Event(key + ':effective', 'sp500', title + ' — effective', effective,
                                link, 'Explicit membership effective date in the official S&P DJI announcement. '
                                'Effective prior to US market open; all-day marker. This is separate from '
                                'the recurring quarterly share/IWF maintenance window.', 'confirmed', 'effective'))
        published = item.findtext('pubDate')
        if published:
            publication = parsedate_to_datetime(published)
            if publication.tzinfo is not None and today <= publication.date() <= horizon:
                events.append(Event(key + ':announcement', 'sp500', title + ' — announcement',
                                    publication, link, 'Publication timestamp from the official RSS item. '
                                    f'Membership effective date: {effective}.', 'confirmed', 'announcement'))
    return events


def fetch(today: date, horizon: date) -> list[SourceResult]:
    notes = [
        'Quarterly share/IWF maintenance dates are calculated. S&P 500 membership '
        'additions/deletions have no scheduled reconstitution and no future announcement dates are invented.',
        'Ad hoc membership coverage is limited to accessible RSS stories naming S&P 500 in the title '
        'and giving one unambiguous explicit effective date; other notices require manual review.',
        'Future maintenance dates repeat the current or reviewed rule until refreshed; provider changes and holiday notices can supersede them.',
    ]
    verified = None
    try:
        response = get(URL)
        reader = PdfReader(BytesIO(response.content))
        # Current rule occurs near the beginning; avoid extracting appendices/history.
        text = ' '.join(p.extract_text() or '' for p in reader.pages[:20])
        text = ' '.join(text.split()).lower()
        if 'third friday' not in text or 'quarterly implementation' not in text:
            raise ValueError('Official maintenance rule missing or changed')
        verified = datetime.now(timezone.utc).isoformat()
        notes.append('Official maintenance methodology retrieved; event dates remain calculated.')
    except Exception as exc:
        verified = REVIEWED_AT
        notes.append(f'Live S&P methodology unavailable ({type(exc).__name__}: {exc}). '
                     f'Using the rule reviewed via official PDF on {REVIEWED_AT}; degraded fallback, not a fresh schedule.')
    events = calculate(today, horizon)
    try:
        announced = parse_announcements(get(RSS_URL).text, today, horizon)
        events.extend(announced)
        notes.append(f'Official RSS parsed: {len(announced)} in-window membership phases.')
    except Exception as exc:
        notes.append(f'Live membership RSS unavailable ({type(exc).__name__}: {exc}); '
                     'ad hoc membership announcements are not currently verified.')
    return [SourceResult('sp500', events, [URL, US_URL, NEWS_URL, RSS_URL],
                         notes, 'partial', verified_at=verified)]
