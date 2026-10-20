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

import numpy as np

import config


def _weekly_ema40(weekly):
    """Weekly EMA(40) of the close series — the slow leg of the MACD diff line
    (EMA10 - EMA40). Uses the caller's precomputed 'ema40' when present (the
    backtest harness sets it), else computes it lazily from 'close' (live's
    bulk_load_weekly carries only close/ema/sma). Cached on the dict so an
    N-ticker scan pays it once per ticker."""
    e40 = weekly.get('ema40')
    if e40 is None:
        closes = weekly.get('close')
        if closes is None:
            return None
        e40 = _ewm(closes, 40)
        weekly['ema40'] = e40
    return e40


def _ewm(values, span):
    """EMA with adjust=False — identical to pandas .ewm(span=span, adjust=False)
    used everywhere else in the MTF path (db.bulk_load_weekly, the backtest),
    so the MACD diff is the same series in live and backtest."""
    out = np.empty(len(values), dtype=np.float64)
    alpha = 2.0 / (span + 1.0)
    prev = float(values[0])
    out[0] = prev
    for i in range(1, len(values)):
        x = float(values[i])
        if math.isnan(x):
            out[i] = prev
            continue
        prev = alpha * x + (1.0 - alpha) * prev
        out[i] = prev
    return out


def macd_gate_ok(weekly, wi, prox):
    """MACD cross-proximity entry gate.

    Requires the weekly EMA10>SMA40 up-cross (CO) to have its weekly MACD diff
    (EMA10-EMA40) zero-cross UP within +/-`prox` weekly bars — the TOS read
    "the diff and the CO turn in close proximity". A CO whose MACD diff turns
    +ve far outside the window (or never, within the data) is rejected: those
    far-apart crosses underperform (see config.EMASMA_MACD_GATE).

    Causal and settled-bar only: scans weekly bars at/before wi, so live and
    backtest compute the same decision. Returns True (enter) / False (reject).
    """
    w_ema = weekly.get('ema')
    w_sma = weekly.get('sma')
    w_e40 = _weekly_ema40(weekly)
    if w_ema is None or w_sma is None or w_e40 is None or wi is None:
        return False

    # Most recent CO up-cross index at/before wi.
    co_x = None
    for j in range(wi, 0, -1):
        if (math.isfinite(w_sma[j]) and math.isfinite(w_sma[j - 1])
                and math.isfinite(w_ema[j]) and math.isfinite(w_ema[j - 1])):
            if w_ema[j] > w_sma[j] and w_ema[j - 1] <= w_sma[j - 1]:
                co_x = j
                break
    if co_x is None:
        return False

    # MACD diff UP-cross (turns +ve) within [co_x - prox, co_x + prox].
    lo = max(1, co_x - prox)
    hi = min(len(w_e40) - 1, co_x + prox)
    for j in range(lo, hi + 1):
        if (math.isfinite(w_e40[j]) and math.isfinite(w_e40[j - 1])
                and math.isfinite(w_ema[j]) and math.isfinite(w_ema[j - 1])):
            md_up = (w_ema[j] - w_e40[j]) > 0
            md_prev = (w_ema[j - 1] - w_e40[j - 1]) > 0
            if md_up and not md_prev:
                return True
    return False


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


def compute_emasma_score(weekly, daily_close, wi, sig_date, use_macd_gate=False, macd_prox=None):
    """EMA/SMA score for ETF rotation.

    Pure weekly strategy: long when weekly EMA10 > SMA40, flat otherwise.
    Rank = min(gap_w / 5, 5) where gap_w is the weekly close vs SMA40 gap.
    No daily/hourly/ATR filters.

    use_macd_gate: stock leg only (config.EMASMA_MACD_GATE). When True, an
    additional entry condition applies — the weekly EMA10>SMA40 up-cross must
    be in proximity (within +/-macd_prox bars) of the weekly MACD diff
    (EMA10-EMA40) zero-cross. The ETF leg passes False (frozen experiment).

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

    if use_macd_gate:
        prox = config.EMASMA_MACD_PROX if macd_prox is None else macd_prox
        if not macd_gate_ok(weekly, wi, prox):
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

def rank_key(candidate):
    """Canonical ranking key: score DESC, then weekly gap_w DESC.

    Single definition shared by live ranking (rank_candidates) AND the executor's
    backfill filler selection, so a filler can never be chosen by a different rule
    than the top-N itself. (Before 2026-10-15 the executor sorted fillers by
    score alone, so among the many 5.0-scored names the picks were effectively
    DB order rather than the true next-best — misleading vs the reported book.)
    """
    return (-candidate.get('score', 0), -candidate.get('gap_w', 0))


def rank_candidates(candidates, is_etf):
    """Deterministic ranking + top-N cut. Also strategy logic, not presentation.

    Sort by score DESC, then weekly gap DESC, so the selected names are
    replicable when many tickers tie at the emasma score cap (5). AGENTS.md
    requires replicable picks, so this must not diverge between live and
    backtest — it lives here for that reason.
    """
    ordered = sorted(candidates, key=rank_key)
    return ordered[:config.ETF_TOP_N if is_etf else config.TOP_N]
