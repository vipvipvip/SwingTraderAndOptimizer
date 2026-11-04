#!/usr/bin/env python3
"""Top-N rotation backtest using Multi-TF score (weekly+daily bullish, gap_w, atr_dist, freshness).

Score (mtf)   = min(gap_w/20, 3) + min(atr_dist/1.5, 3) + max(0, 2 - days_since_weekly/60)
Score (near)  = max(0, 3 - gap_w/K_gap) + max(0, 3 - atr_dist/K_atr) + max(0, 2 - days_since_weekly/60)
                -- favors stocks close to their weekly SMA40 / ATR stop (proximity to the
                   crossover) instead of extended names -- anti-chase by design.
Rebalance: sell non-top-N, buy new entrants at next-day open, equal weight.

Weekly bars (settled by default, matches live runner.py `_settled_weekly_idx`):
the DB's Monday-stamped weekly row already holds that week's FRIDAY close. A
decision on Monday D therefore reads the last COMPLETED week (row dated
<= D - 7 days), never the row stamped D. Reading row D (`--legacy-weekly`)
peeks 4 trading days ahead and inflates results (ETF-28 top-3 emasma:
+636% legacy vs +106% settled, 2021-09 -> 2026-09).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import argparse
import numpy as np
import pandas as pd
import bisect
from datetime import datetime, date as dt_date, timedelta

import config
import db as db_module
from emasma_core import (compute_emasma_score as _compute_emasma_score,
                         macd_gate_ok as _macd_gate_ok)
# The CoreEW P20w state is PHP-canonical (safety rail): consume the artisan
# series, never re-implement the crossover in Python.
from backtest_trio_ew import (fetch_live_leg_ema_series as _fetch_leg_series,
                              flags_from_live_leg_ema_series as _leg_series_flags)
from portfolio_guard import GuardConfig, GuardState, step as guard_step


def _backtest_signature(args):
    """Stable signature of the backtest configuration (determines the baseline cache key)."""
    d = {
        'etf': args.etf,
        'top_n': args.top_n,
        'rebalance': args.rebalance,
        'score': args.score,
        'exit': args.exit,
        'ratchet_atr_src': args.ratchet_atr_src,
        'emasma_daily_bull': args.emasma_daily_bull,
        'emasma_gap_reverse': args.emasma_gap_reverse,
        'emasma_close_200': args.emasma_close_200,
        'emasma_fresh': args.emasma_fresh,
        'daily_only': args.daily_only,
        'legacy_weekly': args.legacy_weekly,
        'equal_weight': args.equal_weight,
        'above': args.above,
        'min_score': args.min_score,
        'infancy': args.infancy,
        'stop_loss': args.stop_loss,
        'start': args.start,
        'end': args.end,
    }
    # Conditional keys keep the historical vanilla cache entries valid while
    # ensuring a gated run can never overwrite/borrow a vanilla result.
    if getattr(args, 'emasma_macd_filter', False):
        d['emasma_macd_filter'] = True
        d['emasma_macd_prox'] = args.emasma_macd_prox
    if getattr(args, 'market_gate', 'none') != 'none':
        d['market_gate'] = args.market_gate
        d['market_gate_mode'] = args.market_gate_mode
        d['market_gate_span'] = args.market_gate_span
        d['market_gate_freq'] = args.market_gate_freq
    if getattr(args, 'daily_mark', False):
        d['daily_mark'] = True
    if getattr(args, 'stock_live_parity', False):
        d['stock_live_parity'] = True
    if getattr(args, 'sweep_at_rebalance', False):
        d['sweep_at_rebalance'] = True
    if getattr(args, 'guard_hold_peak', False):
        d['guard_hold_peak'] = True
    if getattr(args, 'guard_weekly_stop', False):
        d['guard_weekly_stop'] = True
    if getattr(args, 'hwm_stop', 0.0) > 0 or getattr(args, 'profit_sweep', 0.0) > 0:
        d['hwm_stop'] = args.hwm_stop
        d['profit_sweep'] = args.profit_sweep
        d['guard_cooldown'] = args.guard_cooldown
        d['guard_min_sweep'] = args.guard_min_sweep
    return json.dumps(d, sort_keys=True, default=str)


_BASELINE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest_baseline_cache.json')


def _load_baseline_cache():
    if not os.path.exists(_BASELINE_CACHE):
        return {}
    try:
        with open(_BASELINE_CACHE) as f:
            return json.load(f)
    except (IOError, ValueError):
        return {}


def _save_baseline_cache(cache):
    with open(_BASELINE_CACHE, 'w') as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _print_baseline(args, sig, window):
    """Print the cached 'current strategy' baseline for the same leg/window/settings.

    The A/B protocol compares every experiment against the CURRENT (vanilla) emasma
    strategy, so the lookup zeroes all --emasma-* variant flags and matches on the
    remaining config (leg, top_n, exit, ratchet source, rebalance, window pins).
    """
    cache = _load_baseline_cache()
    ref = json.loads(sig)
    for k in ('emasma_daily_bull', 'emasma_gap_reverse', 'emasma_close_200', 'emasma_fresh'):
        ref[k] = False
    # A guard experiment should compare against the same strategy without the
    # overlay; don't let the guard keys hide the vanilla baseline.
    for k in ('hwm_stop', 'profit_sweep', 'guard_cooldown', 'guard_min_sweep',
              'sweep_at_rebalance', 'guard_hold_peak', 'guard_weekly_stop'):
        ref.pop(k, None)
    ref_sig = json.dumps(ref, sort_keys=True, default=str)
    entry = cache.get(ref_sig)
    if entry is None:
        print(f'  Baseline: (current-strategy run for this leg/settings is not cached yet — '
              f'run the vanilla emasma config with --cache-baseline once)')
        return
    cb_start, cb_end = entry.get('window', [None, None])
    if window:
        run_start, run_end = str(window[0]), str(window[-1])
        match = (run_start == cb_start and run_end == cb_end)
    else:
        run_start = run_end = None
        match = False
    if match:
        flag = 'WINDOW MATCH ✓'
    elif run_start is not None:
        flag = f'⚠ window differs ({run_start}->{run_end} vs cached {cb_start}->{cb_end})'
    else:
        flag = 'window unknown'
    w_str = f'{cb_start} -> {cb_end}' if cb_start else 'auto window'
    print(f'  Baseline (cached {entry.get("cached_at", "?")}): {w_str}  '
          f'Return {entry["total_ret_pct"]:+,.0f}%  MaxDD {entry["max_dd_pct"]:.1f}%  '
          f'Win {entry["win_rate_pct"]:.0f}%  Trades {entry["sells"]}  ({flag})')
    if run_start is not None and not match:
        print(f'  Baseline: re-run with --start {cb_start} --end {cb_end} for a fair A/B.')

COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL
WARMUP = 60
EMA = 10
SMA = 40

# TOS WeeklyAndDailyPPO params (used by --ppo-filter hybrid)
WPPO_FAST = 60
WPPO_SLOW = 130
DPPO_FAST = 12
DPPO_SLOW = 26


def _last_idx_before(idx_map, dates, target):
    """Return index for `target` date, or the last available index on/before it."""
    xi = idx_map.get(target)
    if xi is not None:
        return xi
    # Walk backwards from target to find last available date
    for i in range(len(dates) - 1, -1, -1):
        if dates[i] <= target:
            return i
    return None


def _settled_weekly_idx(dates, target):
    """Index of the last COMPLETED weekly bar as of `target`: the last Monday-
    stamped row dated <= target - 7 days (its Friday close is settled). Mirrors
    runner.py `_settled_weekly_idx`. None when no such row exists."""
    i = bisect.bisect_right(dates, target - timedelta(days=7)) - 1
    return i if i >= 0 else None


# Price tables (2026-10-07): the branch logic in load_bars() keys on the old LOGICAL names; they are mapped
# here to the canonical tbl_prices_* tables (split+dividend adjusted, what live trades on). The old
# tbl_scanner_tickers* pair was dropped, so there is no other basis to select.
_PHYSICAL = {'tbl_scanner_tickers': 'tbl_prices_weekly', 'tbl_scanner_tickers_daily': 'tbl_prices_daily'}


def load_bars(conn, table, date_col, is_etf=False, symbols=None):
    """Load OHLC data from a table for all tickers (or a symbol subset)."""
    with conn.cursor() as cur:
        if symbols:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=%s AND symbol = ANY(%s) ORDER BY symbol',
                        (is_etf, list(symbols)))
        else:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=%s ORDER BY symbol', (is_etf,))
        tickers = cur.fetchall()
    print(f'  Loading {_PHYSICAL.get(table, table)} ({len(tickers)} tickers)...')

    data = {}
    for tid, sym in tickers:
        cur = conn.cursor()
        if table == 'tbl_scanner_tickers_1hour':
            cur.execute(
                f"SELECT date, close, atr_stop FROM {table} "
                f"WHERE ticker_id = %s AND date >= '2023-06-30' ORDER BY date ASC",
                (tid,))
            rows = cur.fetchall()
            seen = {}
            if rows:
                s = pd.Series([float(r[1]) if r[1] else 0.0 for r in rows])
                hem = s.ewm(span=EMA, adjust=False).mean().to_numpy()
                hsm = s.rolling(window=SMA).mean().to_numpy()
                for i, r in enumerate(rows):
                    d = r[0].date()
                    seen[d] = (d, float(r[1]) if r[1] else 0.0,
                               float(r[2]) if r[2] else 0.0, hem[i], hsm[i])
            sorted_rows = sorted(seen.values(), key=lambda x: x[0])
            dates = [r[0] for r in sorted_rows]
            closes = np.array([r[1] for r in sorted_rows], dtype=np.float64)
            atr_stops = np.array([r[2] for r in sorted_rows], dtype=np.float64)
            h_emas = np.array([r[3] for r in sorted_rows], dtype=np.float64)
            h_smas = np.array([r[4] for r in sorted_rows], dtype=np.float64)
        elif table == 'tbl_scanner_tickers':
            cur.execute(
                f'SELECT {date_col}, close, atr_stop FROM {_PHYSICAL.get(table, table)} WHERE ticker_id = %s ORDER BY {date_col} ASC',
                (tid,))
            rows = cur.fetchall()
            dates = [r[0] for r in rows]
            closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
            w_atrs = np.array([
                (float(r[1]) - float(r[2])) / 2.0 if r[2] and float(r[2]) > 0 else 0.0
                for r in rows], dtype=np.float64)
        else:
            cur.execute(
                f'SELECT {date_col}, open, close, atr_stop FROM {_PHYSICAL.get(table, table)} WHERE ticker_id = %s ORDER BY {date_col} ASC',
                (tid,))
            rows = cur.fetchall()
            dates = [r[0] for r in rows]
            opens = np.array([float(r[1]) for r in rows], dtype=np.float64)
            closes = np.array([float(r[2]) for r in rows], dtype=np.float64)
            d_atr_stops = np.array([
                float(r[3]) if r[3] else 0.0 for r in rows], dtype=np.float64)
            s = pd.Series(closes)
            d_emas = s.ewm(span=EMA, adjust=False).mean().to_numpy()
            d_smas = s.rolling(window=SMA).mean().to_numpy()
        cur.close()

        if len(dates) < WARMUP:
            continue
        d = dict(symbol=sym, dates=dates, close=closes)
        if table == 'tbl_scanner_tickers_1hour':
            d['atr_stop'] = atr_stops
            d['h_ema'] = h_emas
            d['h_sma'] = h_smas
        elif table == 'tbl_scanner_tickers_daily':
            d['open'] = opens
            d['d_ema'] = d_emas
            d['d_sma'] = d_smas
            d['d_atr_stop'] = d_atr_stops
        elif table == 'tbl_scanner_tickers':
            d['w_atr'] = w_atrs
        data[tid] = d

    return tickers, data


def _load_daily_gate_flags(conn, symbols, span, all_dates):
    """Daily close > daily EMA(span) for each gate leg, aligned to all_dates.

    Unlike the weekly CoreEW series this is a generic daily market filter; the
    stock signal itself is also read on the same daily close, so using the
    signal-day close is consistent with the rest of the backtest.
    """
    _, data = load_bars(conn, 'tbl_scanner_tickers_daily', 'date', True, symbols)
    flags = {}
    for _tid, d in data.items():
        sym = d['symbol']
        close = np.asarray(d['close'], dtype=np.float64)
        ema = pd.Series(close).ewm(span=span, adjust=False).mean().to_numpy()
        dates = d['dates']
        arr = np.zeros(len(all_dates), dtype=bool)
        j = -1
        for i, day in enumerate(all_dates):
            while j + 1 < len(dates) and dates[j + 1] <= day:
                j += 1
            if j >= 0:
                arr[i] = close[j] > ema[j]
        flags[sym] = arr
    missing = [s for s in symbols if s not in flags]
    if missing:
        raise SystemExit(f'--market-gate daily: missing daily bars for {missing}')
    return flags


def backtest(argv=None):
    """Run the backtest and return structured results (CLI prints also happen).

    Returns dict with: equity (np.array), equity_dates, trades (trade_log),
    all_dates, positions, pos_counts, args. Uses sys.argv when argv is None.
    """
    global COST
    parser = argparse.ArgumentParser(description='Top-N Multi-TF rotation backtest')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--rebalance', choices=['daily', 'weekly'], default='daily')
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--etf', action='store_true', help='Run on ETF universe (is_etf=true)')
    parser.add_argument('--score', choices=['mtf', 'early', 'emasma', 'near'], default='mtf',
                        help='Sorting score: mtf=gap+atr+fresh, early=signals+fresh-gap, '
                             'emasma=weekly EMA10>SMA40 gap, '
                             'near=proximity to SMA40/ATR stop (anti-chase)')
    parser.add_argument('--near-gap-k', type=float, default=10.0,
                        help='near score: gap_w that zeroes gap_pts (3 - gap_w/K, default K=10)')
    parser.add_argument('--near-atr-k', type=float, default=1.5,
                        help='near score: atr_dist that zeroes atr_pts (3 - atr_dist/K, default K=1.5)')
    parser.add_argument('--tickers', default=None,
                        help='Comma-separated symbol subset to backtest (e.g. ZBRA,AXON,BXC)')
    parser.add_argument('--above', choices=['none', 'ema-sma', 'ema-sma-daily', 'atr', 'both'], default='none',
                        help='Extra entry filter: require close above (1) daily+weekly EMA10 & SMA40, '
                             '(1d) daily EMA10 & SMA40 only, (2) daily ATR stop, or (3) both')
    parser.add_argument('--min-score', type=float, default=None,
                        help='Minimum MTF score to consider (e.g. 5.0 = only stocks with score >= 5)')
    parser.add_argument('--infancy', action='store_true',
                        help='Only consider tickers with days_since_weekly_cross < 60')
    parser.add_argument('--stop-loss', type=float, default=None,
                        help='Stop-loss exit: sell if position drops >N%% from entry (e.g. 5.0)')
    parser.add_argument('--top-trades', type=int, default=0,
                        help='Print top N winning/losing trades by return %%')
    parser.add_argument('--emasma-daily-bull', action='store_true',
                        help='emasma variant: also require daily EMA10>SMA40 (weekly+daily bullish, '
                             'matches the mtf _compute_score daily gate applied on top of emasma)')
    parser.add_argument('--emasma-gap-reverse', action='store_true',
                        help='emasma variant: rank by SMALLEST weekly gap first (anti-overextension '
                             '— favor names just above the weekly SMA40, max score 5.0 at 0%% gap '
                             'instead of at 25%%+). Ties still break by -gap_w populating the '
                             'opposite end of the candidate pool.')
    parser.add_argument('--emasma-close-200', action='store_true',
                        help='emasma variant: require weekly close ABOVE the weekly SMA200 AND '
                             'rank by proximity to it (smaller gap-to-200MA = higher score). '
                             'Tests the TOS-observed pattern: among EMA/SMA-bullish names, the '
                             'ones closer above the long-term 200MA outperform the far-extended ones.')
    parser.add_argument('--emasma-fresh', action='store_true',
                        help='emasma variant: rank by WEEKLY EMA10>SMA40 crossover freshness '
                             '(fewest days since the cross = highest score, max 5.0 at 0d, '
                             'decaying to 0 by 300d). Tests the observed pattern that names with '
                             'fresh weekly crosses outperform mature trends, accepting a few whipsaws.')
    parser.add_argument('--emasma-macd-filter', action='store_true',
                        help='emasma entry gate: require the weekly MACD diff (EMA10-EMA40) '
                             'zero-cross to be within +/-K weekly bars of the weekly EMA10>SMA40 '
                             'up-cross (TOS read: "diff and CO turn in close proximity"). '
                             'Rejects far-apart crosses, which underperform.')
    parser.add_argument('--emasma-macd-prox', type=int, default=5,
                        help='Max bars between the CO cross and MACD diff zero-cross for '
                             '--emasma-macd-filter (default 5).')
    parser.add_argument('--ppo-filter', action='store_true',
                        help='Hybrid: require TOS WeeklyAndDailyPPO > 0 as an extra entry filter')
    parser.add_argument('--hourly-ema-gate', action='store_true',
                        help='Entry requires EMA10>SMA40 on hourly too (all 3 timeframes bullish)')
    parser.add_argument('--hourly-daily-gap', type=float, default=None,
                        help='Block bearish hourly entries when daily gap < N%% (e.g. -5.0 = '
                             'allow bearish hourly if daily close > ema10 - 5%%)')
    parser.add_argument('--exit', choices=['rebalance', 'hourly-ema', 'ratchet-atr', 'daily-ema'], default='rebalance',
                        help='Exit rule: rebalance (sell out-of-top-N only), '
                             'hourly-ema (also sell when hourly EMA10<SMA40), '
                             'ratchet-atr (also sell when close < highest-close-since-entry - 2xATR), '
                             'daily-ema (also sell when daily EMA10<SMA40)')
    parser.add_argument('--ratchet-atr-src', choices=['hourly', 'weekly', 'daily'], default='hourly',
                        help='ATR source for --exit ratchet-atr (default hourly)')
    parser.add_argument('--daily-only', action='store_true',
                        help='Drop all hourly inputs: gate + atr_dist on daily ATR stop, '
                             'ratchet ATR from daily closes. Matches a live SUT that only '
                             'acts on settled daily bars (ignores the hourly)')
    parser.add_argument('--equal-weight', action='store_true',
                        help='CoreEW-style sizing: each cycle, trim every overweight held '
                             'position and top-up every underweight in-play name so all '
                             'positions sit at equity/len(in_play). Without this, only NEW '
                             'entries are sized (per_stock = cash/len(to_buy)) and held '
                             'winners drift untrimmed. Ratchet-sold names are excluded from '
                             'in_play for the cycle (same-day cool-off), their slots '
                             'backfilled from the rank-N+ tier.')
    parser.add_argument('--stock-live-parity', action='store_true',
                        help='Stock leg only: mirror live executor sizing — cap each name at '
                             'equity/TOP_N (SIZE_BY_TOP_N), apply REBALANCE_BAND_PCT and '
                             'MIN_TRADE_NOTIONAL to trims/top-ups, and block ratchet re-entry '
                             'for RATCHET_COOLDOWN_TRADING_DAYS trading days (backfilled from '
                             'the next-ranked candidate). Live data-gap preserves are not '
                             'modeled. ETF leg ignores this flag.')
    parser.add_argument('--market-gate', choices=['none', 'any', 'majority', 'all', 'qqq'],
                        default='none',
                        help='Stock-leg market gate: hold only while enough of QQQ/VTI/VTV are '
                             'above their own weekly EMA(span) — the live CoreEW P20w state, '
                             'consumed from the PHP-canonical artisan series. '
                             'any=1 leg, majority=2, all=3, qqq=QQQ only.')
    parser.add_argument('--market-gate-span', type=int, default=20,
                        help='EMA span for --market-gate (default 20; weekly = CoreEW P20w, '
                             'daily = daily EMA20).')
    parser.add_argument('--market-gate-freq', choices=['weekly', 'daily'], default='weekly',
                        help='Gate timeframe: weekly consumes the PHP-canonical CoreEW P20w '
                             'series; daily computes close > EMA(span) from daily bars.')
    parser.add_argument('--market-gate-mode', choices=['flat', 'entry'], default='flat',
                        help='flat = sell the whole book when the gate is OFF (CoreEW-like); '
                             'entry = block new buys only (normal exits still run).')
    parser.add_argument('--hwm-stop', type=float, default=0.0,
                        help='Portfolio HWM stop in percent (e.g. 6 = liquidate the '
                             'whole book when total equity is 6%% below its peak). '
                             '0 disables the stop.')
    parser.add_argument('--profit-sweep', type=float, default=0.0,
                        help='Sweep this percent of each new-high gain into a permanent '
                             'cash reserve (e.g. 50). 0 disables sweeps. The reserve is '
                             'never re-invested and is excluded from position sizing.')
    parser.add_argument('--guard-cooldown', type=int, default=5,
                        help='Sessions to block buys after an HWM stop (default 5).')
    parser.add_argument('--guard-min-sweep', type=float, default=0.0,
                        help='Skip sweeps smaller than this dollar amount (default 0).')
    parser.add_argument('--daily-mark', action='store_true',
                        help='Mark equity every trading day even without a guard flag. '
                             'Use for apples-to-apples HWM/sweep A/B runs; the default '
                             'keeps the historical step-frequency equity curve.')
    parser.add_argument('--sweep-at-rebalance', action='store_true',
                        help='Only sweep on rebalance execution days (default: sweep on '
                             'every new high). HWM stops still run daily.')
    parser.add_argument('--guard-hold-peak', action='store_true',
                        help='After an HWM stop, keep the old peak instead of resetting '
                             'the HWM. The guard then stays in cash until equity recovers '
                             'above the original stop line.')
    parser.add_argument('--guard-weekly-stop', action='store_true',
                        help='Check the HWM stop only on rebalance/signal sessions '
                             '(weekly close); the HWM still tracks every daily mark.')
    parser.add_argument('--cost', type=float, default=None,
                        help='Per-side cost fraction (override config.COST_PER_TRADE; '
                             'e.g. 0 = no commissions). The audit + ledger rebuild use '
                             'the engine-effected COST, keeping them reconcilable.')
    parser.add_argument('--start', default=None,
                        help='Restrict backtest to dates >= YYYY-MM-DD (fair comparison window)')
    parser.add_argument('--seed-book', default=None,
                        help='Seed the starting portfolio from a JSON file {"SYM": qty, ...}, '
                             'marked at cost at the first in-window date. Enables an '
                             'apples-to-apples replay: same book as live, only management differs.')
    parser.add_argument('--end', default=None,
                        help='Restrict backtest to dates <= YYYY-MM-DD (pin end of the '
                             'comparison window so A/B runs share an identical window)')
    parser.add_argument('--legacy-weekly', action='store_true',
                        help='LOOKAHEAD: read the decision-day Monday weekly row, which already '
                             'holds that week\'s Friday close (pre-2026-09-25 behaviour). Only for '
                             'reproducing old numbers; default reads the last settled week like live.')
    parser.add_argument('--cache-baseline', action='store_true',
                        help='Save this run into the baseline cache (json) in addition to '
                             'printing. Without it, the run still prints the cached '
                             'baseline for the same config+window, if present.')
    args = parser.parse_args(argv)
    if args.cost is not None:
        COST = args.cost
    if args.hwm_stop < 0 or args.hwm_stop >= 100:
        raise SystemExit('--hwm-stop must be >= 0 and < 100')
    if args.profit_sweep < 0 or args.profit_sweep > 100:
        raise SystemExit('--profit-sweep must be between 0 and 100')
    if args.guard_cooldown < 0:
        raise SystemExit('--guard-cooldown must be >= 0')
    guard_enabled = args.hwm_stop > 0 or args.profit_sweep > 0
    guard_cfg = None
    if guard_enabled:
        guard_cfg = GuardConfig(
            hwm_stop_pct=args.hwm_stop / 100.0,
            sweep_pct=args.profit_sweep / 100.0,
            cooldown_sessions=args.guard_cooldown,
            min_sweep=args.guard_min_sweep,
            reset_hwm_on_stop=not args.guard_hold_peak,
        )
    daily_marks = guard_enabled or args.daily_mark

    sig = _backtest_signature(args)

    db_module.init_db()
    conn = db_module.get_conn()
    try:
        is_etf = args.etf
        if is_etf:
            label = 'ETF'
        else:
            label = 'Stock'
        print(f'\n  Mode: {label} universe\n')
        symbols = set(args.tickers.split(',')) if args.tickers else None
        if symbols:
            print(f'  Subset: {len(symbols)} tickers ({", ".join(sorted(symbols))})')
        # Does THIS run read hourly bars at all? Mirrors runner.py:550
        # (`uses_hourly = (not is_etf) and strategy in ('mtf','v2')`), plus the
        # exit/gate paths that consume hourly. Decided BEFORE loading so the
        # hourly table is neither read nor indexed when it is not needed.
        uses_hourly = (
            (not is_etf and args.score in ('mtf', 'v2'))
            or args.exit == 'hourly-ema'
            or args.ratchet_atr_src == 'hourly'
            or args.hourly_ema_gate
            or args.hourly_daily_gap is not None
        ) and not args.daily_only

        _, weekly = load_bars(conn, 'tbl_scanner_tickers', 'date', is_etf, symbols)
        _, daily = load_bars(conn, 'tbl_scanner_tickers_daily', 'date', is_etf, symbols)
        if uses_hourly:
            _, hourly = load_bars(conn, 'tbl_scanner_tickers_1hour', None, is_etf, symbols)
        else:
            hourly = {}
            print('  Hourly not required by this config (weekly+daily only) '
                  '— matches the live universe for this strategy')

        # Universe: a ticker is eligible only if it has every timeframe this run
        # actually reads. Previously emasma intersected the hourly table even
        # though it never reads hourly, which silently dropped a ticker that
        # live would have ranked and traded — and hourly is documented as
        # unreliable, so it should not gate the universe at all.
        common = set(weekly) & set(daily)
        if uses_hourly:
            common = common & set(hourly)
        print(f'  Tickers with required timeframes '
              f'({"weekly+daily+hourly" if uses_hourly else "weekly+daily"}): '
              f'{len(common)}')
        for tid in list(weekly.keys()):
            if tid not in common:
                del weekly[tid]
        for tid in list(daily.keys()):
            if tid not in common:
                del daily[tid]
        if uses_hourly:
            for tid in list(hourly.keys()):
                if tid not in common:
                    del hourly[tid]

        # Pre-compute weekly and daily EMA/SMA
        for tid in weekly:
            wc = pd.Series(weekly[tid]['close'])
            weekly[tid]['ema'] = wc.ewm(span=EMA, adjust=False).mean().to_numpy()
            weekly[tid]['sma'] = wc.rolling(window=SMA).mean().to_numpy()
            weekly[tid]['sma200'] = wc.rolling(window=200).mean().to_numpy()
            # MACD diff line = EMA10 - EMA40 (same periods as the CO fast leg,
            # different slow leg: EMA40 vs SMA40). Its zero-cross is the TOS
            # 'diff turns +/-' event the user reads. ema40 enables the
            # --emasma-macd-filter entry gate.
            weekly[tid]['ema40'] = wc.ewm(span=40, adjust=False).mean().to_numpy()
        for tid in daily:
            dc = pd.Series(daily[tid]['close'])
            daily[tid]['ema'] = dc.ewm(span=EMA, adjust=False).mean().to_numpy()
            daily[tid]['sma'] = dc.rolling(window=SMA).mean().to_numpy()

        if args.ppo_filter:
            for tid in weekly:
                wc = pd.Series(weekly[tid]['close'])
                weekly[tid]['ppo_fast'] = wc.ewm(span=WPPO_FAST, adjust=False).mean().to_numpy()
                weekly[tid]['ppo_slow'] = wc.ewm(span=WPPO_SLOW, adjust=False).mean().to_numpy()
            for tid in daily:
                dc = pd.Series(daily[tid]['close'])
                daily[tid]['ppo_fast'] = dc.ewm(span=DPPO_FAST, adjust=False).mean().to_numpy()
                daily[tid]['ppo_slow'] = dc.ewm(span=DPPO_SLOW, adjust=False).mean().to_numpy()

        # Build date index maps
        daily_idx = {}
        for tid in daily:
            daily_idx[tid] = {dt: i for i, dt in enumerate(daily[tid]['dates'])}
        weekly_idx = {}
        for tid in weekly:
            weekly_idx[tid] = {dt: i for i, dt in enumerate(weekly[tid]['dates'])}
        hourly_idx = {}
        for tid in hourly:
            hourly_idx[tid] = {dt: i for i, dt in enumerate(hourly[tid]['dates'])}

        MIN_TICKERS = 10 if is_etf else 400
        if symbols:
            MIN_TICKERS = min(10, len(common))
        # All trading dates from daily table (union across all tickers)
        all_dates = sorted(set().union(*[set(d['dates']) for d in daily.values()]))
        # Exclude dates where fewer than MIN_TICKERS tickers have data (partial days)
        all_dates = [d for d in all_dates if sum(1 for td in daily.values() if d in td['dates']) >= MIN_TICKERS]
        print(f'  Daily date range: {all_dates[0]} to {all_dates[-1]} ({len(all_dates)} days)')

        # Start when enough tickers have data
        skip = 0
        for ri, d in enumerate(all_dates):
            cnt = sum(1 for td in daily.values() if d in td['dates'])
            if cnt >= MIN_TICKERS:
                skip = ri
                break
        all_dates = all_dates[skip:]

        # Further filter: need at least WARMUP bars for SMA
        start_idx = 0
        for ri, d in enumerate(all_dates):
            cnt = 0
            for tid in common:
                wi = weekly_idx[tid].get(d)
                if wi is not None and wi >= WARMUP:
                    cnt += 1
            if cnt >= MIN_TICKERS:
                start_idx = ri
                break
        all_dates = all_dates[start_idx:]
        if args.start:
            from datetime import date as _date
            _start = _date.fromisoformat(args.start)
            all_dates = [d for d in all_dates if d >= _start]
        if args.end:
            from datetime import date as _date
            _end = _date.fromisoformat(args.end)
            all_dates = [d for d in all_dates if d <= _end]
        print(f'  Universe: {len(common)} tickers, warmup from {all_dates[0]}')

        # Optional CoreEW-style market regime gate (stock leg only). The leg
        # states come from the live PHP series, aligned to the stock decision
        # dates with the same settled-week rule the backtest already uses.
        market_gate_on = None
        if args.market_gate != 'none':
            if is_etf:
                raise SystemExit('--market-gate is stock-leg only (the ETF leg IS the trio)')
            gate_syms = ['QQQ', 'VTI', 'VTV']
            if args.market_gate_freq == 'weekly':
                print(f'  Market gate: fetching P{args.market_gate_span}w CoreEW leg state '
                      f'(PHP-canonical)...')
                gate_payload = _fetch_leg_series(args.market_gate_span, gate_syms)
                gate_flags = _leg_series_flags(all_dates, gate_payload)
            else:
                print(f'  Market gate: daily EMA{args.market_gate_span} on '
                      f'{"/".join(gate_syms)}...')
                gate_flags = _load_daily_gate_flags(conn, gate_syms,
                                                    args.market_gate_span, all_dates)
            gate_counts = np.array([gate_flags[s].astype(int) for s in gate_syms]).sum(axis=0)
            if args.market_gate == 'any':
                market_gate_on = gate_counts >= 1
            elif args.market_gate == 'majority':
                market_gate_on = gate_counts >= 2
            elif args.market_gate == 'all':
                market_gate_on = gate_counts >= 3
            else:  # qqq
                market_gate_on = gate_flags['QQQ'].astype(bool)
            print(f'  Market gate: {args.market_gate} ({args.market_gate_mode}) -> '
                  f'{100 * market_gate_on.mean():.0f}% of days ON, '
                  f'{int((~market_gate_on).sum())} OFF')

        step = 5 if args.rebalance == 'weekly' else 1
        period_label = f'{args.rebalance} (every {step} trading day{"s" if step > 1 else ""})'
        print(f'  Running: top {args.top_n}, rebalance {period_label}...\n')

        # Portfolio state
        positions = {}
        cash = CAPITAL
        reserve = 0.0
        guard_state = GuardState(hwm=0.0) if guard_enabled else None
        guard_events = []
        live_parity = bool(args.stock_live_parity and not args.etf)
        parity_band = float(getattr(config, 'REBALANCE_BAND_PCT', 0.0)) if live_parity else 0.0
        parity_min = float(getattr(config, 'MIN_TRADE_NOTIONAL', 0.0)) if live_parity else 0.0
        parity_cap_top_n = bool(getattr(config, 'SIZE_BY_TOP_N', True)) if live_parity else False
        parity_cooldown = int(getattr(config, 'RATCHET_COOLDOWN_TRADING_DAYS', 0)) if live_parity else 0
        ratchet_cooldown_until = {}
        equity_curve = []
        equity_dates = []
        pos_counts = []
        trade_log = []  # (date, symbol, side, shares, price, ret)

        def _sell_all(exec_date, reason):
            """Liquidate the whole book at exec_date's open (market-gate flat)."""
            nonlocal cash
            for tid in list(positions):
                d = daily.get(tid)
                if d is None:
                    continue
                xi = _last_idx_before(daily_idx[tid], d['dates'], exec_date)
                if xi is None or xi >= len(d['open']):
                    continue
                sp = float(d['open'][xi])
                pos = positions[tid]
                proceeds = pos['shares'] * sp * (1 - COST)
                ret = (sp - pos['entry_price']) / pos['entry_price'] - COST
                cash += proceeds
                trade_log.append((exec_date, pos['symbol'], reason, pos['shares'], sp, ret))
                if args.detail:
                    print(f'  {exec_date} {reason} {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f}')
                del positions[tid]

        def _mark_value(mark_date):
            """Total equity (active + reserve) marked at mark_date close."""
            val = cash
            for tid, pos in positions.items():
                d = daily.get(tid)
                if d is None:
                    continue
                xi = _last_idx_before(daily_idx[tid], d['dates'], mark_date)
                if xi is not None:
                    val += pos['shares'] * float(d['close'][xi])
            return val

        def _sell_all_close(mark_date, reason):
            """Liquidate the whole book at mark_date's close (HWM stop)."""
            nonlocal cash
            for tid in list(positions):
                d = daily.get(tid)
                if d is None:
                    continue
                xi = _last_idx_before(daily_idx[tid], d['dates'], mark_date)
                if xi is None or xi >= len(d['close']):
                    continue
                sp = float(d['close'][xi])
                pos = positions[tid]
                proceeds = pos['shares'] * sp * (1 - COST)
                ret = (sp - pos['entry_price']) / pos['entry_price'] - COST
                cash += proceeds
                trade_log.append((mark_date, pos['symbol'], reason, pos['shares'], sp, ret))
                if args.detail:
                    print(f'  {mark_date} {reason} {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f}')
                del positions[tid]

        def _sweep_at_close(mark_date, amount):
            """Move `amount` from active capital to the permanent reserve.

            Uses idle active cash first, then sells the book pro-rata. Returns
            the amount actually moved (net of any sale cost).
            """
            nonlocal cash, reserve
            if amount <= 0:
                return 0.0
            available = cash - reserve
            if available >= amount:
                reserve += amount
                return amount

            px_by_tid = {}
            pos_val = 0.0
            for tid, pos in positions.items():
                d = daily.get(tid)
                if d is None:
                    continue
                xi = _last_idx_before(daily_idx[tid], d['dates'], mark_date)
                if xi is None:
                    continue
                px = float(d['close'][xi])
                px_by_tid[tid] = px
                pos_val += pos['shares'] * px
            if pos_val <= 0:
                realized = max(0.0, available)
                reserve += realized
                return realized

            shortfall = amount - available
            gross = min(shortfall / (1.0 - COST), pos_val)
            if gross <= 0:
                reserve += max(0.0, available)
                return max(0.0, available)

            ratio = gross / pos_val
            for tid, pos in list(positions.items()):
                px = px_by_tid.get(tid)
                if px is None or px <= 0:
                    continue
                sell_sh = pos['shares'] * ratio
                proceeds = sell_sh * px * (1 - COST)
                cash += proceeds
                pos['shares'] -= sell_sh
                trade_log.append((mark_date, pos['symbol'], 'SELL-SWEEP', sell_sh, px, None))
                if args.detail:
                    print(f'  {mark_date} SWEEP {pos["symbol"]} {sell_sh:.2f} @ ${px:.2f}')
                if pos['shares'] <= 1e-9:
                    del positions[tid]

            realized = available + gross * (1 - COST)
            reserve += realized
            return realized

        def _mark_and_guard(mark_date, is_rebalance_day=False):
            """Append one daily equity point, then apply the guard at that close."""
            nonlocal cash, reserve, guard_state
            if equity_dates and equity_dates[-1] == mark_date:
                return
            equity = _mark_value(mark_date)
            if guard_enabled:
                allow_sweep = (not args.sweep_at_rebalance) or is_rebalance_day
                allow_stop = (not args.guard_weekly_stop) or is_rebalance_day
                guard_state, gd = guard_step(
                    guard_state, guard_cfg, equity=equity, session=str(mark_date),
                    allow_sweep=allow_sweep, allow_stop=allow_stop)
                if gd.liquidate:
                    _sell_all_close(mark_date, 'SELL-GUARD')
                    guard_events.append((mark_date, 'HWM_STOP', equity, reserve, 0.0))
                    if args.detail:
                        print(f'  {mark_date} GUARD HWM STOP at ${equity:,.2f}')
                elif gd.sweep_amount > 0:
                    realized = _sweep_at_close(mark_date, gd.sweep_amount)
                    guard_state.record_sweep(realized)
                    guard_events.append((mark_date, 'SWEEP', equity, reserve, realized))
                    if args.detail:
                        print(f'  {mark_date} GUARD SWEEP ${realized:,.2f} -> reserve ${reserve:,.2f}')
                equity = _mark_value(mark_date)
            equity_curve.append(equity)
            equity_dates.append(mark_date)
            pos_counts.append(len(positions))

        # Optional seeded book (apples-to-apples replay): start with live's
        # exact holdings marked at the first in-window date's open, so the only
        # difference vs live is how the book is MANAGED from here on.
        if args.seed_book:
            import json as _json
            with open(args.seed_book) as _f:
                seed = _json.load(_f)
            sym_to_tid = {}
            for tid in common:
                s = weekly[tid].get('symbol') or daily[tid].get('symbol')
                if s:
                    sym_to_tid[s] = tid
            seed_date = all_dates[0]
            for sym, val in seed.items():
                tid = sym_to_tid.get(sym)
                if tid is None:
                    print(f'  [seed] {sym}: no tid in universe — skipped')
                    continue
                di = daily_idx[tid].get(seed_date)
                if di is None:
                    print(f'  [seed] {sym}: no daily bar at {seed_date} — skipped')
                    continue
                # val = qty  OR  {"qty":..,"price":..} (real fill basis)
                if isinstance(val, dict):
                    qty = float(val['qty']); px = float(val.get('price') or daily[tid]['open'][di])
                else:
                    qty = float(val); px = float(daily[tid]['open'][di])
                cost = qty * px * (1 + COST)
                cash -= cost
                positions[tid] = dict(shares=qty, entry_price=px,
                                      symbol=sym, peak=px, ratchet=0.0)
            print(f'  [seed] booked {len(positions)} names at {seed_date}, cash=${cash:,.0f}')

        for ri in range(0, len(all_dates), step):
            sig_date = all_dates[ri]
            market_off = bool(market_gate_on is not None and not market_gate_on[ri])

            # Mark the signal-date close and run the guard BEFORE the next-open
            # rebalance. A stop or sweep therefore changes the book that the
            # rebalance sees, instead of buying at the open and then liquidating
            # at the same day's close.
            if daily_marks:
                _mark_and_guard(sig_date, is_rebalance_day=True)
            guard_paused = bool(guard_state is not None and guard_state.pause_sessions > 0)

            # Compute Multi-TF scores for all tickers
            candidates = []
            for tid in common:
                di = daily_idx[tid].get(sig_date)
                wi = weekly_idx[tid].get(sig_date)
                if wi is not None and not args.legacy_weekly:
                    # Decision days stay the weekly-row (Monday) dates, but the
                    # bar READ is the last completed week (see module docstring).
                    wi = _settled_weekly_idx(weekly[tid]['dates'], sig_date)
                hi = hourly_idx[tid].get(sig_date) if hourly_idx else None

                if args.score == 'emasma':
                    # Strategy signal: weekly EMA10 > SMA40 (long), flat otherwise.
                    # No daily/hourly/ATR filters — pure weekly strategy under
                    # the same top-N rotation mechanics. With --emasma-daily-bull
                    # the daily EMA10>SMA40 gate (from the mtf _compute_score) is
                    # also required, giving the 'weekly+daily bullish' variant.
                    if wi is None or wi < WARMUP:
                        continue
                    we = weekly[tid]['ema'][wi]
                    ws = weekly[tid]['sma'][wi]
                    wc = weekly[tid]['close'][wi]
                    if np.isnan(we) or np.isnan(ws) or np.isnan(wc):
                        continue
                    if we <= ws:
                        continue
                    if args.emasma_macd_filter:
                        # MACD cross-proximity gate — the SAME implementation live
                        # uses (emasma_core.macd_gate_ok; stock leg via
                        # config.EMASMA_MACD_GATE). Require the weekly EMA10>SMA40
                        # up-cross to have its weekly MACD diff (EMA10-EMA40)
                        # zero-cross UP within +/-K weekly bars. Kept as a
                        # separate backtest flag so the gate can be A/B'd off,
                        # but the logic is shared, not duplicated.
                        if not _macd_gate_ok(weekly[tid], wi, args.emasma_macd_prox):
                            continue
                    if args.emasma_daily_bull:
                        if di is None or di < 1:
                            continue
                        de = daily[tid]['d_ema'][di]
                        ds = daily[tid]['d_sma'][di]
                        if np.isnan(de) or np.isnan(ds) or de <= ds:
                            continue
                    gap_w = (wc - ws) / ws * 100
                    if args.emasma_fresh:
                        # Freshness-ranked: days since the LAST weekly EMA10>SMA40
                        # cross. Fewest days = highest score (5.0 at 0d -> 0 by
                        # 300d, mirroring fresh_pts = max(0, 2 - days_since/60)
                        # from the mtf score but as the PRIMARY rank). Ignores gap
                        # entirely — a 3d-old cross outranks a 200% gap.
                        days_since = 999
                        w_ema = weekly[tid]['ema']
                        w_sma = weekly[tid]['sma']
                        w_dates = weekly[tid]['dates']
                        for j in range(wi, 0, -1):
                            wj_ema, wj_sma = w_ema[j], w_sma[j]
                            wj_ema_prev, wj_sma_prev = w_ema[j - 1], w_sma[j - 1]
                            if (not np.isnan(wj_ema) and not np.isnan(wj_sma)
                                    and not np.isnan(wj_ema_prev) and not np.isnan(wj_sma_prev)):
                                if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                                    days_since = (sig_date - w_dates[j]).days
                                    break
                        emasma_score = round(max(0.0, 5.0 - days_since / 60), 2)
                    elif args.emasma_close_200:
                        # TOS-observed pattern: among EMA/SMA-bullish names, those
                        # closer ABOVE the weekly SMA200 outperform far-extended ones.
                        # Require close above the long-term trend AND rank by
                        # proximity to it (smaller gap-to-200MA = higher score).
                        w200 = weekly[tid]['sma200'][wi]
                        if np.isnan(w200) or w200 <= 0:
                            continue
                        gap200 = (wc - w200) / w200 * 100
                        if wc <= w200:
                            continue  # hard filter: must be above the 200MA
                        emasma_score = round(max(0.0, 5.0 - gap200 / 25), 2)
                    elif args.emasma_gap_reverse:
                        # Anti-overextension: smallest gap_w ranks highest (max 5.0
                        # at 0% gap, decaying to 0 at 25%+). Requires the weekly
                        # bullish filter above (we>ws), so gap_w is always > 0.
                        emasma_score = round(max(0.0, 5.0 - gap_w / 5), 2)
                    else:
                        # DEFAULT strategy signal — the SAME implementation live
                        # uses (emasma_core.compute_emasma_score), so backtest and
                        # live can no longer drift. The shared function re-applies
                        # the warmup/NaN/we<=ws guards and returns score+gap_w;
                        # live passes the nearest daily close, so mirror that (di
                        # may be None on weekly-only days — the field is
                        # informational and never feeds the score).
                        _dc = daily[tid]['close'][di] if di is not None else wc
                        _res = _compute_emasma_score(weekly[tid], _dc, wi, sig_date)
                        if _res is None:
                            continue
                        emasma_score = _res['score']
                        gap_w = _res['gap_w']
                    candidates.append((tid, emasma_score, gap_w))
                    continue

                if args.daily_only:
                    if di is None or wi is None:
                        continue
                    if di < 1 or wi < WARMUP:
                        continue
                else:
                    if di is None or wi is None or hi is None:
                        continue
                    if di < 1 or wi < WARMUP or hi < 1:
                        continue

                wc = weekly[tid]['close'][wi]
                we = weekly[tid]['ema'][wi]
                ws = weekly[tid]['sma'][wi]
                dc = daily[tid]['close'][di]
                de = daily[tid]['ema'][di]
                ds = daily[tid]['sma'][di]
                hc = hourly[tid]['close'][hi] if not args.daily_only else 0
                ha = hourly[tid]['atr_stop'][hi] if not args.daily_only else 0

                # NaN checks
                if any(np.isnan(x) for x in (wc, we, ws, dc, de, ds)):
                    continue
                if we <= ws or de <= ds:
                    continue  # weekly or daily not bullish
                if not args.daily_only:
                    if hc <= ha or hc <= 0:
                        continue

                if args.above in ('ema-sma', 'ema-sma-daily', 'both'):
                    if args.above != 'ema-sma-daily':
                        if wc <= we or wc <= ws:
                            continue  # weekly close not above weekly EMA10/SMA40
                    if dc <= de or dc <= ds:
                        continue  # daily close not above daily EMA10/SMA40
                if args.above in ('atr', 'both'):
                    das = daily[tid]['d_atr_stop'][di]
                    if das is None or np.isnan(das) or das <= 0 or dc <= das:
                        continue  # daily close not above daily ATR stop

                if args.hourly_ema_gate and not args.daily_only:
                    he = hourly[tid]['h_ema'][hi]
                    hs = hourly[tid]['h_sma'][hi]
                    if np.isnan(he) or np.isnan(hs) or he <= hs:
                        continue  # hourly not bullish

                if args.hourly_daily_gap is not None and not args.daily_only:
                    he = hourly[tid]['h_ema'][hi]
                    hs = hourly[tid]['h_sma'][hi]
                    if not np.isnan(he) and not np.isnan(hs) and he <= hs:
                        # hourly is bearish — allow only if daily gap is shallow
                        dc_val = float(d['close'][di]) if di < len(d['close']) else 0
                        de_val = daily[tid]['ema'][di]
                        if dc_val > 0 and not np.isnan(de_val) and de_val > 0:
                            daily_gap_pct = (dc_val - de_val) / de_val * 100
                            if daily_gap_pct <= args.hourly_daily_gap:
                                continue  # daily gap too deep, broken trend

                if args.ppo_filter:
                    ws130 = weekly[tid]['ppo_slow'][wi]
                    if np.isnan(ws130) or ws130 <= 0:
                        continue
                    wppo = (weekly[tid]['ppo_fast'][wi] - ws130) / ws130 * 100
                    dppo = (daily[tid]['ppo_fast'][di] - daily[tid]['ppo_slow'][di]) / ws130 * 100
                    if wppo + dppo <= 0:
                        continue  # WeeklyAndDailyPPO not bullish

                # gap_w: weekly gap from SMA
                gap_w = (wc - ws) / ws * 100
                if args.daily_only:
                    # atr_dist: distance from DAILY ATR stop (no hourly inputs)
                    das = daily[tid]['d_atr_stop'][di]
                    if das is None or np.isnan(das) or das <= 0:
                        das = 0.0
                    atr_dist = (dc - das) / dc * 100 if das > 0 else 0
                else:
                    # atr_dist: distance from ATR stop (using hourly data)
                    atr_dist = (hc - ha) / hc * 100 if ha > 0 else 0

                # Days since last weekly EMA > SMA cross
                days_since = 999
                for j in range(wi, 0, -1):
                    wj_ema = weekly[tid]['ema'][j]
                    wj_sma = weekly[tid]['sma'][j]
                    wj_ema_prev = weekly[tid]['ema'][j - 1]
                    wj_sma_prev = weekly[tid]['sma'][j - 1]
                    if (not np.isnan(wj_ema) and not np.isnan(wj_sma)
                            and not np.isnan(wj_ema_prev) and not np.isnan(wj_sma_prev)):
                        if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                            days_since = (sig_date - weekly[tid]['dates'][j]).days
                            break

                # Score components
                gap_pts = min(gap_w / 20, 3)
                atr_pts = min(atr_dist / 1.5, 3)
                fresh_pts = max(0, 2 - days_since / 60)
                mtf_score = round(gap_pts + atr_pts + fresh_pts, 1)

                # Near score: favor proximity to weekly SMA40 / ATR stop (anti-chase).
                # A stock just past its crossover (small gap_w) or pulled back to its
                # ratchet (small atr_dist) ranks higher than an extended name.
                near_gap_pts = max(0.0, 3.0 - gap_w / args.near_gap_k)
                near_atr_pts = max(0.0, 3.0 - atr_dist / args.near_atr_k)
                near_score = round(near_gap_pts + near_atr_pts + fresh_pts, 1)

                # Early score: signal count + fresh_pts - gap_pts
                # Signal count: daily_signal (days_since<60) + emac (daily EMA>SMA) + chand (close>atr_stop)
                # EMAC and CHAND are already required by the filter, so base is 2
                signal_cnt = 2 + (1 if days_since < 60 else 0)
                early_score = round(signal_cnt + fresh_pts - gap_pts, 1)

                decision_score = (near_score if args.score == 'near'
                                  else early_score if args.score == 'early'
                                  else mtf_score)
                if args.min_score is not None and mtf_score < args.min_score:
                    continue
                if args.infancy and days_since >= 60:
                    continue
                candidates.append((tid, decision_score, gap_w))

            if not candidates:
                # MTM at the label date's close — same convention as the
                # candidate path (value the portfolio at exec_date close).
                # Using sig_date's close here labels tomorrow's date with
                # today's value: an off-by-one that understated the final
                # equity point (surfaced by the audit template reconciliation).
                if (market_off and args.market_gate_mode == 'flat' and positions
                        and ri + 1 < len(all_dates)):
                    _sell_all(all_dates[ri + 1], 'SELL-GATE')
                if daily_marks:
                    # Mark through the session before the next signal date.
                    # The next iteration marks that signal date itself, with
                    # the guard allowed to sweep before its rebalance.
                    for gj in range(ri + 1, min(ri + step, len(all_dates))):
                        _mark_and_guard(all_dates[gj])
                else:
                    pf_val = cash
                    label_date = all_dates[min(ri + 1, len(all_dates) - 1)]
                    for tid in list(positions):
                        p = _last_idx_before(daily_idx[tid], daily[tid]['dates'], label_date)
                        if p is not None:
                            pf_val += positions[tid]['shares'] * float(daily[tid]['close'][p])
                    equity_curve.append(pf_val)
                    equity_dates.append(label_date)
                    pos_counts.append(len(positions))
                continue

            # Live parity: a ratchet sell blocks re-entry for N trading days;
            # exclude it from the candidate pool so the slot backfills from N+1.
            if live_parity and ratchet_cooldown_until:
                candidates = [c for c in candidates
                              if ratchet_cooldown_until.get(c[0], -1) <= ri]

            # Sort by score DESC, then by weekly gap DESC for a deterministic,
            # replicable selection when many tickers tie at the score cap.
            candidates.sort(key=lambda x: (-x[1], -x[2]))
            selected = {c[0] for c in candidates[:args.top_n]}

            exec_idx = ri + 1
            if exec_idx >= len(all_dates):
                break
            exec_date = all_dates[exec_idx]

            # STOP-LOSS: sell positions that dropped >stop-loss% from entry
            if args.stop_loss is not None:
                for tid in list(positions):
                    d = daily.get(tid)
                    if d is None:
                        continue
                    si = _last_idx_before(daily_idx[tid], daily[tid]['dates'], sig_date)
                    if si is None:
                        continue
                    current_close = float(d['close'][si])
                    pos = positions[tid]
                    drop_pct = (pos['entry_price'] - current_close) / pos['entry_price'] * 100
                    if drop_pct >= args.stop_loss:
                        xi = _last_idx_before(daily_idx[tid], daily[tid]['dates'], exec_date)
                        if xi is None or xi >= len(d['open']):
                            continue
                        sp = float(d['open'][xi])
                        proceeds = pos['shares'] * sp * (1 - COST)
                        ret = (sp - pos['entry_price']) / pos['entry_price'] - COST
                        cash += proceeds
                        trade_log.append((exec_date, pos['symbol'], 'SELL-STOP', pos['shares'], sp, ret))
                        if args.detail:
                            print(f'  {exec_date} STOP  {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f} ({drop_pct:.1f}% drop)')
                        del positions[tid]

            # Market gate OFF + flat mode: liquidate the whole book before the
            # normal per-name exits (CoreEW goes to cash when the regime is off).
            if market_off and args.market_gate_mode == 'flat' and positions:
                _sell_all(exec_date, 'SELL-GATE')

            # SELL: liquidate positions not in selected, or hourly-EMA / ratchet-ATR exit
            ratchet_sold_cycle = set()
            for tid in list(positions):
                reason = None
                if tid not in selected:
                    reason = 'SELL'
                elif args.exit == 'hourly-ema' and not args.daily_only:
                    hp = hourly.get(tid)
                    if hp is not None:
                        hxi = _last_idx_before(hourly_idx[tid], hp['dates'], sig_date)
                        if (hxi is not None and not np.isnan(hp['h_ema'][hxi])
                                and not np.isnan(hp['h_sma'][hxi])
                                and hp['h_ema'][hxi] < hp['h_sma'][hxi]):
                            reason = 'SELL-H-EMA'
                elif args.exit == 'ratchet-atr':
                    pos = positions[tid]
                    d = daily.get(tid)
                    si = _last_idx_before(daily_idx[tid], d['dates'], sig_date)
                    if si is None:
                        continue
                    close_t = float(d['close'][si])
                    atr = 0.0
                    if args.ratchet_atr_src == 'weekly':
                        w = weekly.get(tid)
                        if w is not None:
                            if args.legacy_weekly:
                                wi = _last_idx_before(weekly_idx[tid], w['dates'], sig_date)
                            else:
                                wi = _settled_weekly_idx(w['dates'], sig_date)
                            if wi is not None:
                                atr = float(w['w_atr'][wi]) if np.isfinite(w['w_atr'][wi]) else 0.0
                    elif args.ratchet_atr_src == 'daily' or args.daily_only:
                        if si is not None and np.isfinite(d['d_atr_stop'][si]) and d['d_atr_stop'][si] > 0:
                            atr = (float(d['close'][si]) - float(d['d_atr_stop'][si])) / 2.0
                    else:
                        hp = hourly.get(tid)
                        if hp is not None:
                            hxi = _last_idx_before(hourly_idx[tid], hp['dates'], sig_date)
                            if hxi is not None:
                                atr = (float(hp['close'][hxi]) - float(hp['atr_stop'][hxi])) / 2.0
                    if atr > 0:
                        pos['peak'] = max(pos.get('peak', pos['entry_price']), close_t)
                        pos['ratchet'] = max(pos.get('ratchet', 0.0), pos['peak'] - 2.0 * atr)
                        if close_t < pos['ratchet']:
                            reason = 'SELL-RATC'
                elif args.exit == 'daily-ema':
                    d = daily.get(tid)
                    if d is not None:
                        si = _last_idx_before(daily_idx[tid], d['dates'], sig_date)
                        if (si is not None and not np.isnan(d['d_ema'][si])
                                and not np.isnan(d['d_sma'][si])
                                and d['d_ema'][si] < d['d_sma'][si]):
                            reason = 'SELL-D-EMA'
                if reason is None:
                    continue
                d = daily.get(tid)
                if d is None:
                    continue
                xi = _last_idx_before(daily_idx[tid], daily[tid]['dates'], exec_date)
                if xi is None or xi >= len(d['open']):
                    continue
                sp = float(d['open'][xi])
                pos = positions[tid]
                proceeds = pos['shares'] * sp * (1 - COST)
                ret = (sp - pos['entry_price']) / pos['entry_price'] - COST
                cash += proceeds
                trade_log.append((exec_date, pos['symbol'], reason, pos['shares'], sp, ret))
                if args.detail:
                    print(f'  {exec_date} {reason} {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f}')
                if reason == 'SELL-RATC':
                    ratchet_sold_cycle.add(tid)
                    if parity_cooldown > 0:
                        ratchet_cooldown_until[tid] = exec_idx + parity_cooldown
                del positions[tid]

            # BUY / SIZING: equal-weight the whole book (CoreEW-style) or add new
            # selected positions (legacy new-entry-only sizing).
            to_buy = [tid for tid in selected if tid not in positions]
            if args.equal_weight and not market_off and not guard_paused:
                # in-play = selected names minus same-day ratchet-sold (cool-off);
                # vacated slots backfilled from the rank-N+ tier.
                in_play = [tid for tid in selected if tid not in ratchet_sold_cycle]
                if len(in_play) < args.top_n:
                    for c in candidates:
                        if len(in_play) >= args.top_n:
                            break
                        if c[0] not in in_play and c[0] not in ratchet_sold_cycle:
                            in_play.append(c[0])
                # mark the book at exec-date open (same price we transact at).
                # Size on ACTIVE equity only: the permanent reserve is not
                # buying power and must never be re-invested.
                eq_open = cash - reserve
                open_px = {}
                for tid, pos in positions.items():
                    d = daily.get(tid)
                    if d is None:
                        continue
                    xi = _last_idx_before(daily_idx[tid], d['dates'], exec_date)
                    if xi is None or xi >= len(d['open']):
                        continue
                    op = float(d['open'][xi])
                    open_px[tid] = op
                    eq_open += pos['shares'] * op
                if in_play:
                    per_position = eq_open / len(in_play)
                    if parity_cap_top_n:
                        per_position = min(per_position, eq_open / max(1, args.top_n))
                    # 1) TRIM overweight held positions down to the target.
                    for tid in list(positions):
                        if tid not in in_play:
                            continue
                        op = open_px.get(tid)
                        if op is None or op <= 0:
                            continue
                        pos = positions[tid]
                        excess = pos['shares'] * op - per_position
                        if excess <= 0:
                            continue
                        if live_parity:
                            if excess < per_position * (parity_band / 100.0):
                                continue
                            if excess < parity_min:
                                continue
                        sell_sh = excess / op
                        proceeds = sell_sh * op * (1 - COST)
                        cash += proceeds
                        pos['shares'] -= sell_sh
                        trade_log.append((exec_date, pos['symbol'], 'SELL-TRIM', sell_sh, op, None))
                        if args.detail:
                            print(f'  {exec_date} TRIM {pos["symbol"]} {sell_sh:.2f} @ ${op:.2f}')
                    # 2) BUY / TOP-UP underweight in-play names up to the target.
                    for tid in in_play:
                        d = daily.get(tid)
                        if d is None:
                            continue
                        xi = _last_idx_before(daily_idx[tid], d['dates'], exec_date)
                        if xi is None or xi >= len(d['open']):
                            continue
                        bp = float(d['open'][xi])
                        cur_val = positions[tid]['shares'] * bp if tid in positions else 0.0
                        needed = per_position - cur_val
                        if needed <= 0:
                            continue
                        if live_parity and tid in positions:
                            if needed < per_position * (parity_band / 100.0):
                                continue
                            if needed < parity_min:
                                continue
                        needed = min(needed, max(0.0, cash - reserve))
                        if needed <= 0:
                            continue
                        buy_sh = (needed / bp) * (1 - COST)
                        cost = buy_sh * bp
                        cash -= cost
                        if tid in positions:
                            positions[tid]['shares'] += buy_sh
                            trade_log.append((exec_date, daily[tid]['symbol'], 'BUY-ADD', buy_sh, bp, None))
                            if args.detail:
                                print(f'  {exec_date} ADD  {daily[tid]["symbol"]} {buy_sh:.2f} @ ${bp:.2f}')
                        else:
                            sym = daily[tid]['symbol']
                            positions[tid] = dict(shares=buy_sh, entry_price=bp, symbol=sym, peak=bp, ratchet=0.0)
                            trade_log.append((exec_date, sym, 'BUY', buy_sh, bp, None))
                            if args.detail:
                                print(f'  {exec_date} BUY  {sym} {buy_sh:.2f} @ ${bp:.2f}')
            elif to_buy and not market_off and not guard_paused:
                per_stock = max(0.0, cash - reserve) / len(to_buy)
                for tid in to_buy:
                    d = daily.get(tid)
                    if d is None:
                        continue
                    xi = _last_idx_before(daily_idx[tid], daily[tid]['dates'], exec_date)
                    if xi is None or xi >= len(d['open']):
                        continue
                    bp = float(d['open'][xi])
                    shares = (per_stock / bp) * (1 - COST)
                    cost = shares * bp
                    cash -= cost
                    sym = daily[tid]['symbol']
                    positions[tid] = dict(shares=shares, entry_price=bp, symbol=sym, peak=bp, ratchet=0.0)
                    trade_log.append((exec_date, sym, 'BUY', shares, bp, None))
                    if args.detail:
                        print(f'  {exec_date} BUY  {sym} {shares:.2f} @ ${bp:.2f}')

            # MTM at exec_date close — fall back to last available close.
            # Guard-enabled runs (and explicit --daily-mark) also mark every
            # trading day between rebalances so a path-based stop can fire
            # intraweek; without either flag the historical step-frequency
            # equity curve is preserved exactly.
            if daily_marks:
                # exec_date through the session before the next signal date;
                # the next iteration marks that signal date with the guard.
                for gj in range(ri + 1, min(ri + step, len(all_dates))):
                    _mark_and_guard(all_dates[gj])
            else:
                pf_val = cash
                for tid, pos in positions.items():
                    d = daily.get(tid)
                    if d is None:
                        continue
                    xi = _last_idx_before(daily_idx[tid], daily[tid]['dates'], exec_date)
                    if xi is not None:
                        pf_val += pos['shares'] * float(d['close'][xi])
                equity_curve.append(pf_val)
                equity_dates.append(exec_date)
                pos_counts.append(len(positions))

        # --- Results ---
        if not equity_curve:
            print('No trades.')
            return
        total_ret = (equity_curve[-1] - CAPITAL) / CAPITAL
        eq_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(eq_arr)
        dd = np.max((peak - eq_arr) / peak)

        # Drawdown episodes (peak -> trough -> recovery)
        drawdowns = []
        peak_i = 0
        peak_val = eq_arr[0]
        trough_i = 0
        for i in range(1, len(eq_arr)):
            if eq_arr[i] > peak_val:
                if trough_i > peak_i:
                    depth = (eq_arr[trough_i] - peak_val) / peak_val
                    drawdowns.append((depth, equity_dates[peak_i], equity_dates[trough_i],
                                      equity_dates[i], trough_i - peak_i + 1))
                peak_i = i
                peak_val = eq_arr[i]
                trough_i = i
            elif eq_arr[i] < eq_arr[trough_i]:
                trough_i = i
        if trough_i > peak_i:
            depth = (eq_arr[trough_i] - peak_val) / peak_val
            drawdowns.append((depth, equity_dates[peak_i], equity_dates[trough_i],
                              None, len(eq_arr) - peak_i))
        drawdowns.sort(key=lambda x: x[0])

        all_sells = [t for t in trade_log if t[2] in ('SELL', 'SELL-STOP', 'SELL-H-EMA', 'SELL-RATC', 'SELL-D-EMA', 'SELL-GATE', 'SELL-GUARD')]
        stop_sells = [t for t in trade_log if t[2] == 'SELL-STOP']
        hem_sells = [t for t in trade_log if t[2] == 'SELL-H-EMA']
        ratc_sells = [t for t in trade_log if t[2] == 'SELL-RATC']
        dem_sells = [t for t in trade_log if t[2] == 'SELL-D-EMA']
        gate_sells = [t for t in trade_log if t[2] == 'SELL-GATE']
        guard_sells = [t for t in trade_log if t[2] == 'SELL-GUARD']
        sweep_sells = [t for t in trade_log if t[2] == 'SELL-SWEEP']
        all_buys = [t for t in trade_log if t[2] == 'BUY']
        winners = [t for t in all_sells if t[5] is not None and t[5] > 0]
        losers = [t for t in all_sells if t[5] is not None and t[5] <= 0]
        sells = len(all_sells)
        buys = len(all_buys)
        wr = len(winners) / sells * 100 if sells else 0
        lr = len(losers) / sells * 100 if sells else 0
        avg_win = np.mean([t[5] for t in winners]) * 100 if winners else 0
        avg_loss = np.mean([t[5] for t in losers]) * 100 if losers else 0

        print(f'\n{"="*80}')
        print(f'  TOP-{args.top_n} MULTI-TF BACKTEST  ({period_label})')
        if args.score == 'emasma':
            print(f'  Score: weekly EMA10>SMA40 gap (strategy signal)'
                  + (' + daily EMA10>SMA40 filter' if args.emasma_daily_bull else '')
                  + (' REVERSED (anti-overextension: smallest gap first)' if args.emasma_gap_reverse else '')
                  + (' 200MA-gated (close>200MA, proximity-ranked)' if args.emasma_close_200 else '')
                  + (' FRESHNESS-ranked (days since weekly cross)' if args.emasma_fresh else ''))
        elif args.score == 'near':
            print(f'  Score: proximity (3 - gap_w/{args.near_gap_k:g}) + (3 - atr_dist/{args.near_atr_k:g}) + freshness')
        else:
            print(f'  Score: gap_w/20 + atr_dist/1.5 + freshness')
        if args.ppo_filter:
            print(f'  Hybrid: + WeeklyAndDailyPPO>0 entry filter')
        if args.hourly_ema_gate:
            print(f'  Entry:  + hourly EMA10>SMA40 required (all 3 timeframes bullish)')
        if args.above != 'none':
            ab = 'close > EMA10 & SMA40 (daily+weekly)' if args.above == 'ema-sma' \
                 else 'close > EMA10 & SMA40 (daily only)' if args.above == 'ema-sma-daily' \
                 else 'close > daily ATR stop' if args.above == 'atr' \
                 else 'close > EMA10 & SMA40 (daily+weekly) AND > daily ATR stop'
            print(f'  Entry:  + {ab}')
        print(f'  Exit:   {args.exit}' + (' (sell when hourly EMA10<SMA40)' if args.exit == 'hourly-ema' else ' (sell when close < highest-close - 2xATR)' if args.exit == 'ratchet-atr' else ' (sell when daily EMA10<SMA40)' if args.exit == 'daily-ema' else ''))
        if args.exit == 'ratchet-atr':
            print(f'  Exit:   ratchet ATR source: {args.ratchet_atr_src}')
        if args.market_gate != 'none':
            print(f'  Market:  {args.market_gate_freq} EMA{args.market_gate_span} '
                  f'{args.market_gate} ({args.market_gate_mode})')
        if guard_enabled:
            sweep_when = 'rebalance' if args.sweep_at_rebalance else 'every new high'
            reentry = 'hold peak' if args.guard_hold_peak else 'reset HWM'
            stop_when = 'weekly close' if args.guard_weekly_stop else 'daily close'
            print(f'  Guard:   HWM stop {args.hwm_stop:g}% ({stop_when}) / '
                  f'sweep {args.profit_sweep:g}% ({sweep_when}) / '
                  f'cooldown {args.guard_cooldown} sessions / {reentry}')
        print(f'  Period: {all_dates[0]} to {all_dates[-1]}')
        print(f'{"="*80}')
        print(f'  Initial: ${CAPITAL:,.0f}')
        print(f'  Final:   ${equity_curve[-1]:,.0f}')
        print(f'  Return:  {total_ret*100:+.2f}%')
        print(f'  Max DD:  {dd*100:.1f}%')
        if guard_state is not None:
            print(f'  Reserve: ${reserve:,.0f}  (swept ${guard_state.swept_total:,.0f}, '
                  f'{len([e for e in guard_events if e[1] == "SWEEP"])} sweeps, '
                  f'{guard_state.stop_count} stops)')
            print(f'  Active:  ${equity_curve[-1] - reserve:,.0f}')
        exit_desc = (f'{len(stop_sells)} stop-loss, {len(hem_sells)} hourly-ema, '
                     f'{len(ratc_sells)} ratchet-atr, {len(dem_sells)} daily-ema, '
                     f'{len(gate_sells)} gate, {len(guard_sells)} guard, '
                     f'{len(sweep_sells)} sweep')
        print(f'  Trades:  {sells} sells ({exit_desc}) / {buys} buys')
        print(f'  Win:     {len(winners)} ({wr:.0f}%)  avg +{avg_win:+.2f}%')
        print(f'  Loss:    {len(losers)} ({lr:.0f}%)  avg {avg_loss:+.2f}%')
        print(f'  Hold:    {len(all_dates) // max(1, sells) * step:.0f} days')

        cache = _load_baseline_cache()
        cache[sig] = {
            'cached_at': str(datetime.now().date()),
            'window': [str(all_dates[0]), str(all_dates[-1])],
            'total_ret_pct': total_ret * 100,
            'max_dd_pct': dd * 100,
            'win_rate_pct': wr,
            'sells': sells,
            'buys': buys,
        }
        if args.cache_baseline:
            _save_baseline_cache(cache)
            print(f'  Baseline saved to cache ({sig[:40]}...)')
        else:
            print()
            _print_baseline(args, sig, all_dates)

        # Monthly
        monthly = {}
        for i, v in enumerate(equity_curve):
            if i == 0:
                continue
            if daily_marks:
                d = equity_dates[i]
            else:
                di = min(i * step if i * step < len(all_dates) else len(all_dates) - 1, len(all_dates) - 1)
                d = all_dates[di]
            mk = f'{d.year}-{d.month:02d}'
            monthly.setdefault(mk, []).append(v)

        if monthly:
            print()
            prev = CAPITAL
            for mk in sorted(monthly):
                vals = monthly[mk]
                mret = (vals[-1] - prev) / prev
                print(f'  {mk}: {mret*100:+7.2f}%  (${prev:,.0f} -> ${vals[-1]:,.0f})')
                prev = vals[-1]

        # Exposure
        n = len(pos_counts)
        cash_days = sum(1 for c in pos_counts if c == 0)
        print(f'\n  Exposure: {n - cash_days}/{n} days invested ({100*(n - cash_days)/max(1, n):.0f}%) | '
              f'{cash_days} days 100% cash | avg {np.mean(pos_counts):.1f} positions | '
              f'{sum(1 for c in pos_counts if c < 10)} days with <10 positions')

        # Contiguous cash stretches
        stretches = []
        s = None
        for i, c in enumerate(pos_counts):
            if c == 0 and s is None:
                s = i
            elif c > 0 and s is not None:
                stretches.append((s, i - 1))
                s = None
        if s is not None:
            stretches.append((s, len(pos_counts) - 1))
        if stretches:
            print(f'  Cash stretches: {len(stretches)}')
            for s, e in stretches[:10]:
                dur = e - s + 1
                print(f'    {equity_dates[s]} -> {equity_dates[e]}  ({dur} days)')

        # Top 5 drawdowns
        print(f'\n  TOP-5 DRAWDOWNS:')
        for i, (depth, pd_, td_, rd, dur) in enumerate(drawdowns[:5], 1):
            rec = f'-> {rd}' if rd else '-> (open)'
            print(f'    {i}. {depth*100:6.1f}%  {pd_} -> {td_} {rec}  ({dur} trading days)')

        # Deepest-drawdown window exposure
        if drawdowns:
            _, pd_, td_, rd, _ = drawdowns[0]
            idx = [i for i, d in enumerate(equity_dates) if pd_ <= d <= (td_ or equity_dates[-1])]
            if idx:
                sub = [pos_counts[i] for i in idx]
                print(f'  Crash window ({pd_} -> {td_}): avg {np.mean(sub):.1f} positions, '
                      f'{sum(1 for c in sub if c < 10)}/{len(sub)} days <10, '
                      f'{sum(1 for c in sub if c == 0)} days 100% cash')

        # --- Top trades ---
        if args.top_trades > 0 and trade_log:
            buys_map = {}
            completed = []
            for t in trade_log:
                tdate, tsym, taction, tshares, tprice, tret = t
                if taction == 'BUY':
                    buys_map[tsym] = {'date': tdate, 'price': tprice, 'shares': tshares}
                elif taction in ('SELL', 'SELL-STOP'):
                    if tsym in buys_map:
                        b = buys_map.pop(tsym)
                        pnl_pct = (tprice - b['price']) / b['price'] * 100
                        dollar_pnl = (tprice - b['price']) * b['shares']
                        completed.append({
                            'symbol': tsym,
                            'entry_date': b['date'],
                            'entry_price': b['price'],
                            'exit_date': tdate,
                            'exit_price': tprice,
                            'return_pct': pnl_pct,
                            'dollar_pnl': dollar_pnl,
                            'exit_type': taction
                        })

            if completed:
                completed.sort(key=lambda x: x['return_pct'], reverse=True)
                n = min(args.top_trades, len(completed))
                hdr = f'  {"#":<4} {"Ticker":<7} {"Entry Date":<13} {"Entry $":<11} {"Exit Date":<13} {"Exit $":<11} {"Return":>9} {"P&L $":>12} {"Exit":>9}'
                sep = '-' * 92

                print(f'\n  TOP {n} WINNING TRADES')
                print(sep)
                print(hdr)
                print(sep)
                for i, t in enumerate(completed[:n], 1):
                    ed = str(t["entry_date"]) if not hasattr(t["entry_date"], 'date') else str(t["entry_date"].date())
                    xd = str(t["exit_date"]) if not hasattr(t["exit_date"], 'date') else str(t["exit_date"].date())
                    print(f'  {i:<4} {t["symbol"]:<7} {ed:<13} ${t["entry_price"]:<10.2f} {xd:<13} ${t["exit_price"]:<10.2f} {t["return_pct"]:>+8.2f}% ${t["dollar_pnl"]:>+11,.2f} {t["exit_type"]:>9}')

                print(f'\n  BOTTOM {n} LOSING TRADES')
                print(sep)
                print(hdr)
                print(sep)
                for i, t in enumerate(completed[-n:], 1):
                    ed = str(t["entry_date"]) if not hasattr(t["entry_date"], 'date') else str(t["entry_date"].date())
                    xd = str(t["exit_date"]) if not hasattr(t["exit_date"], 'date') else str(t["exit_date"].date())
                    print(f'  {i:<4} {t["symbol"]:<7} {ed:<13} ${t["entry_price"]:<10.2f} {xd:<13} ${t["exit_price"]:<10.2f} {t["return_pct"]:>+8.2f}% ${t["dollar_pnl"]:>+11,.2f} {t["exit_type"]:>9}')

                wins = [t for t in completed if t['return_pct'] > 0]
                losses = [t for t in completed if t['return_pct'] <= 0]
                print(f'\n  Total: {len(completed)} trades  |  Winners: {len(wins)} ({len(wins)/len(completed)*100:.0f}%)  |  Losers: {len(losses)} ({len(losses)/len(completed)*100:.0f}%)')
                if wins:
                    print(f'  Avg win:  +{np.mean([t["return_pct"] for t in wins]):.2f}%  (${np.mean([t["dollar_pnl"] for t in wins]):+,.0f})')
                if losses:
                    print(f'  Avg loss: {np.mean([t["return_pct"] for t in losses]):.2f}%  (${np.mean([t["dollar_pnl"] for t in losses]):+,.0f})')
        print()

        return {
            'equity': eq_arr,
            'equity_dates': equity_dates,
            'trades': trade_log,
            'all_dates': all_dates,
            'positions': positions,
            'pos_counts': pos_counts,
            'args': args,
            'CAPITAL': CAPITAL,
            'COST': COST,
            'reserve': reserve,
            'guard_state': guard_state,
            'guard_events': guard_events,
        }

    finally:
        conn.close()


def main():
    backtest()


if __name__ == '__main__':
    main()
