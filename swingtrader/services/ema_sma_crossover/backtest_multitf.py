#!/usr/bin/env python3
"""Multi-timeframe EMA(10)/SMA(40) backtest: weekly → daily → 1-hour entry filter.

Entry (all modes):
  - weekly EMA(10) > SMA(40) AND daily EMA(10) > SMA(40)
  - AND 1-hour EMA(10) crosses above SMA(40) (fresh crossover)

Exit modes:
  --exit ema   (default): 1-hour EMA(10) crosses below SMA(40)
  --exit atr:              trailing stop at highest_high - ATR * multiplier
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from datetime import datetime

import config
import db as db_module

EMA = config.EMA_PERIOD
SMA = config.SMA_PERIOD
COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL

SAMPLE_SIZE = 25
WARMUP = SMA + 1


def compute_ema_sma(close, ema_period=EMA, sma_period=SMA):
    series = pd.Series(close)
    ema = series.ewm(span=ema_period, adjust=False).mean().values
    sma = series.rolling(window=sma_period).mean().values
    return ema, sma


def compute_atr(high, low, close, period=14):
    tr = np.zeros_like(close)
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    return atr


def load_stock_bars(conn, ticker_id, table, date_field):
    with conn.cursor() as cur:
        cur.execute(
            f'SELECT {date_field}, open, high, low, close FROM {table} '
            f'WHERE ticker_id = %s ORDER BY {date_field} ASC',
            (ticker_id,))
        return cur.fetchall()


def backtest(ticker_id, weekly_rows, daily_rows, hourly_rows,
             exit_mode='ema', atr_period=14, atr_mult=2.0):
    if len(hourly_rows) < WARMUP + 10:
        return None, None

    weekly_close = np.array([float(r[4]) for r in weekly_rows], dtype=np.float64)
    daily_close = np.array([float(r[4]) for r in daily_rows], dtype=np.float64)

    hourly_high = np.array([float(r[2]) for r in hourly_rows], dtype=np.float64)
    hourly_low = np.array([float(r[3]) for r in hourly_rows], dtype=np.float64)
    hourly_close = np.array([float(r[4]) for r in hourly_rows], dtype=np.float64)
    hourly_open = np.array([float(r[1]) for r in hourly_rows], dtype=np.float64)

    weekly_ema, weekly_sma = compute_ema_sma(weekly_close)
    daily_ema, daily_sma = compute_ema_sma(daily_close)
    hourly_ema, hourly_sma = compute_ema_sma(hourly_close)

    if exit_mode == 'atr':
        hourly_atr = compute_atr(hourly_high, hourly_low, hourly_close, atr_period)
    else:
        hourly_atr = None

    wi = 0
    di = 0
    prev_di = 0
    trades = []
    equity = CAPITAL
    in_pos = False
    entry_price = 0.0
    entry_hi = 0
    highest_since_entry = 0.0
    daily_exit_triggered = False

    hourly_dates = [r[0] for r in hourly_rows]

    for hi in range(1, len(hourly_rows)):
        h_dt = hourly_dates[hi]
        h_date = h_dt.date() if hasattr(h_dt, 'date') else h_dt

        while wi + 1 < len(weekly_rows) and weekly_rows[wi + 1][0] <= h_date:
            wi += 1
        prev_di = di
        while di + 1 < len(daily_rows) and daily_rows[di + 1][0] <= h_date:
            di += 1

        w_nan = np.isnan(weekly_ema[wi]) or np.isnan(weekly_sma[wi])
        d_nan = np.isnan(daily_ema[di]) or np.isnan(daily_sma[di])
        h_nan = (np.isnan(hourly_ema[hi]) or np.isnan(hourly_sma[hi])
                 or np.isnan(hourly_ema[hi - 1]) or np.isnan(hourly_sma[hi - 1]))
        if exit_mode == 'atr':
            h_nan = h_nan or np.isnan(hourly_atr[hi])

        if w_nan or d_nan or h_nan:
            continue

        weekly_bullish = weekly_ema[wi] > weekly_sma[wi]
        daily_bullish = daily_ema[di] > daily_sma[di]

        if not in_pos:
            hourly_cross_above = (
                hourly_ema[hi] > hourly_sma[hi]
                and hourly_ema[hi - 1] <= hourly_sma[hi - 1]
            )
            if weekly_bullish and daily_bullish and hourly_cross_above:
                if hi + 1 < len(hourly_rows):
                    entry_price = hourly_open[hi + 1]
                    entry_hi = hi
                    highest_since_entry = entry_price
                    daily_exit_triggered = False
                    in_pos = True
        else:
            highest_since_entry = max(highest_since_entry, float(hourly_high[hi]))
            should_exit = False

            if exit_mode == 'ema':
                should_exit = (
                    hourly_ema[hi] < hourly_sma[hi]
                    and hourly_ema[hi - 1] >= hourly_sma[hi - 1]
                )
            elif exit_mode == 'daily-ema':
                if di > prev_di and not daily_exit_triggered:
                    if (not np.isnan(daily_ema[di]) and not np.isnan(daily_sma[di])
                            and not np.isnan(daily_ema[di - 1]) and not np.isnan(daily_sma[di - 1])):
                        daily_cross_below = (
                            daily_ema[di] < daily_sma[di]
                            and daily_ema[di - 1] >= daily_sma[di - 1]
                        )
                        if daily_cross_below:
                            should_exit = True
                            daily_exit_triggered = True
            else:
                stop = highest_since_entry - hourly_atr[hi] * atr_mult
                should_exit = float(hourly_close[hi]) < stop

            if should_exit:
                if hi + 1 < len(hourly_rows):
                    exit_price = hourly_open[hi + 1]
                    ret = (exit_price - entry_price) / entry_price - COST
                    equity *= (1 + ret)
                    trades.append({
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'entry_at': hourly_dates[entry_hi + 1],
                        'exit_at': hourly_dates[hi + 1],
                        'return': ret,
                    })
                    in_pos = False

    if in_pos:
        exit_price = float(hourly_rows[-1][4])
        ret = (exit_price - entry_price) / entry_price - COST
        equity *= (1 + ret)
        trades.append({
            'entry_price': entry_price,
            'exit_price': exit_price,
            'entry_at': hourly_dates[entry_hi + 1],
            'exit_at': hourly_dates[-1],
            'return': ret,
            'open': True,
        })

    if not trades:
        return None, None

    trades_df = pd.DataFrame(trades)
    wins = (trades_df['return'] > 0).sum()
    total_ret = (equity - CAPITAL) / CAPITAL

    eq_curve = [CAPITAL]
    for t in trades:
        eq_curve.append(eq_curve[-1] * (1 + t['return']))
    eq_arr = np.array(eq_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = np.max((peak - eq_arr) / peak)

    metrics = {
        'total_trades': len(trades_df),
        'winning_trades': int(wins),
        'win_rate': wins / len(trades_df),
        'avg_return': float(trades_df['return'].mean()),
        'total_return': float(total_ret),
        'max_drawdown': float(dd) if not np.isnan(dd) else 0.0,
    }
    return trades, metrics


def get_bh_return(daily_rows, start_date, end_date):
    closes = [float(r[4]) for r in daily_rows if start_date <= r[0] <= end_date]
    if len(closes) < 2:
        return None
    return (closes[-1] - closes[0]) / closes[0]


def load_ticker_bars_batched(conn, ticker_ids=None):
    ts_start = datetime(2023, 6, 30)

    if ticker_ids:
        placeholders = ','.join(['%s'] * len(ticker_ids))
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT id, symbol FROM tbl_stock_tickers WHERE id IN ({placeholders}) ORDER BY symbol',
                ticker_ids)
            tickers = cur.fetchall()
    else:
        with conn.cursor() as cur:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true ORDER BY symbol')
            tickers = cur.fetchall()

    print(f'Loading data for {len(tickers)} tickers...')

    weekly = {}
    daily = {}
    hourly = {}
    count = 0

    for tid, sym in tickers:
        w = load_stock_bars(conn, tid, 'tbl_scanner_tickers', 'date')
        d = load_stock_bars(conn, tid, 'tbl_scanner_tickers_daily', 'date')
        h = [r for r in load_stock_bars(conn, tid, 'tbl_scanner_tickers_1hour', 'date')
             if r[0] >= ts_start]

        if len(w) < WARMUP or len(d) < WARMUP or len(h) < WARMUP + 10:
            continue

        weekly[tid] = w
        daily[tid] = d
        hourly[tid] = h
        count += 1

    print(f'  {count} tickers have sufficient data across all timeframes')
    return tickers, weekly, daily, hourly


def print_trade_log(sym, trades, bh_ret, start_close, end_close):
    total_moves = end_close - start_close
    first_entry = min(t['entry_at'] for t in trades)
    print(f'\n  === {sym} ===')
    print(f'  Period: {first_entry.date()} to {trades[-1]["exit_at"].date()}')
    print(f'  BH: {bh_ret*100:+.2f}%  (${start_close:.2f} → ${end_close:.2f})')
    print(f'  Trades: {len(trades)}  ({sum(1 for t in trades if t["return"]>0)}W / {sum(1 for t in trades if t["return"]<=0)}L)')
    strat_ret = (np.prod([1 + t['return'] for t in trades]) - 1) * 100
    print(f'  Strategy: {strat_ret:+.2f}%')
    print()
    print(f'  {"#":<4} {"Entry":<22} {"Exit":<22} {"Ent $":<8} {"Ext $":<8} {"Ret%":<8} {"Cum%":<9}')
    print(f'  {"-"*83}')
    cumul = 1.0
    for i, t in enumerate(trades):
        cumul *= (1 + t['return'])
        print(f'  {i+1:<4} {str(t["entry_at"]):<22} {str(t["exit_at"]):<22} '
              f'${t["entry_price"]:<6.2f} ${t["exit_price"]:<6.2f} '
              f'{t["return"]*100:>+6.2f}% {(cumul-1)*100:>+7.2f}%')
    first_buy = min(t['entry_at'] for t in trades)
    first_price = min(t['entry_price'] for t in trades)
    print(f'\n  First entry: {first_buy.date()} @ ${first_price:.2f}')
    print(f'  Entry vs BH start: {(first_price - start_close) / start_close * 100:+.1f}%')


def main():
    parser = argparse.ArgumentParser(description='Multi-timeframe EMA/SMA backtest')
    parser.add_argument('--detail', action='store_true', help='Show detailed trade log')
    parser.add_argument('--tickers', type=str, help='Comma-separated tickers')
    parser.add_argument('--exit', choices=['ema', 'atr', 'daily-ema'], default='ema',
                        help='Exit method (default: ema)')
    parser.add_argument('--atr-period', type=int, default=14, help='ATR period (default: 14)')
    parser.add_argument('--atr-mult', type=float, default=2.0, help='ATR multiplier (default: 2.0)')
    args = parser.parse_args()

    if args.exit == 'atr':
        exit_label = f'ATR({args.atr_period})x{args.atr_mult} trail'
    elif args.exit == 'daily-ema':
        exit_label = 'daily EMA cross below SMA'
    else:
        exit_label = '1-hour EMA cross below SMA'

    db_module.init_db()
    conn = db_module.get_conn()

    try:
        if args.tickers:
            syms = [s.strip().upper() for s in args.tickers.split(',')]
            with conn.cursor() as cur:
                cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE symbol = ANY(%s)', (syms,))
                rows = cur.fetchall()
                found = {r[1]: r[0] for r in rows}
                missing = [s for s in syms if s not in found]
                if missing:
                    print(f'Tickers not found: {missing}')
                ticker_ids = list(found.values())
        else:
            ticker_ids = None

        tickers, weekly_data, daily_data, hourly_data = load_ticker_bars_batched(conn, ticker_ids)

        ts_start = datetime(2023, 6, 30)
        ts_end = datetime(2026, 7, 2)

        if args.tickers:
            selected = []
            for tid, sym in tickers:
                d = daily_data.get(tid)
                if not d:
                    continue
                bh = get_bh_return(d, ts_start.date(), ts_end.date())
                if bh is None:
                    bh = 0.0
                selected.append((bh, tid, sym))
        else:
            print(f'Ranking by buy-and-hold return...')
            ranked = []
            for tid, sym in tickers:
                d = daily_data.get(tid)
                if not d:
                    continue
                bh = get_bh_return(d, ts_start.date(), ts_end.date())
                if bh is not None:
                    ranked.append((bh, tid, sym))
            ranked.sort(key=lambda x: x[0], reverse=True)
            selected = ranked[:SAMPLE_SIZE] + ranked[-SAMPLE_SIZE:]
            print(f'  Top {SAMPLE_SIZE}: {[s for _,_,s in ranked[:SAMPLE_SIZE]]}')
            print(f'  Bottom {SAMPLE_SIZE}: {[s for _,_,s in ranked[-SAMPLE_SIZE:]]}')

        print()

        results = []
        for bh_ret, tid, sym in selected:
            w = weekly_data.get(tid)
            d = daily_data.get(tid)
            h = hourly_data.get(tid)
            if not (w and d and h):
                continue

            trades, metrics = backtest(tid, w, d, h,
                                       exit_mode=args.exit,
                                       atr_period=args.atr_period,
                                       atr_mult=args.atr_mult)
            if metrics is None:
                print(f'  {sym:<6}  No trades')
                continue

            results.append((sym, trades, metrics, bh_ret, w, d, h))

            if args.detail:
                start_close = float(d[0][4])
                end_close = float(d[-1][4])
                print_trade_log(sym, trades, bh_ret, start_close, end_close)
            else:
                print(f'  {sym:<6}  {metrics["total_trades"]:>3} trades  '
                      f'{metrics["win_rate"]*100:>5.1f}% WR  '
                      f'{metrics["total_return"]*100:>+8.2f}% ret  '
                      f'BH: {bh_ret*100:>+7.2f}%  '
                      f'vs BH: {(metrics["total_return"]-bh_ret)*100:>+7.2f}%')

        if not results:
            print('\nNo results.')
            return

        results.sort(key=lambda x: x[2]['total_return'], reverse=True)

        print(f'\n{"="*100}')
        print(f'  MULTI-TIMEFRAME EMA(10)/SMA(40) BACKTEST')
        print(f'  Entry: weekly + daily bullish + 1-hour fresh crossover')
        print(f'  Exit:  {exit_label}')
        print(f'{"="*100}\n')

        print(f'  {"Ticker":<6} {"Trades":<7} {"Wins":<5} {"Win%":<7} {"Avg Ret":<10} '
              f'{"Total Ret":<12} {"Max DD":<9} {"BH Ret":<10} {"vs BH":<10}')
        print(f'  {"-"*79}')
        for sym, trades, m, bh, _, _, _ in results:
            print(f'  {sym:<6} {m["total_trades"]:<7} {m["winning_trades"]:<5} '
                  f'{m["win_rate"]*100:>5.1f}% '
                  f'{m["avg_return"]*100:>+8.2f}% '
                  f'{m["total_return"]*100:>+10.2f}% '
                  f'{m["max_drawdown"]*100:>6.1f}% '
                  f'{bh*100:>+8.2f}% '
                  f'{(m["total_return"]-bh)*100:>+8.2f}%')

        n_half = SAMPLE_SIZE if not args.tickers else len(results) // 2
        if n_half > 0 and len(results) > 1:
            print(f'  {"-"*79}')
            avg_top = np.mean([r[2]['total_return'] for r in results[:min(n_half, len(results))]])
            avg_bot = np.mean([r[2]['total_return'] for r in results[-min(n_half, len(results)):]])
            avg_wr = np.mean([r[2]['win_rate'] for r in results])
            avg_dd = np.mean([r[2]['max_drawdown'] for r in results])
            avg_bh_top = np.mean([r[3] for r in results[:min(n_half, len(results))]])
            avg_bh_bot = np.mean([r[3] for r in results[-min(n_half, len(results)):]])
            print(f'  {"TOP AVG":<6} {"":<7} {"":<5} {avg_wr*100:>5.1f}% {"":<10} '
                  f'{avg_top*100:>+10.2f}% '
                  f'{avg_dd*100:>6.1f}% '
                  f'{avg_bh_top*100:>+8.2f}% '
                  f'{(avg_top-avg_bh_top)*100:>+8.2f}%')
            print(f'  {"BOT AVG":<6} {"":<7} {"":<5} {"":<7} {"":<10} '
                  f'{avg_bot*100:>+10.2f}% '
                  f'{"":<9} '
                  f'{avg_bh_bot*100:>+8.2f}% '
                  f'{(avg_bot-avg_bh_bot)*100:>+8.2f}%')
        print()

    finally:
        conn.close()


if __name__ == '__main__':
    main()
