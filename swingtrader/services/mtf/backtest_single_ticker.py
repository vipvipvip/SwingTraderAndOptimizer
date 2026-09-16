#!/usr/bin/env python3
"""Single-ticker EMA10/SMA40 crossover backtest (triple-timeframe).

Long while EMA10 > SMA40 on ALL three timeframes (weekly, daily, 1-hour).
Trigger history depends on data availability:
  * pre 2023-06-30: only weekly + daily have bars -> weekly+daily drive triggers
  * on/after 2023-06-30: the 1-hour EMA10>SMA40 state joins the gate
Entry/exit fills happen at the CLOSE of the NEXT trading day after a trigger.

SMA40 (rolling mean) is used — not EMA40 — so trigger dates match the
user's TOS/MTF emasma convention (EMA10>SMA40).

CSV output format (per trade):
  ticker, buydate, buyprice, selldate, sellprice, gainloss,
  WeeklyCO, DailyCO, HourlyCO

Usage:
  python backtest_single_ticker.py --ticker VLO
  python backtest_single_ticker.py --ticker VTI --out /tmp/single

Works for any ticker in tbl_stock_tickers (stocks AND ETFs, is_etf=true)."""

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

EMA_PERIOD = 10
SMA_LONG = 40
HOURLY_START = pd.Timestamp('2023-06-30').date()
CAPITAL = 100000.0


def _ema(series, span):
    return pd.Series(series).ewm(span=span, adjust=False).mean().to_numpy()


def _sma(series, window):
    return pd.Series(series).rolling(window=window).mean().to_numpy()


def _to_date(d):
    return d.date() if hasattr(d, 'date') else d


def load_data(conn, symbol):
    cur = conn.cursor()
    cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
    row = cur.fetchone()
    if row is None:
        cur.execute('SELECT id FROM tbl_etf_tickers WHERE symbol = %s', (symbol,))
        row = cur.fetchone()
        if row is None:
            return None, None
    ticker_id = row[0]
    out = {}
    cur.execute(
        'SELECT date, close FROM tbl_scanner_tickers WHERE ticker_id = %s ORDER BY date', (ticker_id,))
    wk = cur.fetchall()
    cur.execute(
        'SELECT date, open, high, low, close, volume FROM tbl_scanner_tickers_daily '
        'WHERE ticker_id = %s ORDER BY date', (ticker_id,))
    dy = cur.fetchall()
    cur.execute(
        'SELECT date, open, high, low, close, volume FROM tbl_scanner_tickers_1hour '
        'WHERE ticker_id = %s ORDER BY date', (ticker_id,))
    hr = cur.fetchall()
    cur.close()
    if len(wk) < SMA_LONG or len(dy) < SMA_LONG:
        return None, ticker_id
    out['weekly'] = {'date': [r[0] for r in wk], 'close': np.array([float(r[1]) for r in wk])}
    out['daily'] = {
        'date': [r[0] for r in dy],
        'open': np.array([float(r[1]) for r in dy]),
        'high': np.array([float(r[2]) for r in dy]),
        'low': np.array([float(r[3]) for r in dy]),
        'close': np.array([float(r[4]) for r in dy]),
        'volume': np.array([float(r[5]) for r in dy]),
    }
    if len(hr) >= SMA_LONG:
        out['hourly'] = {
            'date': [r[0] for r in hr],
            'open': np.array([float(r[1]) for r in hr]),
            'high': np.array([float(r[2]) for r in hr]),
            'low': np.array([float(r[3]) for r in hr]),
            'close': np.array([float(r[4]) for r in hr]),
            'volume': np.array([float(r[5]) for r in hr]),
        }
    return out, ticker_id


def _latest_tf_state(bars, as_of):
    dates = bars['date']
    if not dates:
        return None
    ad = _to_date(as_of)
    if _to_date(dates[0]) > ad:
        return None
    hi = np.searchsorted([_to_date(d) for d in dates], ad, side='right') - 1
    if hi < SMA_LONG - 1:
        return None
    ema10 = _ema(bars['close'][: hi + 1], EMA_PERIOD)[hi]
    sma40 = _sma(bars['close'][: hi + 1], SMA_LONG)[hi]
    return ema10, sma40


MIN_HOURLY_VOL = 1000.0  # drop degraded/synthetic bars (DB vol is 40-700, real majors ~100K+)


