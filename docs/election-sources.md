# US federal election days

The calendar includes regular nationwide midterm and presidential/congressional general-election days. Elections have a rolling 48-month lookahead, separately configured from the 18-month macro/index window. The same subscribed ICS URL, stable year-based UID, daily refresh, 24-hour alarm and outage retention apply.

Official sources checked on 2 November 2026:

- [FEC national election information](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/) explicitly identifies **3 November 2026** as the next regularly scheduled federal general-election day. This date has a fixed reviewed fallback if the FEC page cannot be fetched.
- [USAGov presidential general elections](https://www.usa.gov/presidential-general-election) states the four-year cycle and first-Tuesday-after-first-Monday November rule.
- [USAGov midterms and congressional elections](https://www.usa.gov/midterm-elections) describes the two-year congressional cycle and the midterm distinction.

The adapter checks the USAGov rules and attempts to parse the explicit next national date from the FEC daily. The **7 November 2028 presidential election** date is currently calculated from the official rule, and is labelled calculated until an explicit FEC schedule entry confirms it. It is not a forecast of the outcome or a result-announcement time. Subsequent even-year cycles enter the lookahead automatically; presidential years are divisible by four, with intervening midterms.

Polling hours vary by state and locality, so events are all-day markers on the US election date. London viewers may receive results overnight or later. Early voting, primary elections, state/local-only elections, runoffs, special elections, inauguration and certification deadlines are outside this category. It is a national market-events marker, not a jurisdiction-specific voting guide.

If live sources fail, health becomes partial and records the fallback and its original verification date. A disagreement between an explicit FEC date and the current calculation blocks publication for review. Existing confirmed events cannot be replaced by lower-confidence calculated dates. Tests cover the November 1 Tuesday edge case, even-year classification, the extended horizon, all-day ICS representation, fallback status, stable identities and preservation during outages.
