"""Shared emasma signal logic — the single source for BOTH live and backtest.

Owned by neither runner.py (live) nor backtest/ (research). Both import this.
The rule: if a scoring or settled-bar rule belongs to the *strategy*, it lives
here. If it belongs to *execution* (fills, sizing, cost) it lives in
backtest/harness.py. If it belongs to *orchestration* (timers, Slack, orders)
it stays in runner.py.

Adding a scoring rule here automatically changes live and backtest together,
which is the point: before this module, backtest_topn_multitf.py carried its own
copy of both functions below (with a different signature) and drifted.
"""
import math
from datetime import timedelta

import config


def settled_weekly_idx(weekly_idx, weekly_dates, today):
    """Index of the last COMPLETED weekly bar: the Monday-stamped row whose week
    has fully passed (bar_date + 7 <= today), so its settled Friday close is in
    the DB. Excludes the in-progress week's running aggregate.

    Fixes live==backtest parity (2026-09-24): the old nearest-date read pulled
    the in-progress Monday-stamped bar intraweek (e.g. SMH week of 2026-09-21 had
    close 594.49 = a partial week-to-date close), making the rotation react
    intraweek to a half-baked weekly bar, while the backtest (exact Monday match)
    only re-ranked weekly. Now both use the last fully settled week; a new week
    enters on its following Monday."""
    cutoff = today - timedelta(days=7)
    for d in reversed(weekly_dates):
        if d <= cutoff:
            return weekly_idx.get(d)
    return None


def compute_emasma_score(weekly, daily_close, wi, sig_date):
    """EMA/SMA score for ETF rotation.

    Pure weekly strategy: long when weekly EMA10 > SMA40, flat otherwise.
    Rank = min(gap_w / 5, 5) where gap_w is the weekly close vs SMA40 gap.
    No daily/hourly/ATR filters.

    Pure: no DB, no I/O. weekly must carry 'close', 'ema', 'sma', 'dates'.
    """
    if wi < config.WARMUP_BARS:
        return None

    wc = weekly['close'][wi]
    we = weekly['ema'][wi]
    ws = weekly['sma'][wi]

    if any(math.isnan(x) for x in (wc, we, ws)):
        return None
    if we <= ws:
        return None

    gap_w = (wc - ws) / ws * 100
    score = round(min(gap_w / 5, 5), 2)

    # Freshness: days since last weekly EMA/SMA crossover (informational)
    days_since = 999
    w_ema = weekly['ema']
    w_sma = weekly['sma']
    w_dates = weekly['dates']
    for j in range(wi, 0, -1):
        wj_ema = w_ema[j]
        wj_sma = w_sma[j]
        wj_ema_prev = w_ema[j - 1]
        wj_sma_prev = w_sma[j - 1]
        if not (math.isnan(wj_ema) or math.isnan(wj_sma)
                or math.isnan(wj_ema_prev) or math.isnan(wj_sma_prev)):
            if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                days_since = (sig_date - w_dates[j]).days
                break

    return {
        'score': score,
        'gap_w': round(gap_w, 1),
        'atr_dist': 0.0,
        'freshness': days_since,
        'close': round(daily_close, 2),
        'name': None,
    }

def rank_candidates(candidates, is_etf):
    """Deterministic ranking + top-N cut. Also strategy logic, not presentation.

    Sort by score DESC, then weekly gap DESC, so the selected names are
    replicable when many tickers tie at the emasma score cap (5). AGENTS.md
    requires replicable picks, so this must not diverge between live and
    backtest — it lives here for that reason.
    """
    ordered = sorted(candidates, key=lambda x: (-x['score'], -x['gap_w']))
    return ordered[:config.ETF_TOP_N if is_etf else config.TOP_N]
