"""Build a verified static publication; failure never touches the deployed site."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import importlib
import json
import logging
from pathlib import Path
import shutil
import tempfile
import yaml
from dateutil.relativedelta import relativedelta
from src.models import SourceResult
from src.state import reconcile, IntegrityError
from src.calendar import build_calendar, validate_ics
from src.site import render_site
from src.sources.http import get

ADAPTERS = {'fomc':['fomc'], 'boe':['boe'], 'bls':['nfp','cpi'], 'bea':['pce'], 'msci':['msci'], 'sp500':['sp500'], 'russell':['russell'], 'options':['options']}

def fetch_one(name, categories, today, horizon):
    try:
        results = importlib.import_module(f'src.sources.{name}').fetch(today, horizon)
        if set(r.category for r in results) != set(categories):
            raise IntegrityError(f'{name} returned incorrect categories')
        return results
    except IntegrityError:
        raise
    except Exception as error:
        logging.exception('Source failed: %s', name)
        return [SourceResult(c, status='unavailable', notes=[f'Live source failed: {type(error).__name__}: {error}']) for c in categories]

def load_previous(path, url, bootstrap):
    if path:
        return json.loads(Path(path).read_text())
    if url:
        try:
            response = get(url)
        except Exception as error:
            if bootstrap and getattr(getattr(error, 'response', None), 'status_code', None) == 404:
                return None
            raise IntegrityError('Cannot retrieve previous published state; refusing unsafe fresh-start publication') from error
        data = response.json()
        if data.get('schema_version') != 1 or not data.get('events'):
            raise IntegrityError('Invalid previous publication state')
        return data
    return None

def publish(state, output, base_url, now):
    raw = build_calendar(state['events'], now)
    validate_ics(raw, len(state['events']))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.calendar-', dir=output.parent))
    try:
        (staging/'calendar.ics').write_bytes(raw)
        (staging/'state.json').write_text(json.dumps(state, indent=2) + '\n')
        (staging/'health.json').write_text(json.dumps({'generated_at':state['generated_at'], 'horizon':state['horizon'], 'categories':state['health']}, indent=2) + '\n')
        (staging/'changes.json').write_text(json.dumps(state['changes'], indent=2) + '\n')
        (staging/'index.html').write_text(render_site(state, base_url))
        (staging/'.nojekyll').touch()
        if output.exists():
            shutil.rmtree(output)
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='build')
    parser.add_argument('--previous')
    parser.add_argument('--previous-url')
    parser.add_argument('--bootstrap', action='store_true', help='Permit initial 404 for absent publication only')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    config = yaml.safe_load(Path('config.yaml').read_text())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    horizon = now.date() + relativedelta(months=config['horizon_months'])
    previous = load_previous(args.previous, args.previous_url, args.bootstrap)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_one, name, categories, now.date(), horizon) for name,categories in ADAPTERS.items()]
        results = [r for f in futures for r in f.result()]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = reconcile(results, previous, now, horizon)
    if previous is None and any(h['count'] == 0 for h in state['health'].values()):
        raise IntegrityError('Initial publication must contain verified or explicitly labelled fallback events for every category')
    publish(state, args.output, config['base_url'], now)
    for cat,h in state['health'].items():
        logging.info('%s: %s, %d events through %s; verified %s',cat,h['status'],h['count'],h['through'],h['last_success'])
        if h['status'] != 'ok':
            print(f'::warning title={cat} source coverage::{" ".join(h["notes"])}')
    logging.info('Validated %d events. Output: %s', len(state['events']), args.output)

if __name__ == '__main__':
    main()
