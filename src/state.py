"""Reconcile snapshots without deleting future events during source failures."""
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import json
from urllib.parse import urlparse
from src.models import CATEGORIES, Event, SourceResult

class IntegrityError(ValueError):
    pass

def serialize(event: Event) -> dict:
    if event.category not in CATEGORIES or event.certainty not in ('confirmed', 'provisional', 'calculated'):
        raise IntegrityError('Unknown category or date certainty')
    if not event.key.strip() or not event.title.strip() or len(event.description.strip()) < 20:
        raise IntegrityError('Event lacks stable identity, title or useful description')
    if urlparse(event.source_url).scheme != 'https' or not urlparse(event.source_url).netloc:
        raise IntegrityError('Event lacks HTTPS source URL')
    if isinstance(event.start, datetime) and (event.start.tzinfo is None or event.start.utcoffset() is None):
        raise IntegrityError('Naive datetime is forbidden')
    if not isinstance(event.start, date):
        raise IntegrityError('Invalid event date')
    result = asdict(event)
    result['all_day'] = not isinstance(event.start, datetime)
    result['start'] = event.start.isoformat()
    result['uid'] = hashlib.sha256(f'{event.category}:{event.key}'.encode()).hexdigest()[:32] + '@macro-index-calendar'
    return result

def fingerprint(record: dict) -> str:
    return hashlib.sha256(json.dumps({k:v for k,v in record.items() if k not in ('created','modified','sequence','fingerprint','verified_at')}, sort_keys=True).encode()).hexdigest()

def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else datetime.min.replace(tzinfo=timezone.utc)

def reconcile(results: list[SourceResult], previous: dict | None, now: datetime, horizon: date) -> dict:
    today = now.date()
    previous = previous or {}
    old = {r['uid']:r for r in previous.get('events', []) if today <= date.fromisoformat(r['start'][:10]) <= horizon}
    prior_health = previous.get('health', {})
    if len(results) != len(CATEGORIES) or set(r.category for r in results) != set(CATEGORIES):
        raise IntegrityError('Each requested category must return exactly one explicit result')
    records, health, changes = {}, {}, []
    for result in results:
        if result.status not in ('ok', 'partial', 'unavailable'):
            raise IntegrityError(f'Unknown source status {result.status}')
        notes = list(result.notes)
        rows = {}
        for event in result.events:
            if event.category != result.category:
                raise IntegrityError('Adapter returned an event in the wrong category')
            row = serialize(event)
            if not today <= date.fromisoformat(row['start'][:10]) <= horizon:
                continue
            if row['uid'] in rows and rows[row['uid']] != row:
                raise IntegrityError(f"Conflicting duplicate identity {event.key}")
            rows[row['uid']] = row
        # Same category/phase/title/date duplicates with different keys must not become duplicate calendar entries.
        semantic = {}
        for uid, row in list(rows.items()):
            identity = (row['category'], row['phase'], row['title'], row['start'])
            if identity in semantic:
                del rows[uid]
            else:
                semantic[identity] = uid
        prior = {uid:r for uid,r in old.items() if r['category'] == result.category}
        missing = prior.keys() - rows.keys()
        incoming_verified = now.isoformat() if result.status == 'ok' else result.verified_at
        protected = set()
        for uid, row in list(rows.items()):
            old_row = prior.get(uid)
            old_verified = (old_row.get('verified_at') or prior_health.get(result.category, {}).get('last_success')) if old_row else None
            older_fallback = old_row and result.status != 'ok' and timestamp(incoming_verified) < timestamp(old_verified)
            lower_confidence = old_row and result.status != 'ok' and row['certainty'] == 'calculated' and old_row['certainty'] in ('confirmed', 'provisional')
            if older_fallback or lower_confidence:
                rows[uid] = dict(old_row, retained=True)
                protected.add(uid)
            else:
                row['verified_at'] = incoming_verified
        # A successful parser suddenly losing a material portion is treated as a broken parser/source.
        if result.status == 'ok' and prior and len(missing) / len(prior) > .30:
            raise IntegrityError(f'{result.category}: successful source lost {len(missing)}/{len(prior)} future identities; publication blocked')
        for uid in missing:
            rows[uid] = dict(prior[uid], retained=True)
        status = result.status
        if missing or protected:
            status = 'partial'
            notes.append(f'{len(missing | protected)} previously published future events retained; absent, older or lower-confidence source data did not replace them.')
        if not rows:
            status = 'unavailable'
            notes.append('No upcoming events are currently available for this category. No dates have been invented.')
        last_success = prior_health.get(result.category, {}).get('last_success')
        if result.status == 'ok' and result.events:
            last_success = now.isoformat()
        elif result.verified_at and rows.keys() - (missing | protected):
            last_success = max(filter(None, (last_success, result.verified_at)), key=timestamp, default=None)
        for uid, row in rows.items():
            digest = fingerprint(row)
            old_row = old.get(uid)
            changed = old_row is not None and digest != old_row.get('fingerprint')
            row['created'] = old_row['created'] if old_row else now.isoformat()
            row['modified'] = now.isoformat() if changed or not old_row else old_row['modified']
            row['sequence'] = old_row.get('sequence',0) + int(changed) if old_row else 0
            row['fingerprint'] = digest
            if changed:
                changes.append({'uid':uid, 'category':row['category'], 'title':row['title'], 'before':old_row['start'], 'after':row['start'], 'at':now.isoformat()})
            records[uid] = row
        health[result.category] = {'status':status, 'last_attempt':now.isoformat(), 'last_success':last_success, 'count':len(rows), 'through':max((r['start'][:10] for r in rows.values()), default=None), 'certainty':dict(Counter(r['certainty'] for r in rows.values())), 'retained':len(missing | protected), 'notes':list(dict.fromkeys(notes)), 'source_urls':result.source_urls}
    if not records:
        raise IntegrityError('Refusing to publish an empty calendar')
    if old and len(records) < len(old) * .8:
        raise IntegrityError('Material event-count regression')
    return {'schema_version':1, 'generated_at':now.isoformat(), 'horizon':horizon.isoformat(), 'events':list(records.values()), 'health':health, 'changes':(previous.get('changes',[]) + changes)[-500:]}