def _settled_hourly_days(hourly, min_bars=2):
    """Return {date: (ema10, sma40)} keyed to days with a usable session day.

    The stored hourly series is heterogeneous: historic good days carry real
    regular-session bars (e.g. 09:00-15:00, vol ~100-250K), recent days mix in
    degraded synthetic bars (flat OHLC, vol 40-700, inconsistent hour stamps)
    plus a couple of REAL morning bars. A "valid" bar requires real OHLC spread
    and volume >= MIN_HOURLY_VOL; a usable "settled" day requires >= min_bars
    valid bars (default 2, so a recent 2-real-bar capture day still drives HCO
    rather than freezing at the last full-session day). EMA10/SMA40 run over the
    valid-bar sequence in time order; each day's state is taken at its LAST
    valid bar. So the hourly gate (HCO) is settled/day-old by construction and
    contaminated capture days never drive it.
    """
    ts = hourly['date']
    o, h, l_, c, v = (hourly[k] for k in ('open', 'high', 'low', 'close', 'volume'))
    valid = np.array([not (o[i] == h[i] == l_[i] == c[i]) and v[i] >= MIN_HOURLY_VOL
                      for i in range(len(ts))])
    if valid.sum() < min_bars:
        return {}
    vdates = [t for t, k in zip(ts, valid) if k]
    vcloses = c[valid]
    ema10 = _ema(vcloses, EMA_PERIOD)
    sma40 = _sma(vcloses, SMA_LONG)
    idx_by_day = {}
    for i, t in enumerate(vdates):
        idx_by_day.setdefault(_to_date(t), []).append(i)
    daymap = {}
    for day, inds in idx_by_day.items():
        if len(inds) >= min_bars:
            last = inds[-1]
            daymap[day] = (ema10[last], sma40[last])
    return daymap


def _hourly_state_as_of(daymap, as_of):
    """Latest PREV-DAY hourly (ema10, sma40) strictly BEFORE as_of.

    Foolproof hourly rule: HCO on day D uses only settled hourly bars with
    date < D (prev day's close) — today's partial/degraded capture can never
    drive its own signal. The mapped day state is taken at that day's LAST
    valid bar, so the signal is deterministic and reproducible.
    """
    ad = _to_date(as_of)
    best = None
    for day in daymap:
        if day < ad and (best is None or day > best):
            best = day
    return daymap.get(best)


def _atr14(daily, period=14):
    """Simple rolling-mean ATR(14) over the daily series."""
    h = daily['high']; l = daily['low']; c = daily['close']
    prevc = np.empty_like(c)
    prevc[0] = c[0]
    prevc[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prevc), np.abs(l - prevc)))
    return pd.Series(tr).rolling(period).mean().bfill().values


