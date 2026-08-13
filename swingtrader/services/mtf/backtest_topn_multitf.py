#!/usr/bin/env python3
"""Top-N rotation backtest using Multi-TF score (weekly+daily bullish, gap_w, atr_dist, freshness).

Score = min(gap_w/20, 3) + min(atr_dist/1.5, 3) + max(0, 2 - days_since_weekly/60)
Rebalance: sell non-top-N, buy new entrants at next-day open, equal weight.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, date as dt_date

import config
import db as db_module

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


def load_bars(conn, table, date_col, is_etf=False):
    """Load OHLC data from a table for all tickers."""
    with conn.cursor() as cur:
        cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=%s ORDER BY symbol', (is_etf,))
        tickers = cur.fetchall()
    print(f'  Loading {table} ({len(tickers)} tickers)...')

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
                f'SELECT {date_col}, close FROM {table} WHERE ticker_id = %s ORDER BY {date_col} ASC',
                (tid,))
            rows = cur.fetchall()
            dates = [r[0] for r in rows]
            closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        else:
            cur.execute(
                f'SELECT {date_col}, open, close, atr_stop FROM {table} WHERE ticker_id = %s ORDER BY {date_col} ASC',
                (tid,))
            rows = cur.fetchall()
            dates = [r[0] for r in rows]
            opens = np.array([float(r[1]) for r in rows], dtype=np.float64)
            closes = np.array([float(r[2]) for r in rows], dtype=np.float64)
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
        data[tid] = d

    return tickers, data


def main():
    parser = argparse.ArgumentParser(description='Top-N Multi-TF rotation backtest')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--rebalance', choices=['daily', 'weekly'], default='daily')
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--etf', action='store_true', help='Run on ETF universe (is_etf=true)')
    parser.add_argument('--score', choices=['mtf', 'early', 'emasma'], default='mtf',
                        help='Sorting score: mtf=gap+atr+fresh, early=signals+fresh-gap, '
                             'emasma=weekly EMA10>SMA40 gap')
    parser.add_argument('--min-score', type=float, default=None,
                        help='Minimum MTF score to consider (e.g. 5.0 = only stocks with score >= 5)')
    parser.add_argument('--infancy', action='store_true',
                        help='Only consider tickers with days_since_weekly_cross < 60')
    parser.add_argument('--stop-loss', type=float, default=None,
                        help='Stop-loss exit: sell if position drops >N%% from entry (e.g. 5.0)')
    parser.add_argument('--top-trades', type=int, default=0,
                        help='Print top N winning/losing trades by return %%')
    parser.add_argument('--ppo-filter', action='store_true',
                        help='Hybrid: require TOS WeeklyAndDailyPPO > 0 as an extra entry filter')
    parser.add_argument('--hourly-ema-gate', action='store_true',
                        help='Entry requires EMA10>SMA40 on hourly too (all 3 timeframes bullish)')
    parser.add_argument('--exit', choices=['rebalance', 'hourly-ema', 'ratchet-atr', 'daily-ema'], default='rebalance',
                        help='Exit rule: rebalance (sell out-of-top-N only), '
                             'hourly-ema (also sell when hourly EMA10<SMA40), '
                             'ratchet-atr (also sell when close < highest-close-since-entry - 2xATR), '
                             'daily-ema (also sell when daily EMA10<SMA40)')
    parser.add_argument('--start', default=None,
                        help='Restrict backtest to dates >= YYYY-MM-DD (fair comparison window)')
    args = parser.parse_args()

    db_module.init_db()
    conn = db_module.get_conn()
    try:
        is_etf = args.etf
        if is_etf:
            label = 'ETF'
        else:
            label = 'Stock'
        print(f'\n  Mode: {label} universe\n')
        # Load three timeframes
        _, weekly = load_bars(conn, 'tbl_scanner_tickers', 'date', is_etf)
        _, daily = load_bars(conn, 'tbl_scanner_tickers_daily', 'date', is_etf)
        _, hourly = load_bars(conn, 'tbl_scanner_tickers_1hour', None, is_etf)

        # Only keep tickers present in all datasets
        common = set(weekly) & set(daily) & set(hourly)
        print(f'  Tickers with all 3 timeframes: {len(common)}')
        for tid in list(weekly.keys()):
            if tid not in common:
                del weekly[tid]
        for tid in list(daily.keys()):
            if tid not in common:
                del daily[tid]
        for tid in list(hourly.keys()):
            if tid not in common:
                del hourly[tid]

        # Pre-compute weekly and daily EMA/SMA
        for tid in weekly:
            wc = pd.Series(weekly[tid]['close'])
            weekly[tid]['ema'] = wc.ewm(span=EMA, adjust=False).mean().to_numpy()
            weekly[tid]['sma'] = wc.rolling(window=SMA).mean().to_numpy()
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
        print(f'  Universe: {len(common)} tickers, warmup from {all_dates[0]}')

        step = 5 if args.rebalance == 'weekly' else 1
        period_label = f'{args.rebalance} (every {step} trading day{"s" if step > 1 else ""})'
        print(f'  Running: top {args.top_n}, rebalance {period_label}...\n')

        # Portfolio state
        positions = {}
        cash = CAPITAL
        equity_curve = []
        equity_dates = []
        pos_counts = []
        trade_log = []  # (date, symbol, side, shares, price, ret)

        for ri in range(0, len(all_dates), step):
            sig_date = all_dates[ri]

            # Compute Multi-TF scores for all tickers
            candidates = []
            for tid in common:
                di = daily_idx[tid].get(sig_date)
                wi = weekly_idx[tid].get(sig_date)
                hi = hourly_idx[tid].get(sig_date)

                if args.score == 'emasma':
                    # Strategy signal: weekly EMA10 > SMA40 (long), flat otherwise.
                    # No daily/hourly/ATR filters — pure weekly strategy under
                    # the same top-N rotation mechanics.
                    if wi is None or wi < WARMUP:
                        continue
                    we = weekly[tid]['ema'][wi]
                    ws = weekly[tid]['sma'][wi]
                    wc = weekly[tid]['close'][wi]
                    if np.isnan(we) or np.isnan(ws) or np.isnan(wc):
                        continue
                    if we <= ws:
                        continue
                    gap_w = (wc - ws) / ws * 100
                    emasma_score = round(min(gap_w / 5, 5), 2)
                    candidates.append((tid, emasma_score))
                    continue

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
                hc = hourly[tid]['close'][hi]
                ha = hourly[tid]['atr_stop'][hi]

                # NaN checks
                if any(np.isnan(x) for x in (wc, we, ws, dc, de, ds, hc, ha)):
                    continue
                if we <= ws or de <= ds:
                    continue  # weekly or daily not bullish
                if hc <= ha or hc <= 0:
                    continue

                if args.hourly_ema_gate:
                    he = hourly[tid]['h_ema'][hi]
                    hs = hourly[tid]['h_sma'][hi]
                    if np.isnan(he) or np.isnan(hs) or he <= hs:
                        continue  # hourly not bullish

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

                # Early score: signal count + fresh_pts - gap_pts
                # Signal count: daily_signal (days_since<60) + emac (daily EMA>SMA) + chand (close>atr_stop)
                # EMAC and CHAND are already required by the filter, so base is 2
                signal_cnt = 2 + (1 if days_since < 60 else 0)
                early_score = round(signal_cnt + fresh_pts - gap_pts, 1)

                decision_score = early_score if args.score == 'early' else mtf_score
                if args.min_score is not None and mtf_score < args.min_score:
                    continue
                if args.infancy and days_since >= 60:
                    continue
                candidates.append((tid, decision_score))

            if not candidates:
                # MTM — fall back to last available close if sig_date missing
                pf_val = cash
                for tid in list(positions):
                    p = _last_idx_before(daily_idx[tid], daily[tid]['dates'], sig_date)
                    if p is not None:
                        pf_val += positions[tid]['shares'] * float(daily[tid]['close'][p])
                equity_curve.append(pf_val)
                equity_dates.append(all_dates[min(ri + 1, len(all_dates) - 1)])
                pos_counts.append(len(positions))
                continue

            # Sort by score DESC
            candidates.sort(key=lambda x: -x[1])
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

            # SELL: liquidate positions not in selected, or hourly-EMA / ratchet-ATR exit
            for tid in list(positions):
                reason = None
                if tid not in selected:
                    reason = 'SELL'
                elif args.exit == 'hourly-ema':
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
                    hp = hourly.get(tid)
                    if d is not None and hp is not None:
                        si = _last_idx_before(daily_idx[tid], d['dates'], sig_date)
                        hxi = _last_idx_before(hourly_idx[tid], hp['dates'], sig_date)
                        if si is not None and hxi is not None and hp['atr_stop'][hxi]:
                            close_t = float(d['close'][si])
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
                del positions[tid]

            # BUY: add new selected positions
            to_buy = [tid for tid in selected if tid not in positions]
            if to_buy:
                per_stock = cash / len(to_buy)
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

            # MTM at exec_date close — fall back to last available close
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

        all_sells = [t for t in trade_log if t[2] in ('SELL', 'SELL-STOP', 'SELL-H-EMA', 'SELL-RATC', 'SELL-D-EMA')]
        stop_sells = [t for t in trade_log if t[2] == 'SELL-STOP']
        hem_sells = [t for t in trade_log if t[2] == 'SELL-H-EMA']
        ratc_sells = [t for t in trade_log if t[2] == 'SELL-RATC']
        dem_sells = [t for t in trade_log if t[2] == 'SELL-D-EMA']
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
            print(f'  Score: weekly EMA10>SMA40 gap (strategy signal)')
        else:
            print(f'  Score: gap_w/20 + atr_dist/1.5 + freshness')
        if args.ppo_filter:
            print(f'  Hybrid: + WeeklyAndDailyPPO>0 entry filter')
        if args.hourly_ema_gate:
            print(f'  Entry:  + hourly EMA10>SMA40 required (all 3 timeframes bullish)')
        print(f'  Exit:   {args.exit}' + (' (sell when hourly EMA10<SMA40)' if args.exit == 'hourly-ema' else ' (sell when close < highest-close - 2xATR)' if args.exit == 'ratchet-atr' else ' (sell when daily EMA10<SMA40)' if args.exit == 'daily-ema' else ''))
        print(f'  Period: {all_dates[0]} to {all_dates[-1]}')
        print(f'{"="*80}')
        print(f'  Initial: ${CAPITAL:,.0f}')
        print(f'  Final:   ${equity_curve[-1]:,.0f}')
        print(f'  Return:  {total_ret*100:+.2f}%')
        print(f'  Max DD:  {dd*100:.1f}%')
        exit_desc = f'{len(stop_sells)} stop-loss, {len(hem_sells)} hourly-ema, {len(ratc_sells)} ratchet-atr, {len(dem_sells)} daily-ema'
        print(f'  Trades:  {sells} sells ({exit_desc}) / {buys} buys')
        print(f'  Win:     {len(winners)} ({wr:.0f}%)  avg +{avg_win:+.2f}%')
        print(f'  Loss:    {len(losers)} ({lr:.0f}%)  avg {avg_loss:+.2f}%')
        print(f'  Hold:    {len(all_dates) // max(1, sells) * step:.0f} days')

        # Monthly
        monthly = {}
        for i, v in enumerate(equity_curve):
            if i == 0:
                continue
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

    finally:
        conn.close()


if __name__ == '__main__':
    main()
