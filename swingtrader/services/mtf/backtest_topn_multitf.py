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
                f"SELECT date::date AS bar_date, close, atr_stop FROM {table} "
                f"WHERE ticker_id = %s AND date >= '2023-06-30' ORDER BY date ASC",
                (tid,))
            rows = cur.fetchall()
            seen = {}
            for r in rows:
                seen[r[0]] = (r[0], float(r[1]) if r[1] else 0.0, float(r[2]) if r[2] else 0.0)
            sorted_rows = sorted(seen.values(), key=lambda x: x[0])
            dates = [r[0] for r in sorted_rows]
            closes = np.array([r[1] for r in sorted_rows], dtype=np.float64)
            atr_stops = np.array([r[2] for r in sorted_rows], dtype=np.float64)
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
        cur.close()

        if len(dates) < WARMUP:
            continue
        d = dict(symbol=sym, dates=dates, close=closes)
        if table == 'tbl_scanner_tickers_1hour':
            d['atr_stop'] = atr_stops
        elif table == 'tbl_scanner_tickers_daily':
            d['open'] = opens
        data[tid] = d

    return tickers, data


def main():
    parser = argparse.ArgumentParser(description='Top-N Multi-TF rotation backtest')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--rebalance', choices=['daily', 'weekly'], default='daily')
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--etf', action='store_true', help='Run on ETF universe (is_etf=true)')
    parser.add_argument('--score', choices=['mtf', 'early'], default='mtf',
                        help='Sorting score: mtf=gap+atr+fresh, early=signals+fresh-gap')
    parser.add_argument('--min-score', type=float, default=None,
                        help='Minimum MTF score to consider (e.g. 5.0 = only stocks with score >= 5)')
    parser.add_argument('--infancy', action='store_true',
                        help='Only consider tickers with days_since_weekly_cross < 60')
    parser.add_argument('--stop-loss', type=float, default=None,
                        help='Stop-loss exit: sell if position drops >N%% from entry (e.g. 5.0)')
    parser.add_argument('--top-trades', type=int, default=0,
                        help='Print top N winning/losing trades by return %%')
    args = parser.parse_args()

    db_module.init_db()
    conn = db_module.get_conn()
    try:
        is_etf = args.etf
        label = 'ETF' if is_etf else 'Stock'
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
        print(f'  Universe: {len(common)} tickers, warmup from {all_dates[0]}')

        step = 5 if args.rebalance == 'weekly' else 1
        period_label = f'{args.rebalance} (every {step} trading day{"s" if step > 1 else ""})'
        print(f'  Running: top {args.top_n}, rebalance {period_label}...\n')

        # Portfolio state
        positions = {}
        cash = CAPITAL
        equity_curve = []
        trade_log = []  # (date, symbol, side, shares, price, ret)

        for ri in range(0, len(all_dates), step):
            sig_date = all_dates[ri]

            # Compute Multi-TF scores for all tickers
            candidates = []
            for tid in common:
                di = daily_idx[tid].get(sig_date)
                wi = weekly_idx[tid].get(sig_date)
                hi = hourly_idx[tid].get(sig_date)
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

            # SELL: liquidate positions not in selected
            for tid in list(positions):
                if tid not in selected:
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
                    trade_log.append((exec_date, pos['symbol'], 'SELL', pos['shares'], sp, ret))
                    if args.detail:
                        print(f'  {exec_date} SELL {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f}')
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
                    positions[tid] = dict(shares=shares, entry_price=bp, symbol=sym)
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

        # --- Results ---
        if not equity_curve:
            print('No trades.')
            return
        total_ret = (equity_curve[-1] - CAPITAL) / CAPITAL
        eq_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(eq_arr)
        dd = np.max((peak - eq_arr) / peak)

        all_sells = [t for t in trade_log if t[2] in ('SELL', 'SELL-STOP')]
        stop_sells = [t for t in trade_log if t[2] == 'SELL-STOP']
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
        print(f'  Score: gap_w/20 + atr_dist/1.5 + freshness')
        print(f'  Period: {all_dates[0]} to {all_dates[-1]}')
        print(f'{"="*80}')
        print(f'  Initial: ${CAPITAL:,.0f}')
        print(f'  Final:   ${equity_curve[-1]:,.0f}')
        print(f'  Return:  {total_ret*100:+.2f}%')
        print(f'  Max DD:  {dd*100:.1f}%')
        print(f'  Trades:  {sells} sells ({len(stop_sells)} stop-loss) / {buys} buys')
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