def run(symbol, out_dir, capital, min_bars=2, entry_close_ema=False, atr_exit=False,
        atr_mult=2.0, exit_only_daily=False, exit_ignore_hourly=False):
    conn = db.get_conn()
    data, ticker_id = load_data(conn, symbol)
    conn.close()
    if data is None:
        print(f'No data for {symbol} (or <{SMA_LONG} weekly/daily bars).')
        return 1
    weekly, daily = data['weekly'], data['daily']
    hourly = data.get('hourly')
    print(f'\n  {symbol}   [{ticker_id}]')
    print(f'  Weekly: {weekly["date"][0]} -> {weekly["date"][-1]}  ({len(weekly["close"])} bars)')
    print(f'  Daily:  {daily["date"][0]} -> {daily["date"][-1]}  ({len(daily["close"])} bars)')
    if hourly:
        print(f'  1hour:  {hourly["date"][0]} -> {hourly["date"][-1]}  ({len(hourly["close"])} bars)  '
              f'(gates from {HOURLY_START}, settled >= {min_bars} bars/day)')
    else:
        print(f'  1hour:  none')
    opts = []
    if entry_close_ema:
        opts.append('entry: close>daily EMA10')
    if atr_exit:
        opts.append(f'exit: ATR-ratchet x{atr_mult}')
    if exit_only_daily:
        opts.append('exit: daily bear-flip only')
    if exit_ignore_hourly:
        opts.append('exit: weekly/daily bear-flip (ignore hourly)')
    if opts:
        print(f'  opts:  {", ".join(opts)}')

    d_dates = daily['date']
    d_close = daily['close']
    atr = _atr14(daily) if atr_exit else None
    hday_map = _settled_hourly_days(hourly, min_bars) if hourly else {}

    # ------------------------------------------------------------------
    # Main loop: compute per-bar 3-TF state, fire trigger on flip.
    # ------------------------------------------------------------------
    state = 'FLAT'          # current target state (FLAT or LONG)
    pending = None          # (BUY/SELL, trigger_date) awaiting next-bar fill
    ratchet_peak = None     # highest daily close since entry (ATR-ratchet exit)
    fills = []              # (fill_date, side, fill_close, trigger_date, w_bull, d_bull, h_bull)
    all_states = []         # per-bar state record for signals CSV

    for i, d in enumerate(d_dates):
        # 1) Fill prior trigger at THIS bar's close (next-day-close semantics).
        if pending is not None:
            side, trig_date, wb, db_, hb = pending
            fills.append((d, side, float(d_close[i]), trig_date, wb, db_, hb))
            if side == 'BUY':
                ratchet_peak = float(d_close[i])
            pending = None

        # 2) Compute current 3-TF state.
        w   = _latest_tf_state(weekly, d)
        dy  = _latest_tf_state(daily, d)
        hr  = _hourly_state_as_of(hday_map, d) if hday_map else None
        wb  = w  is not None and w[0]  > w[1]
        db_ = dy is not None and dy[0] > dy[1]
        hg  = bool(hday_map) and _to_date(d) >= HOURLY_START and hr is not None
        hb  = (hr is not None and hr[0] > hr[1]) if hg else None
        long_ok = wb and db_ and (hb if hg else True)
        close_i = float(d_close[i])

        if state == 'LONG' and atr_exit:
            ratchet_peak = max(ratchet_peak, close_i) if ratchet_peak else close_i
            exit_hit = close_i < ratchet_peak - atr_mult * atr[i]
            desired = 'FLAT' if exit_hit else 'LONG'
        else:
            buy_ok = long_ok and (not entry_close_ema or close_i > dy[0])
            if exit_only_daily and state == 'LONG':
                desired = 'LONG' if db_ else 'FLAT'
            elif exit_ignore_hourly and state == 'LONG':
                desired = 'LONG' if (wb and db_) else 'FLAT'
            else:
                desired = 'LONG' if (buy_ok if state == 'FLAT' else long_ok) else 'FLAT'

        if desired != state:
            side = 'BUY' if desired == 'LONG' else 'SELL'
            pending = (side, d, wb, db_, hb if hg else None)
            state = desired

        all_states.append({
            'date': d,
            'close': round(float(daily['close'][i]), 2),
            'w_ema10': round(w[0], 2)  if w  else '',
            'w_sma40': round(w[1], 2)  if w  else '',
            'd_ema10': round(dy[0], 2) if dy else '',
            'd_sma40': round(dy[1], 2) if dy else '',
            'h_ema10': round(hr[0], 2) if hr else '',
            'h_sma40': round(hr[1], 2) if hr else '',
            'w_bull': 'T' if wb else 'F',
            'd_bull': 'T' if db_ else 'F',
            'h_bull': 'T' if hb else ('F' if hg else ''),
        })

    # ------------------------------------------------------------------
    # Build round-trips from fills (alternating BUY/SELL).
    # ------------------------------------------------------------------
    cash = capital
    shares = 0.0
    entry = None
    trades = []

    for fd, side, fclose, tdate, wb, db_, hb in fills:
        if side == 'BUY' and entry is None:
            shares = cash / fclose
            cash = 0.0
            entry = {
                'td': tdate, 'fd': fd, 'fc': fclose,
                'wb': wb, 'db': db_, 'hb': hb,
                'shares': shares,
            }
        elif side == 'SELL' and entry is not None:
            sold = shares
            cash = sold * fclose
            shares = 0.0
            trades.append({
                'ticker': symbol,
                'buydate': entry['td'],
                'buyprice': round(entry['fc'], 2),
                'selldate': tdate,
                'sellprice': round(fclose, 2),
                'gainloss_usd': round(sold * (fclose - entry['fc']), 2),
                'gainloss_pct': round((fclose - entry['fc']) / entry['fc'] * 100, 2),
                'WeeklyCO': 'bull' if entry['wb'] else 'bear',
                'DailyCO': 'bull' if entry['db'] else 'bear',
                'HourlyCO': ('bull' if entry['hb'] else 'bear') if entry['hb'] is not None else 'n/a',
            })
            entry = None

    # ------------------------------------------------------------------
    # Equity curve (compounding).
    # ------------------------------------------------------------------
    cash = capital
    shares = 0.0
    fill_map = {}
    for fd, side, *_ in fills:
        fill_map.setdefault(fd, []).append(side)

    equity = []
    for i, d in enumerate(d_dates):
        for side in fill_map.get(d, []):
            if side == 'BUY' and shares == 0.0:
                shares = cash / float(daily['close'][i])
                cash = 0.0
            elif side == 'SELL' and shares > 0.0:
                cash = shares * float(daily['close'][i])
                shares = 0.0
        equity.append(cash + shares * float(daily['close'][i]))

    # ------------------------------------------------------------------
    # Terminal summary.
    # ------------------------------------------------------------------
    wins = [t for t in trades if t['gainloss_pct'] > 0]
    losses = [t for t in trades if t['gainloss_pct'] <= 0]
    total_pnl = sum(t['gainloss_usd'] for t in trades)

    print(f'\n  ROUND-TRIPS: {len(trades)}')
    if trades:
        print(f'    total $P&L: {total_pnl:+,.2f}   return: {total_pnl / capital * 100:+,.1f}%')
        print(f'    win rate: {len(wins) / len(trades) * 100:.0f}%  '
              f'({len(wins)}W / {len(losses)}L)')
        print(f'    avg win:  {np.mean([t["gainloss_pct"] for t in wins]):+.2f}%')
        print(f'    avg loss: {np.mean([t["gainloss_pct"] for t in losses]):+.2f}%')
        print(f'    max equity DD: {_max_dd(equity) * 100:.1f}%')
        print()
        hdr = f'    {"BuyDate":<12} {"Buy$":>9} {"SellDate":<12} {"Sell$":>9} {"P&L$":>10} {"P&L%":>8}  {"W":>4} {"D":>4} {"H":>4}'
        print(hdr)
        print(f'    {"-"*95}')
        for t in trades:
            print(f'    {str(t["buydate"]):<12} {t["buyprice"]:>9.2f} {str(t["selldate"]):<12} '
                  f'{t["sellprice"]:>9.2f} {t["gainloss_usd"]:>+10,.2f} {t["gainloss_pct"]:>+7.2f}%  '
                  f'{t["WeeklyCO"][:1]:>4} {t["DailyCO"][:1]:>4} {t["HourlyCO"][:1]:>4}')
    else:
        print('    (no trades)')

    # ------------------------------------------------------------------
    # CSV outputs.
    # ------------------------------------------------------------------
    os.makedirs(out_dir, exist_ok=True)

    # trades CSV (exact format requested)
    trd_path = os.path.join(out_dir, f'{symbol}_trades.csv')
    if trades:
        df = pd.DataFrame(trades)
        cols = ['ticker', 'buydate', 'buyprice', 'selldate', 'sellprice',
                'gainloss_usd', 'gainloss_pct', 'WeeklyCO', 'DailyCO', 'HourlyCO']
        df[cols].to_csv(trd_path, index=False)

    # signals CSV (per daily bar state)
    sig_path = os.path.join(out_dir, f'{symbol}_signals.csv')
    pd.DataFrame(all_states).to_csv(sig_path, index=False)

    # equity CSV
    eq_path = os.path.join(out_dir, f'{symbol}_equity.csv')
    pd.DataFrame({'date': d_dates, 'equity': [round(e, 2) for e in equity]}).to_csv(eq_path, index=False)

    print(f'\n  Files written:')
    print(f'    {trd_path}')
    print(f'    {sig_path}')
    print(f'    {eq_path}')
    return 0


