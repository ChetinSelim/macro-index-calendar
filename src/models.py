"""Shared adapter contract. Keys identify logical releases, not their scheduled dates."""
from dataclasses import dataclass, field
from datetime import date, datetime

CATEGORIES = ('fomc', 'boe', 'nfp', 'cpi', 'pce', 'msci', 'sp500', 'russell', 'options')
LABELS = dict(zip(CATEGORIES, ('FOMC', 'Bank of England', 'US Non-Farm Payrolls', 'US CPI', 'US PCE', 'MSCI', 'S&P 500', 'Russell', 'Options expiry')))

@dataclass
class Event:
    key: str
    category: str
    title: str
    start: date | datetime
    source_url: str
    description: str
    certainty: str = 'confirmed'  # confirmed, provisional, calculated
    phase: str = 'announcement'

@dataclass
class SourceResult:
    category: str
    events: list[Event] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    status: str = 'ok'  # ok, partial, unavailable
    verified_at: str | None = None  # ISO UTC timestamp for reviewed offline fallback
