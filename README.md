# Macro & Index Events

A free, ad-free public iCalendar feed of macroeconomic releases and equity-index dates. Python 3.12, GitHub Actions and GitHub Pages; no API keys, database, cookies, analytics or paid infrastructure.

- **Website:** https://chetinselim.github.io/macro-index-calendar/
- **Subscribe:** https://chetinselim.github.io/macro-index-calendar/calendar.ics
- **Freshness:** https://chetinselim.github.io/macro-index-calendar/health.json
- **Automation:** https://github.com/ChetinSelim/macro-index-calendar/actions

## Subscribe in Google Calendar

In Google Calendar on desktop, choose **Other calendars → + → From URL** (also available under Settings → Add calendar → From URL). Paste the subscription URL and select **Add calendar**. [Google's instructions](https://support.google.com/calendar/answer/37100).

Use the URL subscription, not a one-time file import. The server refreshes daily; Google controls how frequently it refetches subscriptions and updates may be delayed. This project cannot force Google's refresh schedule.

Each event includes a `VALARM` 24 hours beforehand. Google Calendar may ignore alarms in subscribed ICS feeds. In Settings, select this calendar, then add a **1 day before** event notification if that control is available. Some read-only subscribed calendars do not offer notification controls. No notification delivery guarantee is made.

## Coverage and meaning

The requested horizon is the next 18 months. The generator only uses published macro dates, and does not extend a short official schedule by guessing. The requested list has **nine categories**, counting NFP and CPI separately.

| Category | Primary format and scope | Fallback / limitation |
|---|---|---|
| FOMC | Federal Reserve meeting-calendar HTML, final meeting day, 14:00 New York | Future dates conservatively provisional under the Fed's caveat; no inferred meetings |
| Bank of England | Official MPC date tables; 12:00 Europe/London | No dates beyond published tables |
| US Non-Farm Payrolls | Official BLS ICS; Employment Situation | Official HTML, then explicitly dated reviewed official schedule if automated access is blocked |
| US CPI | Official BLS ICS; Consumer Price Index | Same independently reported fallback as NFP |
| US PCE | Official BEA ICS; Personal Income and Outlays | Current and next-year official HTML schedules |
| MSCI | Official next-eight-review CSV | Confirmed announcement/effective dates; separate calculated prior-weekday implementation windows, which require local-market confirmation |
| S&P 500 | Official methodology PDFs and announcement RSS | Calculated quarterly shares/IWF maintenance, distinct from discretionary membership changes; RSS availability and narrow parsing limit ad hoc coverage |
| Russell | Official LSEG HTML/JSON-LD and methodology PDF | June **and December** semiannual reconstitution from 2026; rank day, preliminary lists, list updates, implementation and effective sessions; future cycles labelled calculated |
| Options expiry | OCC/OIC standard convention and Cboe holiday HTML | Calculated monthly third-Friday concentration dates, holiday-adjusted; March/June/September/December labelled triple witching (historically also called quad witching) |

See [macro source evidence](docs/macro-sources.md) and [index source evidence](docs/index-sources.md) for exact URLs, parser choices and verified limitations. Every event links its source. The landing page reports **actual upcoming event counts**, last verification, last attempt, published coverage end, date certainty and retained-event count for every category.

**Confirmed** means an official date is published. **Provisional** means a published date is explicitly tentative. **Calculated** means a date derived from a documented rule, not a separately confirmed provider announcement. Provisional and calculated labels appear in event titles as well as descriptions. A source can be healthy while its dates remain provisional.

Index effective dates, close-of-market implementation days, and date-only publication schedules are all-day markers unless an exact publication timestamp is available. Timed macro events convert from the source timezone into `Europe/London`, with a `VTIMEZONE` definition for GMT/BST. US/UK DST mismatch weeks are handled explicitly. Timed entries occupy 15 minutes for display; that duration is not a claim about the duration of a policy meeting or release.

### Coverage limits

- BLS blocked direct automated requests from the initial development environment. The fallback contains dates verified from official HTML, with a fixed review timestamp. It is **not** treated as a new successful fetch every day. After 90 days it stops offering the seed; already published future events remain retained and visibly unverified. If live access remains blocked, refreshing/expanding this category requires a fresh official-source review. The job retries the compliant official ICS and HTML sources daily, without bypassing restrictions.
- S&P 500 does not have a predictable quarterly membership-reconstitution announcement schedule. Quarterly share/IWF maintenance is included as calculated dates. Membership notices are included only when accessible official RSS stories name S&P 500 and provide a single unambiguous effective date; missing/ambiguous notices cannot be represented as comprehensive coverage. The initial direct PDF/RSS requests were blocked, so this category starts degraded.
- MSCI implementation windows are indicative prior weekdays, not a uniform global trading close. Local holidays or index-specific notices can alter treatment.
- Options dates do not describe every contract's last trading time, AM/PM settlement, exercise deadline, daily/weekly expiry, VIX expiry or end-of-quarter series. Quarterly events also cover that month's standard monthly expiry; they are intentionally not duplicated.
- Russell's older November transition announcements are superseded by the current December schedule. Rules and holiday adjustments remain calculated until the specific cycle is announced.
- No scraper can guarantee perpetual unattended operation through access-policy or format changes. Such problems are visible in health and workflow diagnostics; parser maintenance or an official-source review can be required. Existing verified future events are protected.

## Local setup

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pytest -q
python -m src.main
python -m http.server 8000 --directory build
```

If Python 3.12 is unavailable, install it using your usual Python manager; the project was built locally using `uv python install 3.12`. `requirements.txt` specifies direct dependencies and `requirements.lock` pins the complete tested environment. The runtime source code is under `src/`; `data/` contains public test fixtures and explicitly reviewed fallback schedules only.

The first local build has no prior state. Subsequent builds should use:

```sh
python -m src.main --previous build/state.json
# Or reconcile against the currently published snapshot:
python -m src.main --previous-url https://chetinselim.github.io/macro-index-calendar/state.json
```

The output directory contains `calendar.ics`, `index.html`, `health.json`, `changes.json` and `state.json`. These are public schedule data only. No generated publication is committed back to the repository. `state.json` is the durable previous-publication snapshot; it is served with the calendar and retrieved before the next generation. No external database or expiring Actions cache is needed.

## Integrity and outage handling

1. Semantic keys identify the reporting month, review cycle or meeting ordinal, not the scheduled date. A date change keeps the same UID and increments `SEQUENCE` and `LAST-MODIFIED`; unchanged events retain their stamps.
2. Identical duplicates collapse; conflicting events with the same identity fail validation. Timed events must have an aware timezone, descriptions and HTTPS source links.
3. Every requested category must return an explicit health result, including zero-coverage categories. Missing or malformed category results fail.
4. Prior future events are retained during source outages or partial omissions. Older fallback snapshots cannot overwrite newer verified corrections, and calculated projections cannot replace confirmed dates. Retained events are identified in the ICS and health report. Their verification timestamp never advances merely because the generator ran.
5. A source claiming success but losing more than 30% of its previous future identities blocks publication. Empty calendars and material total-count regression also fail. Investigate changed keys/layouts or verified cancellations before changing the baseline; the generator does not silently treat disappearance as cancellation.
6. The complete ICS is round-tripped through the `icalendar` parser before any output is published. After deployment, the public feed is parsed and must match the validated artifact's SHA-256 fingerprint and contain all nine categories. Tests cover release rescheduling, source outage preservation, empty/regressed output, parser fixtures, all-day events, holiday adjustments, UK/US DST boundaries and alarms. The initial publication must contain events in all nine categories.
7. `changes.json` retains the latest 500 event changes. `health.json` distinguishes last verification from the last attempt. GitHub warnings and the job summary expose degraded source coverage.
8. If the prior published state cannot be fetched or fails validation, the production update fails instead of starting from an empty baseline. Failed builds do not deploy; GitHub Pages keeps the previous site. Its visible build timestamp then becomes stale, and the Actions run is red.

Central-bank meeting ordinals assume the institution retains its published regular sequence. An added/deleted regular meeting needs identity review. Unscheduled Fed notation votes are excluded. Combined BEA reporting periods are supported.

## Automation and deployment

`.github/workflows/update.yml` runs daily at **06:23 UTC**, on pushes to `main`, and manually. It installs the lockfile, runs tests, fetches schedules, reconciles the last public state, validates the output, uploads an official Pages artifact and deploys via `actions/deploy-pages`. The build has `contents: read`; the separate deployment job has only `pages: write` and `id-token: write`.

GitHub disables scheduled workflows in public repositories after 60 days without repository activity. A separate monthly keepalive workflow makes an **empty bot commit** on the first day of each month. This requires `contents: write` only in that small workflow. It does not modify or commit generated calendars, and its `GITHUB_TOKEN` push does not recursively trigger workflows. [GitHub schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). Schedules can be delayed by GitHub; they are not real-time delivery.

For a fork: update `config.yaml`, the production state URL in the workflow, and source-code links in `src/site.py` / `src/sources/http.py`. Enable **Settings → Pages → Source: GitHub Actions** and Actions permissions. The initial deployment requires a deliberate `--bootstrap` run for the absent public state (404 only); remove that flag after the first successful deployment. Normal production runs must require the prior state. GitHub-hosted Actions and Pages for a public repository fit this project's free-hosting design; provider terms can change.

To trigger or inspect:

```sh
gh workflow run update.yml
gh run list --workflow update.yml
gh run view RUN_ID --log-failed
```

When a parser fails, reproduce with its official fixture, inspect the current official source, add a regression test for the real format change, and preserve semantic keys. Never update an offline fallback's `verified_at` without actually rechecking the linked official schedule. Publication is public by design; do not add credentials, personal information or private data.
