# Index and expiry sources

Adapters return semantic review keys, source URLs, certainty and distinct phases. Dates are all-day unless the source supplies an exact aware publication timestamp. “After close” is described rather than assigning an invented common clock time.

## MSCI

[Official review CSV](https://www.msci.com/eqb/pressreleases/archive/ir_dates.csv), linked by the [official review page](https://www.msci.com/eqb/fm/index_review.html), is the primary structured source. Its August 12, 2026 edition lists eight upcoming reviews through August 2028. The unusual CSV wraps pipe-delimited records in the first CSV cell and uses US month-day-year numeric dates. Announcement and effective dates are confirmed; the publisher reserves the right to change them.

A separate calculated implementation-window marker uses the previous weekday before the effective date. This is explicitly indicative: a global index has multiple local market closes and local holiday treatments. The effective date is not the announcement date, and the implementation window is not an official exact implementation date. For the November 2026 review, MSCI’s [October 15 official notice](https://app2.msci.com/webapp/index_ann/DocGet?amp=&format=html&lang=en&pub_key=aq0wbkjxPgo%3D) confirms implementation at the November 30 close, consistent with the CSV’s December 1 effective date. Future windows must be checked against the eventual review announcement.

A missing, blocked or unrecognisable CSV returns unavailable and no invented replacement dates. Core persistence retains the last good events.

## S&P 500

[US index methodology](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf), July 2026, distinguishes discretionary, as-needed composition changes from recurring maintenance. [Equity Indices Policies & Practices](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-equity-indices-policies-practices.pdf), August 2026, pages 15–16, gives quarterly share/IWF maintenance rules.

The adapter calculates quarterly maintenance after-close markers for the third Friday in March, June, September and December, with the preceding XNYS session when closed, plus the next trading-session effective marker. These are labelled calculated and require notice confirmation, especially around holidays. It does not manufacture a fixed membership announcement schedule or apply equal-weight index rules to the headline S&P 500.

[Official RSS discovery](https://www.spglobal.com/spdji/en/rss/) links an [index-announcement RSS feed](https://www.spglobal.com/spdji/en/rss/rss-details/?rssFeedName=index-news-announcements). The adapter tries that feed, accepts only membership stories naming S&P 500 in their title, and requires one unambiguous explicit effective date. Stable identities derive from the notice GUID/URL, not its scheduled effective date. Multiple-date notices and other titles require manual review. A supplied RSS publication time remains timezone-aware.

On the recorded live run the methodology and RSS returned HTTP 403 to ordinary requests. The official PDFs were inspectable through web browsing, so maintenance uses a reviewed rule dated November 2, 2026 and reports degraded fallback. No block bypass was attempted. Ad hoc membership announcements are currently unverified. Future calculations repeat the reviewed rule until a subsequent refresh or code review changes it; they are not new provider confirmations.

## Russell US

[Official reconstitution hub](https://www.lseg.com/en/ftse-russell/russell-reconstitution) supplies the current cycle calendar and a structured JSON-LD FAQ. [Ground Rules](https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/russell-us-indexes-construction-and-methodology.pdf), v7.2 August 2026, Appendix F, supplies calculation rules.

The 2026 transition is June **and December**, superseding the [January 2025 release](https://www.lseg.com/en/media-centre/press-releases/ftse-russell/2025/russell-us-indexes-move-to-semi-annual-reconstitution) that initially proposed November. Rank day is the last business day of April/October; first preliminary information is five/four weeks before implementation; implementation is after the fourth Friday close in June/second Friday close in December. Calculated effective-session markers use the next XNYS trading session. Projected phases stay calculated until explicitly announced.

For December 2026 the live hub explicitly confirms rank October 30, preliminary lists November 13, updates November 20/27 and December 4/11, and implementation after the December 11 US close. Weekly update markers are created only from explicit current-cycle statements, not projected indefinitely. IPO quarterly additions and other daily corporate actions are outside this calendar’s reconstitution coverage.

## US monthly options / quarterly concentration

[OIC options basics](https://www.optionseducation.org/optionsoverview/options-basics) states the standard third-Friday equity-option convention and holiday adjustment. [Cboe holidays](https://www.cboe.com/about/hours/us-options) supplies full-day options closures; early closes remain trading sessions. The [OIC expiration calendar](https://www.optionseducation.org/referencelibrary/expiration-calendar) explains product-specific series and settlement differences.

Every marker is calculated: standard monthly convention adjusted to the prior XNYS session and live Cboe closures when available. March/June/September/December are labelled quarterly expiry concentration / triple witching (sometimes historically “quad witching”). These markers do not assert all contracts settle together. AM/PM index settlement, last trading times, exercise deadlines, VIX, daily/weekly options and end-of-quarter option series differ and are outside scope.

Good Friday is handled by the exchange calendar. Important checked cases: April 18, 2025 moves to April 17; June 19, 2026 moves to June 18; June 18, 2027 (Juneteenth observed) moves to June 17. March 19, 2027 does not move because Good Friday is March 26. Cboe currently supplies 2026/2027 full-year tables; 2028 uses XNYS calculations with an explicit coverage limitation. Unscheduled closures or provider changes can still change future dates.

## Verification

`tests/test_index_sources.py` covers real CSV shape, rescheduling identities, phase separation, blocked and changed sources, Russell’s semiannual transition, explicit list updates, holiday handling and conservative RSS parsing. Four adapters were also fetched live for November 2, 2026–May 2, 2028; exact observed counts, timestamps, URLs and limitations are recorded in `data/index-live-verification.json`.

The installed exchange-calendars/pandas combination raises `DateOutOfBounds` for valid inputs to `is_session`; helpers use membership in Python dates from the exchange’s session index, which preserves calendar holidays while avoiding timestamp-resolution mismatch.
