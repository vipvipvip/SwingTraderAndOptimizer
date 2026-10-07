# HANDOFF — Commercialization (P20w retail package)

> Companion to `common/docs/commercial/*` — the package itself is committed and on `main`; this doc holds **session decisions & process state**, and points to the canonical numbers instead of duplicating them (so nothing goes stale twice).

**Status:** v0.1 retail package DONE and committed (`2664503`, on `main`). Live P20w running on paper since 2026-09-28 (see AGENTS.md for the strategy side).

## What exists

| File | Role |
|---|---|
| `common/docs/commercial/README.md` | Package index + the six FINRA red-lines + provenance/refresh commands |
| `common/docs/commercial/one_pager.md` | Plain-English mechanism explainer (retail first touch) |
| `common/docs/commercial/performance.md` | Full + 813d tables, span & start-date sweeps, rejected-variants graveyard, live-track plan |
| `common/docs/commercial/regime_matrix.md` | Regime-by-regime behavior with verifiable VTV flip dates/prices, 2022 whipsaw disclosed |
| `common/docs/commercial/faq.md` | 10 objections, zero guarantees |
| `common/docs/commercial/disclosure.md` | Compliance spine: hypothetical method, limitations, no-advice, paper-record status, versioning |

## Decisions made (do not re-litigate)

1. **Format:** markdown in repo first (chosen over PDF/PPTX); polish/PDF/landing-page is a later milestone.
2. **Audience order:** retail/social (friends & family) FIRST → traders (tool/methodology) → investors (pitch). Retail only is built so far.
3. **FINRA bar** = the six red-lines in `commercial/README.md`: fair & balanced; every number labeled hypothetical; no guarantees; no cherry-picking (we publish the sweeps ourselves); **no testimonials/social proof**; tool-with-disclosed-methodology framing, not advice.
4. **Numbers are canonical only if pulled from the shared PHP signal** (never re-implemented): `php artisan trades:coreew-leg-ema-series --span=20` + `python3 backtest_trio_ew.py --leg-ema 20`. As-of 2026-09-28 run; full-period P20w +364.27%/−19.2% DD, 813d +79.26%/−9.4% (verify all figures in `performance.md`, which shows the sweeps).
5. **Any paid distribution must first pass a securities-lawyer review** — disclosure.md already states this to the reader.

## Open threads (next-session queue)

1. **Traders tier** — same mechanism, swapped audience: methodology deep-dive, backtest harness (they'll want the sweep output python-printable), the PHP-canonical parity story as a selling point.
2. **Investors tier** — pitch framing: Calmar/risk-adjusted emphasis, the live paper-track sheet in `performance.md` ("Roll forward metric sheet") once it accumulates.
3. **Render v2:** PDF one-pager / landing page for social, generated from the markdown so numbers stay single-sourced.
4. **Lawyer review** — get on the calendar BEFORE any paid sales channel.
5. **Refresh cadence:** re-run the two commands above when a meaningful new regime row appears or the paper record hits a natural milestone; bump as-of date + red-line re-check every time.

## Quick facts to answer anyone cold

- Universe QQQ/VTI/VTV; rule = per-leg settled weekly close vs its own EMA(20); OFF→cash, ON legs re-balanced to equal thirds (Wednesday action Monday); 0.05%/side; 2–3 small orders/week.
- Historic profile (hypothetical): ~92% of buy-and-hold return at ~59% of its drawdown; cash ~19%; the known failure = sustained chop (2022 whipsaw, printed in the deck).
- Live = Alpaca **paper** #PA3GKZYLVO68 since 2026-09-12 (reset), on P20w since 09-28. Zero real-money/audited record yet.

## Git state

- `main` = `2664503` (commercial) on top of `276799a` (P20w go-live). No feature branches (renamed `feature/vwap-experiment` → `feature/P20w`, merged & deleted).
- Working tree clean at handoff.