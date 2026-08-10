#!/usr/bin/env python3
"""R&D: quantify market-regime gates on the MTF top-N rotation backtest.

Regime detectors tested as 'go to cash' gates:
  1) Breadth gate  : % of universe with weekly+daily close > SMA40 < 35 (same as Slack Risk-off)
  2) 4-ETF gate    : >=3 of VTI/SPY/QQQ/VTV with weekly EMA10 > SMA40 (weekly agreement)
  3) Both gates    : go to cash if either gate says risk-off
  4) 4-ETF strong  : all 4 bearish (agree=0)

Also reports, for each gate, how often the gate was triggered and whether it
avoided or added drawdown vs the ungated baseline.

Reuses loading + scoring from backtest_topn_multitf.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from datetime import datetime

import config
import db as db_module
from backtest_topn_multitf import load_bars, _last_idx_before, WARMUP, EMA, SMA, COST, CAPITAL

MKT_ETFS = ['VTI', 'SPY', 'QQQ', 'VTV']
MIN_TICKERS = 400


def _nearest_idx(idx_map, dates, target):
    """Index of last bar on/before target (fallback if exact missing)."""
    xi = idx_map.get(target)
    if xi is not None:
        return xi
    for i in range(len(dates) - 1, -1, -1):
        if dates[i] <= target:
            return i
    return None


def compute_breadth_series(weekly, daily, all_dates):
    """% of tickers with weekly close>sma40 AND daily close>sma40, per trading date.
    Uses last weekly bar on/before each trading day (weekly data only exists weekly)."""
    breadth = {}
    wk_sma = {tid: pd.Series(w['close']).rolling(SMA).mean().to_numpy()
              for tid, w in weekly.items()}
    dy_sma = {tid: pd.Series(d['close']).rolling(SMA).mean().to_numpy()
              for tid, d in daily.items()}
    wk_idx = {tid: {dt: i for i, dt in enumerate(w['dates'])} for tid, w in weekly.items()}
    dy_idx = {tid: {dt: i for i, dt in enumerate(d['dates'])} for tid, d in daily.items()}
    for sig_date in all_dates:
        up = tot = 0
        for tid in weekly:
            wi = _nearest_idx(wk_idx[tid], weekly[tid]['dates'], sig_date)
            di = _nearest_idx(dy_idx[tid], daily[tid]['dates'], sig_date)
            if wi is None or di is None or wi < WARMUP or di < WARMUP:
                continue
            wc = weekly[tid]['close'][wi]
            ws = wk_sma[tid][wi]
            dc = daily[tid]['close'][di]
            ds = dy_sma[tid][di]
            if np.isnan(wc) or np.isnan(ws) or np.isnan(dc) or np.isnan(ds):
                continue
            tot += 1
            if wc > ws and dc > ds:
                up += 1
        breadth[sig_date] = (up / tot * 100) if tot else None
    return breadth


def load_mkt_weekly(conn):
    """Load weekly bars for VTI/SPY/QQQ/VTV (they are is_etf, excluded from stock universe)."""
    data = {}
    for sym in MKT_ETFS:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT w.date, w.close FROM tbl_scanner_tickers w
                JOIN tbl_stock_tickers s ON s.id = w.ticker_id
                WHERE s.symbol = %s ORDER BY w.date ASC
            """, (sym,))
            rows = cur.fetchall()
        if len(rows) < WARMUP:
            print(f'  WARNING: {sym} only {len(rows)} weekly bars')
            continue
        data[sym] = dict(
            dates=[r[0] for r in rows],
            close=np.array([float(r[1]) for r in rows], dtype=np.float64),
        )
    return data