def _max_dd(equity):
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)
    return float(np.max((peak - arr) / peak)) if len(arr) else 0.0


def _cross_events(bars):
    """Return (up_crosses, down_crosses, current_bull) for a bars dict.
    up_cross  = EMA10 crosses above SMA40 (bear->bull)
    down_cross = EMA10 crosses below SMA40 (bull->bear)
    Events are (bar_timestamp, bull_after)."""
    closes = bars['close']
    ema10 = _ema(closes, EMA_PERIOD)
    sma40 = _sma(closes, SMA_LONG)
    bull = ema10 > sma40
    up, down = [], []
    for i in range(1, len(closes)):
        if np.isnan(sma40[i]) or np.isnan(sma40[i - 1]):
            continue
        if bull[i] and not bull[i - 1]:
            up.append((bars['date'][i], bull[i]))
        elif not bull[i] and bull[i - 1]:
            down.append((bars['date'][i], bull[i]))
    return up, down, bool(bull[-1])


def _cross_events_state(dates, ema10, sma40):
    """Cross events from precomputed EMA10/SMA40 series (for settled-hourly map)."""
    bull = ema10 > sma40
    up, down = [], []
    for i in range(1, len(dates)):
        if np.isnan(sma40[i]) or np.isnan(sma40[i - 1]):
            continue
        if bull[i] and not bull[i - 1]:
            up.append((dates[i], bull[i]))
        elif not bull[i] and bull[i - 1]:
            down.append((dates[i], bull[i]))
    return up, down, bool(bull[-1])


def _fmt_dt(d):
    return d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') and ' ' in str(d) else str(d)


