#!/usr/bin/env python3
import os
import pickle
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

COST = 0.0005
CAPITAL = 100_000.0
DB = dict(host=os.getenv('DB_HOST', '127.0.0.1'),
          port=int(os.getenv('DB_PORT', '5432')),
          dbname=os.getenv('DB_DATABASE', 'swingtrader'),
          user=os.getenv('DB_USERNAME', 'swingtrader'),
          password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'))
ETF_POOL = ['DIA', 'EEM', 'EFA', 'IJH', 'IJR', 'IWM', 'QQQ', 'RSP', 'SCHB', 'SCHD',
            'SMH', 'SPY', 'TLT', 'VGT', 'VTI', 'VTV', 'VUG', 'XLB', 'XLC', 'XLE',
            'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU', 'XLV', 'XLY']
STOCK_POOL = ['A', 'AAOI', 'ACIW', 'ACN', 'ACU', 'ADP', 'ADSK', 'AGL', 'AGYS', 'ALLE',
              'ALRM', 'ANF', 'APPF', 'ATR', 'BAH', 'BALL', 'BBY', 'BDX', 'BJ',
              'BMI', 'CAKE', 'CBOE', 'CBRL', 'CDW', 'CHDN', 'CHH', 'COLM', 'CPAY', 'CRAI',
              'CRL', 'CROX', 'CRVL', 'CRWD', 'CSL', 'CTSH', 'CVCO', 'DINO', 'DOCU', 'DUOL',
              'ECO', 'ECPG', 'ED', 'EPAM', 'EXPO', 'EXR', 'FCN', 'FTV', 'GEHC', 'GKOS',
              'HCA', 'HHH', 'HNGE', 'HRI', 'HURN', 'ICE', 'IDXX', 'INOD', 'KNSA', 'LITE',
              'MANH', 'MCK', 'MORN', 'MRNA', 'MSCI', 'MXL', 'NBIS', 'OLLI', 'PDS', 'PG',
              'PLTR', 'PPG', 'QTWO', 'RCL', 'REGN', 'RGLD', 'ROP', 'RYTM', 'SN', 'SPGI',
              'STE', 'TNL', 'TTAN', 'TW', 'TWST', 'TYL', 'ULTA', 'UPS', 'VCYT', 'VICR',
              'VRSK', 'WCN', 'WDAY', 'WGS', 'WIX', 'ZS']


def load(tf, symbols):
    table = 'tbl_prices_daily' if tf == 'day' else 'tbl_prices_weekly'
    conn = psycopg2.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT s.symbol, p.date, p.open, p.close FROM {table} p
            JOIN tbl_stock_tickers s ON s.id=p.ticker_id
            WHERE s.symbol = ANY(%s) AND p.date <= %s ORDER BY p.date ASC
        """, (symbols, date.today() - timedelta(days=1)))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['symbol', 'date', 'open', 'close'])
    for c in ('open', 'close'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    frames = {}
    for c in ('open', 'close'):
        frames[c] = df.pivot(index='date', columns='symbol', values=c).reindex(columns=symbols)
    return frames['open'], frames['close']


def calculate_tos_dymi(price, stdev_length=5, avg_of_stdev_length=10,
                       dymi_length=14, dymi_lower_limit=5, dymi_upper_limit=30):
    """TOS DynamicMomentumIndex: volatility-adaptive Wilder RSI on settled closes."""
    price = pd.Series(price, dtype=float)
    stdev = price.rolling(window=stdev_length).std(ddof=0)
    avg_stdev = stdev.rolling(window=avg_of_stdev_length).mean()
    with np.errstate(divide='ignore', invalid='ignore'):
        vi = stdev / avg_stdev
        td = np.round(dymi_length / vi)
    td = np.clip(td, dymi_lower_limit, dymi_upper_limit)
    delta = price.diff().to_numpy()
    gain = np.nan_to_num(np.clip(delta, 0, None), nan=0.0)
    loss = np.nan_to_num(np.clip(-delta, 0, None), nan=0.0)
    td_arr = td.to_numpy(dtype=float)
    n = len(price)
    out = np.full(n, np.nan)
    for i in range(n):
        length = td_arr[i]
        if not np.isfinite(length):
            continue
        length = int(length)
        if i < length:
            continue
        start = max(1, i - length * 3)
        alpha = 1.0 / length
        avg_gain = gain[start]
        avg_loss = loss[start]
        for j in range(start + 1, i + 1):
            avg_gain = alpha * gain[j] + (1.0 - alpha) * avg_gain
            avg_loss = alpha * loss[j] + (1.0 - alpha) * avg_loss
        if avg_loss <= 0:
            out[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            out[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return pd.Series(out, index=price.index, name='DYMI')


def cached_dymi_panel(dclose, end):
    path = f'/tmp/opencode/s1_dymi_{end}.pkl'
    if os.path.exists(path):
        with open(path, 'rb') as fh:
            panel = pickle.load(fh)
        if panel.index.equals(dclose.index) and list(panel.columns) == list(dclose.columns):
            return panel
    print('building DYMI panel', flush=True)
    panel = pd.DataFrame({s: calculate_tos_dymi(dclose[s]) for s in dclose.columns},
                         index=dclose.index).reindex(columns=dclose.columns)
    with open(path, 'wb') as fh:
        pickle.dump(panel, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return panel


def dymi_pct_rank(dclose, active, dymi):
    """Cross-sectional DYMI percentile among names the strategy would hold that day."""
    rank = pd.DataFrame(np.nan, index=dclose.index, columns=dclose.columns)
    eligible = active.fillna(False) & dymi.notna()
    for day in dclose.index:
        syms = eligible.columns[eligible.loc[day].to_numpy()]
        if len(syms) < 2:
            continue
        vals = dymi.loc[day, syms].to_numpy(dtype=float)
        rank.loc[day, syms] = pd.Series(vals).rank(pct=True).to_numpy()
    return rank


def dymi_top_n(s1, rank, n, cut=0.75, prefer_high=False):
    """Pick n held names by DYMI rank, restricted to the non-top quartiles."""
    out = pd.DataFrame(False, index=s1.index, columns=s1.columns)
    valid = s1.fillna(False) & rank.lt(cut)
    for day in s1.index:
        syms = valid.columns[valid.loc[day].to_numpy()]
        if not len(syms):
            continue
        order = np.argsort(rank.loc[day, syms].to_numpy(dtype=float))
        if prefer_high:
            order = order[::-1]
        out.loc[day, syms[order[:n]]] = True
    return out


def dymi_entry_quartiles(label, dopen, entered, rank):
    """Forward-return check of the Q1 'already moved' hypothesis at entry events."""
    r = rank.reindex(index=entered.index, columns=entered.columns)
    op = dopen.reindex(index=entered.index, columns=entered.columns).to_numpy(dtype=float)
    buckets = {'Q1 top (excluded)': [], 'Q2': [], 'Q3': [], 'Q4 bottom': []}
    print(label, flush=True)
    for i, day in enumerate(entered.index):
        for col in np.flatnonzero(entered.to_numpy()[i]):
            q = r.iat[i, col]
            if not np.isfinite(q):
                continue
            key = ('Q1 top (excluded)' if q >= 0.75 else 'Q2' if q >= 0.5
                   else 'Q3' if q >= 0.25 else 'Q4 bottom')
            fwd = {}
            if i + 1 < len(op) and np.isfinite(op[i + 1, col]) and op[i + 1, col] > 0:
                for h in (20, 60):
                    j = i + h
                    if j < len(op) and np.isfinite(op[j, col]):
                        fwd[h] = op[j, col] / op[i + 1, col] - 1.0
            buckets[key].append(fwd)
    for key, rows in buckets.items():
        f20 = [x[20] for x in rows if 20 in x]
        f60 = [x[60] for x in rows if 60 in x]
        print(f'  {key:<20} n={len(rows):>5}  fwd20 mean {np.mean(f20)*100:>6.2f}% '
              f'med {np.median(f20)*100:>6.2f}%  fwd60 mean {np.mean(f60)*100:>6.2f}% '
              f'med {np.median(f60)*100:>6.2f}%' if f20 and f60 else
              f'  {key:<20} n={len(rows):>5}  (no forward window)', flush=True)


def build_expl_walkforward(px):
    import imminent_probability as ip

    panel = ip.feature_panel(with_labels=True)
    panel = panel[panel['symbol'].isin(px.columns)]
    bundles = {}
    out = {}
    for week in px.index:
        qstart = pd.Timestamp(week).to_period('Q').start_time
        cutoff = qstart - pd.Timedelta(weeks=13)
        if cutoff < panel['date'].min() + pd.Timedelta(weeks=52):
            out[week] = set()
            continue
        if cutoff not in bundles:
            print(f'training walk-forward EXPL bundle {cutoff.date()}', flush=True)
            bundles[cutoff] = ip.train_bundle(panel, cutoff)
        try:
            picks = ip.select(panel, week, bundle=bundles[cutoff], top_n=10,
                              min_dvol=50e6)
        except Exception as exc:
            print(f'[PIT] EXPL select failed for {week}: {exc}', flush=True)
            picks = pd.DataFrame()
        out[week] = set(picks['symbol']) if not picks.empty else set()
    return out


def build_pit_universe(end_date, expl_mode='full'):
    suffix = {'full': '', 'noexpl': '-noexpl', 'wfexpl': '-wfexpl'}[expl_mode]
    cache_path = f'/tmp/opencode/s1_pit_universe_{end_date}{suffix}.pkl'
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as fh:
            return pickle.load(fh)
    import cmo_universe

    conn = psycopg2.connect(**DB)
    try:
        wp, dp = cmo_universe.load_panels(end_date, conn=conn)
    finally:
        conn.close()
    weekly_e10, weekly_sma40, weekly_e40 = cmo_universe.weekly_indicators(wp)
    print('building PIT RS / MTF / Takeoff', flush=True)
    rs = cmo_universe.build_rs(wp, dp, weekly_e10, weekly_sma40, weekly_e40)
    mtf = cmo_universe.build_mtf(wp['close'], weekly_e10, weekly_sma40, weekly_e40)
    takeoff = cmo_universe.build_takeoff(wp)
    print('building PIT EXPL / Daily Signal', flush=True)
    if expl_mode == 'full':
        expl = cmo_universe.build_expl(wp['close'])
    elif expl_mode == 'wfexpl':
        expl = build_expl_walkforward(wp['close'])
    else:
        expl = {}
    dsignal = cmo_universe.build_daily_signal(wp, dp, weekly_e10, weekly_sma40)
    weeks = sorted(set(rs) | set(mtf) | set(takeoff) | set(expl))
    active = {}
    for day in sorted(dp['close'].index):
        valid = [w for w in weeks if w + timedelta(days=7) <= day < w + timedelta(days=14)]
        week = max(valid) if valid else None
        names = set(dsignal.get(day, set()))
        if week is not None:
            for src in (rs, mtf, takeoff, expl):
                names |= src.get(week, set())
        active[day] = names
    with open(cache_path, 'wb') as fh:
        pickle.dump(active, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return active


def ema(series, span):
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def states(dopen, dclose, wclose, entry_ok=None):
    d10, d20 = ema(dclose, 10), ema(dclose, 20)
    w10, w20 = ema(wclose, 10), ema(wclose, 20)
    wstate = (w10 > w20).where(np.isfinite(w10) & np.isfinite(w20), False)
    settle = wclose.index + pd.Timedelta(days=7)
    valid_d = np.isfinite(d10) & np.isfinite(d20)
    cross_up = valid_d & (d10 > d20) & (d10.shift(1) <= d20.shift(1))
    if entry_ok is not None:
        cross_up = cross_up & entry_ok.reindex(index=dclose.index,
                                              columns=dclose.columns).fillna(False)
    cross_dn = pd.DataFrame(False, index=dclose.index, columns=dclose.columns)
    for sym in dclose.columns:
        ss = pd.Series(settle.values, index=wstate.index)
        valid_w = wstate[sym].index
        changed = pd.Series(np.r_[True, ss.values[1:] != ss.values[:-1]], index=valid_w)
        dn = (~wstate[sym]) & wstate[sym].shift(1).fillna(False) & changed
        for week in dn.index[dn.fillna(False)]:
            later = dclose.index[dclose.index >= week + pd.Timedelta(days=7)]
            if len(later):
                cross_dn.loc[later[0], sym] = True
    s1 = pd.DataFrame(False, index=dclose.index, columns=dclose.columns)
    donly = valid_d & (d10 > d20)
    for sym in dclose.columns:
        held = False
        vals = np.zeros(len(dclose), dtype=bool)
        cu, cd = cross_up[sym].to_numpy(), cross_dn[sym].to_numpy()
        for i in range(len(vals)):
            if not held and cu[i]:
                held = True
            elif held and cd[i]:
                held = False
            vals[i] = held
        s1[sym] = vals
    return s1.fillna(False), donly.fillna(False)


def freshest_top_n(dclose, wclose, n, recross=False, allowed=None):
    d10 = ema(dclose, 10).to_numpy(dtype=float)
    d20 = ema(dclose, 20).to_numpy(dtype=float)
    w10 = ema(wclose, 10).to_numpy(dtype=float)
    w20 = ema(wclose, 20).to_numpy(dtype=float)
    wstate = np.isfinite(w10) & np.isfinite(w20) & (w10 > w20)
    week_dn = np.zeros_like(wstate)
    week_dn[1:] = (~wstate[1:]) & wstate[:-1]
    settle_days = (wclose.index + pd.Timedelta(days=7)).to_numpy()
    daily_days = dclose.index.to_numpy()
    day_idx = np.searchsorted(daily_days, settle_days, side='left')
    cross_dn = np.zeros(dclose.shape, dtype=bool)
    for week_i, sym_i in zip(*np.nonzero(week_dn)):
        target = day_idx[week_i]
        if target < len(daily_days):
            cross_dn[target, sym_i] = True
    prev_d10 = np.vstack([np.full((1, dclose.shape[1]), np.nan), d10[:-1]])
    prev_d20 = np.vstack([np.full((1, dclose.shape[1]), np.nan), d20[:-1]])
    cross_up = (np.isfinite(d10) & np.isfinite(d20) & (d10 > d20)
                & np.isfinite(prev_d10) & np.isfinite(prev_d20)
                & (prev_d10 <= prev_d20))
    if allowed is None:
        allowed_arr = np.ones(dclose.shape, dtype=bool)
    else:
        allowed_arr = allowed.reindex(index=dclose.index,
                                      columns=dclose.columns).fillna(False).to_numpy(dtype=bool)
    held = np.zeros(dclose.shape[1], dtype=bool)
    last_up = np.full(dclose.shape[1], -1, dtype=np.int64)
    want = np.zeros(dclose.shape, dtype=bool)
    for i in range(len(dclose)):
        cu, cd = cross_up[i], cross_dn[i]
        if recross:
            last_up[cu] = i
        old = held.copy()
        entered = (~old) & cu
        exited = old & cd
        held[entered] = True
        held[exited] = False
        last_up[entered] = i
        pool = np.flatnonzero(held & allowed_arr[i])
        if pool.size:
            order = np.argsort(last_up[pool], kind='stable')
            want[i, pool[order[-n:]]] = True
    return pd.DataFrame(want, index=dclose.index, columns=dclose.columns)


def sim(dopen, dclose, want):
    op = dopen.to_numpy(dtype=float)
    cl = dclose.to_numpy(dtype=float)
    selected = want.to_numpy(dtype=bool)
    cash = CAPITAL
    shares = np.zeros(cl.shape[1], dtype=float)
    equity = np.empty(len(cl), dtype=float)
    exposure = np.empty(len(cl), dtype=float)
    trades = 0
    for i in range(len(cl)):
        close_row = cl[i]
        investable = np.isfinite(close_row)
        invested = float(np.sum(shares[investable] * close_row[investable]))
        eq = cash + invested
        equity[i] = eq
        exposure[i] = invested / eq if eq > 0 else 0.0
        if i >= len(cl) - 1:
            continue
        nxt = op[i + 1]
        next_ok = np.isfinite(nxt)
        active = selected[i] & next_ok
        exit_idx = np.flatnonzero((shares > 0) & ~active & next_ok)
        for j in exit_idx:
            cash += shares[j] * nxt[j] * (1 - COST)
            shares[j] = 0.0
            trades += 1
        entry_idx = np.flatnonzero(active & (shares == 0))
        if entry_idx.size:
            per = cash / entry_idx.size
            for j in entry_idx:
                q = per / (nxt[j] * (1 + COST))
                if q > 0:
                    shares[j] = q
                    cash -= q * nxt[j] * (1 + COST)
                    trades += 1
    return equity, exposure, trades


def buy_hold(dclose):
    r = dclose.pct_change(fill_method=None)
    mean = r.mean(axis=1, skipna=True).fillna(0.0)
    return CAPITAL * (1 + mean).cumprod().to_numpy()


def metrics(eq, dates):
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    peak = np.maximum.accumulate(eq)
    r = np.diff(eq) / eq[:-1]
    sd = r.std(ddof=0)
    return dict(total=eq[-1] / eq[0] - 1,
                cagr=(eq[-1] / eq[0]) ** (1 / years) - 1,
                mdd=float((eq / peak - 1).min()),
                sharpe=float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
                final=float(eq[-1]))


def show(label, m, expo, trades):
    print(f'  {label:<26} ret {m["total"]*100:>9.1f}%  CAGR {m["cagr"]*100:>6.2f}%  '
          f'MDD {m["mdd"]*100:>7.2f}%  Sharpe {m["sharpe"]:>5.2f}  '
          f'expo {expo*100:>3.0f}%  trades {trades:>4}  final ${m["final"]:>12,.0f}')


def pit_buy_hold(dclose, active):
    r = dclose.pct_change(fill_method=None)
    prev = active.shift(1).fillna(False)
    mean = r.where(prev).mean(axis=1, skipna=True).fillna(0.0)
    return CAPITAL * (1 + mean).cumprod().to_numpy()


def run_pit_stock(expl_mode='full'):
    end = date.today() - timedelta(days=1)
    active_by_day = build_pit_universe(end, expl_mode=expl_mode)
    symbols = sorted(set().union(*active_by_day.values()))
    dopen, dclose = load('day', symbols)
    _, wclose = load('week', symbols)
    dclose = dclose[dclose.notna().any(axis=1)]
    dopen = dopen.reindex(dclose.index)
    dclose = dclose[dclose.index.normalize() < pd.Timestamp(end + timedelta(days=1))]
    dopen = dopen.reindex(dclose.index)
    wclose = wclose.reindex(columns=dclose.columns)
    active_vals = np.zeros(dclose.shape, dtype=bool)
    row_ix = {d: i for i, d in enumerate(dclose.index)}
    col_ix = {s: i for i, s in enumerate(dclose.columns)}
    for day, names in active_by_day.items():
        ts = pd.Timestamp(day)
        row = row_ix.get(ts)
        if row is None:
            continue
        for sym in names:
            col = col_ix.get(sym)
            if col is not None:
                active_vals[row, col] = True
    active = pd.DataFrame(active_vals, index=dclose.index, columns=dclose.columns)
    static_cols = [s for s in STOCK_POOL if s in dclose.columns]
    s1, _ = states(dopen, dclose, wclose)
    dymi = cached_dymi_panel(dclose, end)
    rank = dymi_pct_rank(dclose, s1 & active, dymi)
    q4_ok = rank.lt(0.75)
    sweep_full = {}
    for cut in (0.90, 0.85, 0.80, 0.75, 0.70, 0.60):
        ok = rank.lt(cut).reindex(index=dclose.index, columns=dclose.columns).fillna(True)
        sweep_full[cut], _ = states(dopen, dclose, wclose, entry_ok=ok)
    bottom_full = {}
    for cut in (0.10, 0.25, 0.50, 0.75):
        ok = rank.gt(cut).reindex(index=dclose.index, columns=dclose.columns).fillna(True)
        bottom_full[cut], _ = states(dopen, dclose, wclose, entry_ok=ok)
    top5 = freshest_top_n(dclose, wclose, 5, allowed=active)
    top5_recross = freshest_top_n(dclose, wclose, 5, recross=True, allowed=active)
    static_s1, _ = states(dopen[static_cols], dclose[static_cols], wclose[static_cols])
    nonempty = active.any(axis=1)
    if not nonempty.any():
        raise SystemExit('PIT universe empty')
    start = nonempty[nonempty].index[0]
    dopen, dclose = dopen.loc[start:], dclose.loc[start:]
    active, wclose = active.loc[start:], wclose.loc[start:]
    s1 = (s1 & active).loc[start:]
    sweep = {cut: (full & active).loc[start:] for cut, full in sweep_full.items()}
    bottom = {cut: (full & active).loc[start:] for cut, full in bottom_full.items()}
    s1_entry = sweep[0.75]
    s1_target = s1 & q4_ok.loc[start:]
    dy_top5_low = dymi_top_n(s1, rank, 5, cut=0.75)
    dy_top5_high = dymi_top_n(s1, rank, 5, cut=0.75, prefer_high=True)
    dy_top10_low = dymi_top_n(s1, rank, 10, cut=0.75)
    top5, top5_recross = top5.loc[start:], top5_recross.loc[start:]
    static_s1 = static_s1.loc[start:]
    label_suffix = {'full': '', 'noexpl': ' (no EXPL)',
                    'wfexpl': ' (walk-forward EXPL)'}[expl_mode]
    print(f'=== S1 portfolio stock PIT five-source universe{label_suffix} ===')
    print(f'Window: {dclose.index[0].date()} -> {dclose.index[-1].date()} '
          f'({len(dclose)} daily bars, union {len(symbols)} names)')
    print(f'PIT universe size: avg {active.sum(axis=1).mean():.1f}, '
          f'last {int(active.iloc[-1].sum())}')
    for label, op, cl, want in (
            ('S1 PIT all-active', dopen, dclose, s1),
            ('S1 PIT Q2-Q4 entries', dopen, dclose, s1_entry),
            ('S1 PIT Q2-Q4 targets', dopen, dclose, s1_target),
            ('S1 PIT DYMI top5 lowest', dopen, dclose, dy_top5_low),
            ('S1 PIT DYMI top5 highest', dopen, dclose, dy_top5_high),
            ('S1 PIT DYMI top10 lowest', dopen, dclose, dy_top10_low),
            ('S1 PIT TOP5 freshest', dopen, dclose, top5),
            ('S1 PIT TOP5 re-cross', dopen, dclose, top5_recross),
            ('S1 static 96 snapshot', dopen[static_cols], dclose[static_cols], static_s1)):
        eq, expo, tr = sim(op, cl, want)
        show(label, metrics(eq, cl.index), expo.mean(), tr)
    base_eq, _, _ = sim(dopen, dclose, s1)
    base_m = metrics(base_eq, dclose.index)
    print(f'\nDYMI top-cut sensitivity (entry gate only; baseline '
          f'{base_m["total"]*100:.1f}% / {base_m["mdd"]*100:.2f}% MDD / '
          f'{base_m["sharpe"]:.2f} Sharpe):', flush=True)
    for cut, want in sweep.items():
        eq, expo, tr = sim(dopen, dclose, want)
        m = metrics(eq, dclose.index)
        print(f'  exclude top {(1-cut)*100:>4.0f}%  ret {m["total"]*100:>8.1f}%  '
              f'MDD {m["mdd"]*100:>7.2f}%  Sharpe {m["sharpe"]:>5.2f}  '
              f'trades {tr:>5}', flush=True)
    print('\nDYMI minimum-rank gate (require percentile > cut):', flush=True)
    for cut, want in bottom.items():
        eq, expo, tr = sim(dopen, dclose, want)
        m = metrics(eq, dclose.index)
        print(f'  require > {cut*100:>4.0f}%  ret {m["total"]*100:>8.1f}%  '
              f'MDD {m["mdd"]*100:>7.2f}%  Sharpe {m["sharpe"]:>5.2f}  '
              f'trades {tr:>5}', flush=True)
    d10, d20 = ema(dclose, 10), ema(dclose, 20)
    cross_up = (np.isfinite(d10) & np.isfinite(d20) & (d10 > d20)
                & (d10.shift(1) <= d20.shift(1))).fillna(False)
    dymi_entry_quartiles('DYMI quartile at true daily EMA10/20 cross-ups '
                         '(rank among held names, fwd from next open):',
                         dopen, cross_up & active, rank)
    dymi_entry_quartiles('DYMI quartile at S1 held-state transitions:',
                         dopen,
                         s1.fillna(False) & ~s1.fillna(False).shift(1).fillna(False),
                         rank)
    eq = pit_buy_hold(dclose, active)
    show('PIT universe EW B&H', metrics(eq, dclose.index), 1.0, len(symbols))
    _, spy_close = load('day', ['SPY'])
    spy_close = spy_close[spy_close.notna().any(axis=1)].reindex(dclose.index)
    spy_ret = spy_close['SPY'].pct_change(fill_method=None).fillna(0.0)
    spy_eq = CAPITAL * (1 + spy_ret).cumprod()
    show('SPY B&H', metrics(spy_eq.to_numpy(), dclose.index), 1.0, 1)
    active_last = active.iloc[-1][active.iloc[-1]].index.tolist()
    print(f'Current PIT active ({len(active_last)}): '
          f'{", ".join(active_last) if active_last else "(none)"}')


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'etf').lower()
    if mode in ('stock-pit', 'stock-pit-noexpl', 'stock-pit-wfexpl'):
        expl_mode = {'stock-pit': 'full', 'stock-pit-noexpl': 'noexpl',
                     'stock-pit-wfexpl': 'wfexpl'}[mode]
        run_pit_stock(expl_mode=expl_mode)
        return
    symbols = ETF_POOL if mode == 'etf' else STOCK_POOL
    dopen, dclose = load('day', symbols)
    _, wclose = load('week', symbols)
    dclose = dclose[dclose.notna().any(axis=1)]
    dopen = dopen.reindex(dclose.index)
    s1, donly = states(dopen, dclose, wclose)
    top5 = freshest_top_n(dclose, wclose, 5)
    top5_recross = freshest_top_n(dclose, wclose, 5, recross=True)
    print(f'=== S1 portfolio {mode} ({len(symbols)} names) ===')
    print(f'Window: {dclose.index[0].date()} -> {dclose.index[-1].date()} '
          f'({len(dclose)} daily bars)')
    for label, want in ((f'S1 EW {mode}', s1), ('S1 TOP5 freshest', top5),
                        ('S1 TOP5 fresh re-cross', top5_recross),
                        (f'Daily-only EW {mode}', donly)):
        eq, expo, tr = sim(dopen, dclose, want)
        show(label, metrics(eq, dclose.index), expo.mean(), tr)
    eq = buy_hold(dclose)
    show(f'EW B&H {mode}', metrics(eq, dclose.index), 1.0, len(symbols))
    _, spy_close = load('day', ['SPY'])
    spy_close = spy_close[spy_close.notna().any(axis=1)]
    spy_close = spy_close.reindex(dclose.index)
    spy_ret = spy_close['SPY'].pct_change(fill_method=None).fillna(0.0)
    spy_eq = CAPITAL * (1 + spy_ret).cumprod()
    show('SPY B&H', metrics(spy_eq.to_numpy(), dclose.index), 1.0, 1)
    active = s1.iloc[-1][s1.iloc[-1]].index.tolist()
    print(f'Current S1 active ({len(active)}): {", ".join(active) if active else "(none)"}')
    top5_active = top5.iloc[-1][top5.iloc[-1]].index.tolist()
    print(f'Current TOP5 freshest ({len(top5_active)}): '
          f'{", ".join(top5_active) if top5_active else "(none)"}')


if __name__ == '__main__':
    main()