def compute_mkt_agreement(mkt_weekly, all_dates):
    """For each trading date: how many of VTI/SPY/QQQ/VTV are in weekly uptrend (ema10>sma40)."""
    mkt = {}
    for sym, w in mkt_weekly.items():
        ema = pd.Series(w['close']).ewm(span=EMA, adjust=False).mean().to_numpy()
        sma = pd.Series(w['close']).rolling(SMA).mean().to_numpy()
        mkt[sym] = dict(dates=w['dates'], close=w['close'], ema=ema, sma=sma)
    out = {}
    for d in all_dates:
        n = 0
        for sym in MKT_ETFS:
            m = mkt.get(sym)
            if not m:
                continue
            i = _nearest_idx({dt: j for j, dt in enumerate(m['dates'])}, m['dates'], d)
            if i is None or i < 1 or np.isnan(m['ema'][i]) or np.isnan(m['sma'][i]):
                continue
            if m['ema'][i] > m['sma'][i]:
                n += 1
        out[d] = n
    return out


def run_backtest(weekly, daily, hourly, all_dates, breadth, mkt_agr, gate='none', top_n=10):
    """Replicates backtest_topn_multitf daily-rebalance loop with optional regime gate.
    gate: 'none' | 'breadth' | 'mkt' | 'both' | 'mktstrong'
    """
    common = set(weekly) & set(daily) & set(hourly)
    daily_idx = {tid: {dt: i for i, dt in enumerate(d['dates'])} for tid, d in daily.items()}
    weekly_idx = {tid: {dt: i for i, dt in enumerate(w['dates'])} for tid, w in weekly.items()}
    hourly_idx = {tid: {dt: i for i, dt in enumerate(h['dates'])} for tid, h in hourly.items()}

    def gate_off(sig_date):
        if gate == 'none':
            return False
        if gate == 'breadth':
            b = breadth.get(sig_date)
            return b is not None and b < 35
        if gate == 'mkt':
            a = mkt_agr.get(sig_date)
            return a is not None and a <= 2  # <=2 of 4 bullish -> risk-off
        if gate == 'both':
            b = breadth.get(sig_date)
            a = mkt_agr.get(sig_date)
            return (b is not None and b < 35) or (a is not None and a <= 2)
        if gate == 'mktstrong':
            a = mkt_agr.get(sig_date)
            return a is not None and a == 0  # all 4 bearish
        return False

    positions = {}
    cash = CAPITAL
    equity_curve = []
    trade_log = []
    gated_days = 0
    days = 0
    gate_crosses = 0
    prev_gated = False

    for ri, sig_date in enumerate(all_dates):
        days += 1
        gated = gate_off(sig_date)
        if gated != prev_gated and gated:
            gate_crosses += 1
        prev_gated = gated
        if gated:
            gated_days += 1

        exec_idx = ri + 1
        if exec_idx >= len(all_dates):
            break
        exec_date = all_dates[exec_idx]

        # When gated: liquidate everything, no buys
        if gated:
            for tid in list(positions):
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
                trade_log.append((exec_date, pos['symbol'], 'SELL-GATE', pos['shares'], sp, ret))
                del positions[tid]
            pf_val = cash
            equity_curve.append(pf_val)
            continue

        # Compute MTF scores (same as backtest)
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
            if any(np.isnan(x) for x in (wc, we, ws, dc, de, ds, hc, ha)):
                continue
            if we <= ws or de <= ds:
                continue
            if hc <= ha or hc <= 0:
                continue
            gap_w = (wc - ws) / ws * 100
            atr_dist = (hc - ha) / hc * 100 if ha > 0 else 0
            days_since = 999
            for j in range(wi, 0, -1):
                e0 = weekly[tid]['ema'][j]; s0 = weekly[tid]['sma'][j]
                e1 = weekly[tid]['ema'][j - 1]; s1 = weekly[tid]['sma'][j - 1]
                if not (np.isnan(e0) or np.isnan(s0) or np.isnan(e1) or np.isnan(s1)):
                    if e0 > s0 and e1 <= s1:
                        days_since = (sig_date - weekly[tid]['dates'][j]).days
                        break
            gap_pts = min(gap_w / 20, 3)
            atr_pts = min(atr_dist / 1.5, 3)
            fresh_pts = max(0, 2 - days_since / 60)
            score = round(gap_pts + atr_pts + fresh_pts, 1)
            candidates.append((tid, score))

        if not candidates:
            pf_val = cash
            for tid in list(positions):
                p = _last_idx_before(daily_idx[tid], daily[tid]['dates'], sig_date)
                if p is not None:
                    pf_val += positions[tid]['shares'] * float(daily[tid]['close'][p])
            equity_curve.append(pf_val)
            continue

        candidates.sort(key=lambda x: -x[1])
        selected = {c[0] for c in candidates[:top_n]}

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
                del positions[tid]

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
                cash -= shares * bp
                positions[tid] = dict(shares=shares, entry_price=bp, symbol=daily[tid]['symbol'])
                trade_log.append((exec_date, daily[tid]['symbol'], 'BUY', shares, bp, None))

        pf_val = cash
        for tid, pos in positions.items():
            d = daily.get(tid)
            if d is None:
                continue
            xi = _last_idx_before(daily_idx[tid], daily[tid]['dates'], exec_date)
            if xi is not None:
                pf_val += pos['shares'] * float(d['close'][xi])
        equity_curve.append(pf_val)

    if not equity_curve:
        return None
    total_ret = (equity_curve[-1] - CAPITAL) / CAPITAL
    eq = np.array(equity_curve)
    dd = np.max((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq))
    sells = [t for t in trade_log if t[2].startswith('SELL')]
    wins = [t for t in sells if t[5] is not None and t[5] > 0]
    losses = [t for t in sells if t[5] is not None and t[5] <= 0]
    return dict(
        ret=total_ret, dd=dd, final=equity_curve[-1],
        buys=sum(1 for t in trade_log if t[2] == 'BUY'),
        sells=len(sells), gate_sells=sum(1 for t in trade_log if t[2] == 'SELL-GATE'),
        winrate=len(wins) / len(sells) * 100 if sells else 0,
        avg_win=np.mean([t[5] for t in wins]) * 100 if wins else 0,
        avg_loss=np.mean([t[5] for t in losses]) * 100 if losses else 0,
        gated_days=gated_days, days=days, gate_crosses=gate_crosses,
        equity_curve=equity_curve, trade_log=trade_log,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--start', default=None)
    args = parser.parse_args()

    db_module.init_db()
    conn = db_module.get_conn()
    try:
        print('  Loading stock universe...')
        _, weekly = load_bars(conn, 'tbl_scanner_tickers', 'date', False)
        _, daily = load_bars(conn, 'tbl_scanner_tickers_daily', 'date', False)
        _, hourly = load_bars(conn, 'tbl_scanner_tickers_1hour', None, False)

        common = set(weekly) & set(daily) & set(hourly)
        for tid in list(weekly.keys()):
            if tid not in common:
                del weekly[tid]
        for tid in list(daily.keys()):
            if tid not in common:
                del daily[tid]
        for tid in list(hourly.keys()):
            if tid not in common:
                del hourly[tid]

        for tid in weekly:
            wc = pd.Series(weekly[tid]['close'])
            weekly[tid]['ema'] = wc.ewm(span=EMA, adjust=False).mean().to_numpy()
            weekly[tid]['sma'] = wc.rolling(window=SMA).mean().to_numpy()
        for tid in daily:
            dc = pd.Series(daily[tid]['close'])
            daily[tid]['ema'] = dc.ewm(span=EMA, adjust=False).mean().to_numpy()
            daily[tid]['sma'] = dc.rolling(window=SMA).mean().to_numpy()

        all_dates = sorted(set().union(*[set(d['dates']) for d in daily.values()]))
        all_dates = [d for d in all_dates if sum(1 for td in daily.values() if d in td['dates']) >= MIN_TICKERS]
        if args.start:
            from datetime import date as _date
            all_dates = [d for d in all_dates if d >= _date.fromisoformat(args.start)]

        print(f'  Dates: {all_dates[0]} -> {all_dates[-1]} ({len(all_dates)} trading days)')

        print('  Computing breadth series (weekly+daily close>SMA40)...')
        breadth = compute_breadth_series(weekly, daily, all_dates)
        print('  Loading market ETFs weekly...')
        mkt_weekly = load_mkt_weekly(conn)
        print('  Computing 4-ETF weekly agreement (VTI/SPY/QQQ/VTV)...')
        mkt_agr = compute_mkt_agreement(mkt_weekly, all_dates)

        # Breadth stats
        bvals = [b for b in breadth.values() if b is not None]
        print(f'\n  Breadth: min {min(bvals):.0f}%  median {np.median(bvals):.0f}%  '
              f'<35% on {sum(1 for b in bvals if b < 35)}/{len(bvals)} days '
              f'({sum(1 for b in bvals if b < 35)/len(bvals)*100:.1f}%)')
        avals = [a for a in mkt_agr.values()]
        print(f'  4-ETF agreement: <=2 bullish on {sum(1 for a in avals if a <= 2)}/{len(avals)} days '
              f'({sum(1 for a in avals if a <= 2)/len(avals)*100:.1f}%), '
              f'==0 on {sum(1 for a in avals if a == 0)} days')

        print(f'\n{"="*92}')
        print(f'  TOP-{args.top_n} MTF BACKTEST — REGIME GATE COMPARISON')
        print(f'  Period: {all_dates[0]} to {all_dates[-1]}')
        print(f'{"="*92}')
        hdr = (f'  {"gate":<12} {"Return":>9} {"MaxDD":>7} {"Buys":>5} {"Sells":>6} '
               f'{"GateSells":>9} {"Win%":>6} {"AvgW":>7} {"AvgL":>7} {"Gated":>7}')
        print(hdr)
        print('  ' + '-' * 88)
        results = {}
        for gate in ['none', 'breadth', 'mkt', 'both', 'mktstrong']:
            r = run_backtest(weekly, daily, hourly, all_dates, breadth, mkt_agr, gate=gate, top_n=args.top_n)
            results[gate] = r
            print(f'  {gate:<12} {r["ret"]*100:+8.2f}% {r["dd"]*100:6.1f}% {r["buys"]:>5} '
                  f'{r["sells"]:>6} {r["gate_sells"]:>9} {r["winrate"]:>5.0f}% '
                  f'{r["avg_win"]:>+6.2f}% {r["avg_loss"]:>+6.2f}% '
                  f'{r["gated_days"]}/{r["days"]} ({r["gate_crosses"]}x)')
        print('  ' + '-' * 88)

        # 4-ETF override analysis: on days agreement<=2, how many top-10 picks existed / got overridden
        print('\n  --- 4-ETF agreement vs MTF picks overlap ---')
        # For a sample: dates where agreement <=2, count how many MTF candidates qualified
        daily_idx = {tid: {dt: i for i, dt in enumerate(d['dates'])} for tid, d in daily.items()}
        weekly_idx = {tid: {dt: i for i, dt in enumerate(w['dates'])} for tid, w in weekly.items()}
        hourly_idx = {tid: {dt: i for i, dt in enumerate(h['dates'])} for tid, h in hourly.items()}
        mkt_days = [d for d in all_dates if mkt_agr.get(d, 99) <= 2]
        if mkt_days:
            sample = mkt_days[::max(1, len(mkt_days) // 12)]
            print(f'  Days with <=2/4 ETFs bullish: {len(mkt_days)} total. Sample:')
            for d in sample:
                nq = 0
                for tid in common:
                    di = daily_idx[tid].get(d); wi = weekly_idx[tid].get(d); hi = hourly_idx[tid].get(d)
                    if di is None or wi is None or hi is None or di < 1 or wi < WARMUP or hi < 1:
                        continue
                    wc = weekly[tid]['close'][wi]; we = weekly[tid]['ema'][wi]; ws = weekly[tid]['sma'][wi]
                    dc = daily[tid]['close'][di]; de = daily[tid]['ema'][di]; ds = daily[tid]['sma'][di]
                    hc = hourly[tid]['close'][hi]; ha = hourly[tid]['atr_stop'][hi]
                    if any(np.isnan(x) for x in (wc, we, ws, dc, de, ds, hc, ha)):
                        continue
                    if we > ws and de > ds and hc > ha:
                        nq += 1
                print(f'    {d}: agreement={mkt_agr[d]}/4, MTF-qualifying stocks={nq}')
        else:
            print('  No days with agreement <=2 in period.')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