def run_crosses(symbol, since, min_bars=2):
    conn = db.get_conn()
    data, ticker_id = load_data(conn, symbol)
    conn.close()
    if data is None:
        print(f'No data for {symbol} (or <{SMA_LONG} weekly/daily bars).')
        return 1
    weekly, daily = data['weekly'], data['daily']
    hourly = data.get('hourly')
    hday_map = _settled_hourly_days(hourly, min_bars) if hourly else {}
    print(f'\n  {symbol}  [{ticker_id}]  EMA10 > SMA40 crossover state '
          f'(hourly = settled >= {min_bars} bars/day)')
    rows = [('Weekly', weekly), ('Daily', daily)]
    for label, bars in rows:
        up, down, cur = _cross_events(bars)
        last_up = up[-1][0] if up else None
        last_down = down[-1][0] if down else None
        print(f'  {label:7} last DOWN cross = {_fmt_dt(last_down) if last_down else "never":<12} '
              f'last UP cross = {_fmt_dt(last_up) if last_up else "never":<12} '
              f'current = {"bull" if cur else "bear"} ({bars["date"][-1]})')

    if hday_map:
        last_daily = _to_date(daily['date'][-1])
        hday_map = {d: v for d, v in hday_map.items() if d < last_daily}
        hdays = sorted(hday_map)
        h_dates = [d for d in hdays]
        h_ema10 = np.array([hday_map[d][0] for d in hdays])
        h_sma40 = np.array([hday_map[d][1] for d in hdays])
        up, down, cur = _cross_events_state(h_dates, h_ema10, h_sma40)
        last_settled = hdays[-1] if hdays else None
        if hdays:
            last_up = up[-1][0] if up else None
            last_down = down[-1][0] if down else None
            print(f'  {"1hour":7} last DOWN cross = {_fmt_dt(last_down) if last_down else "never":<16} '
                  f'last UP cross = {_fmt_dt(last_up) if last_up else "never":<16} '
                  f'current = {"bull" if cur else "bear"} (prev-day settled thru {last_settled})\n')
            all_ev = sorted(up + down, key=lambda e: e[0])
            recent = [e for e in all_ev if e[0] >= pd.Timestamp(since).date()] if since else all_ev[-8:]
            for dt_, bull in recent:
                print(f'      {_fmt_dt(dt_)}  {"UP   (bear->bull)" if bull else "DOWN (bull->bear)"}')
        else:
            print(f'  {"1hour":7} no prev-day settled hourly — gate disabled\n')
        return 0
    print(f'  {"1hour":7} no prev-day settled hourly — gate disabled\n')
    return 0


def main():
    global CAPITAL
    ap = argparse.ArgumentParser(description='Single-ticker EMA10/SMA40 triple-TF backtest')
    ap.add_argument('--ticker', required=True)
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  'single_ticker_out'))
    ap.add_argument('--capital', type=float, default=CAPITAL)
    ap.add_argument('--crosses', action='store_true',
                    help='only show last UP/DOWN crossover dates + recent flips (no backtest)')
    ap.add_argument('--since', default=None,
                    help='with --crosses: show all flips after YYYY-MM-DD (hourly shows ET timestamps)')
    ap.add_argument('--min-bars', type=int, default=2,
                    help='hourly settled-day rule: min valid bars/day for a day to drive HCO (default 2)')
    ap.add_argument('--entry-close-ema', action='store_true',
                    help='BUY only when daily close > daily EMA10 (filter late/pullback entries)')
    ap.add_argument('--atr-exit', action='store_true',
                    help='exit on daily ATR-ratchet (close < peak - atr_mult*ATR14) instead of bear-flip')
    ap.add_argument('--atr-mult', type=float, default=2.0,
                    help='ATR-ratchet multiplier (default 2.0)')
    ap.add_argument('--exit-only-daily', action='store_true',
                    help='exit only when DAILY EMA10<SMA40 (ignore hourly/weekly bear for exits)')
    ap.add_argument('--exit-ignore-hourly', action='store_true',
                    help='exit when weekly OR daily flips bear (ignore hourly whipsaw exits)')
    args = ap.parse_args()
    if args.capital:
        CAPITAL = args.capital
    if args.crosses:
        return run_crosses(args.ticker.upper(), args.since, args.min_bars)
    return run(args.ticker.upper(), args.out, CAPITAL, args.min_bars,
               entry_close_ema=args.entry_close_ema, atr_exit=args.atr_exit,
               atr_mult=args.atr_mult, exit_only_daily=args.exit_only_daily,
               exit_ignore_hourly=args.exit_ignore_hourly)


if __name__ == '__main__':
    sys.exit(main())
