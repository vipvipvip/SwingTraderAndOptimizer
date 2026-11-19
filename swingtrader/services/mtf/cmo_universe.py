from __future__ import annotations

import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(BASE_DIR, '..', '..', '..'))
COMMON_SCRIPTS = os.path.join(ROOT, 'common', 'scripts')
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if COMMON_SCRIPTS not in sys.path:
    sys.path.insert(0, COMMON_SCRIPTS)

import config  # noqa: E402
import db as db_module  # noqa: E402
import imminent_probability as ip  # noqa: E402

TAKEOFF_W = {
    'std20': 1.7,
    'maxrange8': 1.65,
    'low52': 1.65,
    'atr': 1.65,
    'expcount': 1.6,
    'dip8': 1.5,
    'rng_c': 1.5,
    'c2s': 1.3,
    'ret20': 1.1,
}


def ewm(series, span):
    return series.ewm(span=span, adjust=False).mean()


def load_panels(sig_date, conn=None):
    own = conn is None
    conn = conn or db_module.get_conn()
    try:
        weekly = pd.read_sql(
            "select k.symbol sym, p.date, p.open, p.high, p.low, p.close, p.volume "
            "from tbl_prices_weekly p join tbl_stock_tickers k on k.id=p.ticker_id "
            "where k.enabled and not k.is_etf and p.date::date <= %s::date order by 1,2",
            conn, params=(sig_date,))
        daily = pd.read_sql(
            "select k.symbol sym, p.date, p.close, p.atr_stop "
            "from tbl_prices_daily p join tbl_stock_tickers k on k.id=p.ticker_id "
            "where k.enabled and not k.is_etf and p.date::date <= %s::date order by 1,2",
            conn, params=(sig_date,))
    finally:
        if own:
            conn.close()

    for col in ('open', 'high', 'low', 'close', 'volume'):
        weekly[col] = weekly[col].astype(float)
    for col in ('close', 'atr_stop'):
        daily[col] = daily[col].astype(float)
    weekly['date'] = pd.to_datetime(weekly['date']).dt.date
    daily['date'] = pd.to_datetime(daily['date']).dt.date

    wp = {c: weekly.pivot(index='date', columns='sym', values=c)
          for c in ('close', 'high', 'low', 'volume')}
    dp = {c: daily.pivot(index='date', columns='sym', values=c)
          for c in ('close', 'atr_stop')}
    return wp, dp


def weekly_indicators(wp):
    px = wp['close']
    return ewm(px, 10), px.rolling(40).mean(), ewm(px, 40)


def build_rs(wp, dp, ema10, sma40, ema40):
    px, hi, lo, vol = wp['close'], wp['high'], wp['low'], wp['volume']
    dv = (px * vol).rolling(26).mean()
    liq = (px >= 10) & (dv >= 5e6)
    rank_fn = lambda frame: frame.where(liq).rank(axis=1, pct=True)
    rank = (0.5 * rank_fn(px.pct_change(13))
            + 0.3 * rank_fn(px.pct_change(26))
            + 0.2 * rank_fn(px.pct_change(52))).rank(axis=1, pct=True)
    base = rank.shift(2).rolling(12).mean()
    base_event = (rank >= .8) & (rank.shift(1) < .8) & (base < .5)
    up = (ema10 > sma40) & sma40.notna()
    cross = up & ~up.shift(1, fill_value=False) & sma40.shift(1).notna()
    pos = pd.DataFrame(
        np.where(cross, np.arange(len(px))[:, None], np.nan),
        index=px.index, columns=px.columns).ffill()
    age = pd.DataFrame(
        np.arange(len(px))[:, None] - pos.values,
        index=px.index, columns=px.columns).where(up)
    base_pos = pd.DataFrame(
        np.where(base_event, np.arange(len(px))[:, None], np.nan),
        index=px.index, columns=px.columns).ffill()
    base_age = pd.DataFrame(
        np.arange(len(px))[:, None] - base_pos.values,
        index=px.index, columns=px.columns)
    base_flag = base_age <= 8
    macd = ema10 - ema40
    daily_close = dp['close']
    daily_e10 = daily_close.apply(lambda s: ewm(s, 10))
    daily_e40 = daily_close.apply(lambda s: ewm(s, 40))
    daily_diff = daily_e10 - daily_e40
    daily_hist = (daily_diff - daily_diff.ewm(span=400, adjust=False).mean()).where(
        daily_close.notna().cumsum() >= 440)
    daily_dates = np.array(daily_close.index, dtype=object)
    out = {}
    for k, week in enumerate(px.index):
        j = np.searchsorted(daily_dates, week + timedelta(days=4), side='right') - 1
        if j < 0:
            out[week] = set()
            continue
        row = daily_hist.iloc[j].reindex(px.columns)
        mask = ((rank.iloc[k] >= .8) & (age.iloc[k] <= 8)
                & base_flag.iloc[k] & (row > 0))
        out[week] = set(px.columns[mask.values])
    return out


def build_mtf(px, ema10, sma40, ema40):
    n, m = px.shape
    eligible = np.zeros((n, m), dtype=bool)
    cols = px.columns
    for ci, sym in enumerate(cols):
        e = ema10[sym].to_numpy(dtype=float)
        s = sma40[sym].to_numpy(dtype=float)
        e40 = ema40[sym].to_numpy(dtype=float)
        cross = np.where((e > s) & (np.r_[False, e[:-1] <= s[:-1]]))[0]
        macd = e - e40
        macd_up = np.where((macd > 0) & (np.r_[False, macd[:-1] <= 0]))[0]
        for k in range(n):
            if not np.isfinite(e[k]) or not np.isfinite(s[k]) or k < 60 or e[k] <= s[k]:
                continue
            prev = cross[cross <= k]
            if len(prev) == 0:
                continue
            c = prev[-1]
            if np.any((macd_up >= c - 5) & (macd_up <= c + 5)):
                eligible[k, ci] = True
    out = {}
    for k, week in enumerate(px.index):
        gap = ((px.iloc[k].to_numpy(dtype=float) - sma40.iloc[k].to_numpy(dtype=float))
               / sma40.iloc[k].to_numpy(dtype=float) * 100)
        score = np.minimum(gap / 5.0, 5.0)
        valid = eligible[k] & np.isfinite(score)
        idx = np.where(valid)[0]
        idx = sorted(idx, key=lambda i: (-score[i], cols[i]))[:25]
        out[week] = {cols[i] for i in idx}
    return out


def build_takeoff(wp):
    px, hi, lo = wp['close'], wp['high'], wp['low']
    dates = np.array(px.index, dtype=object)
    scores = np.full(px.shape, np.nan)
    for ci, sym in enumerate(px.columns):
        c = px[sym].astype(float)
        h = hi[sym].astype(float)
        low = lo[sym].astype(float)
        e10 = ewm(c, 10)
        s40 = c.rolling(40).mean()
        rets = c.pct_change()
        cross = np.where((e10 >= s40) & (e10.shift(1) < s40.shift(1)))[0]
        for k in range(45, len(c)):
            if not np.isfinite(s40.iloc[k]) or not np.isfinite(e10.iloc[k]) or e10.iloc[k] < s40.iloc[k]:
                continue
            prev = cross[cross <= k]
            if len(prev) == 0:
                continue
            start = prev[-1]
            since = (dates[k] - dates[start]).days / 7.0
            if since > 12:
                continue
            pre = slice(max(0, k - 8), k - 1)
            rs = rets.iloc[max(0, k - 20):k - 1]
            feat = {
                'std20': rs.std() * 100,
                'maxrange8': (h.iloc[pre] / low.iloc[pre]).max(),
                'expcount': int(((h.iloc[max(0, k - 5):k - 1]
                                  / low.iloc[max(0, k - 5):k - 1]) >= 1.10).sum()),
                'atr': (h.iloc[max(0, k - 20):k].sub(low.iloc[max(0, k - 20):k])).mean()
                       / c.iloc[k] * 100,
                'dip8': (1 - low.iloc[pre].min() / c.iloc[k]) * 100,
                'rng_c': h.iloc[k] / low.iloc[k],
                'c2s': c.iloc[k] / s40.iloc[k],
                'ret20': (c.iloc[k] / c.iloc[max(0, k - 20)] - 1) * 100,
                'low52': c.iloc[k] / c.iloc[max(0, k - 52):k - 1].min(),
            }
            if any(not np.isfinite(v) for v in feat.values()):
                continue
            scores[k, ci] = sum(TAKEOFF_W[f] * feat[f] for f in TAKEOFF_W)
    out = {}
    for k, week in enumerate(px.index):
        row = scores[k]
        idx = np.where(np.isfinite(row))[0]
        idx = sorted(idx, key=lambda i: (-row[i], px.columns[i]))[:25]
        out[week] = {px.columns[i] for i in idx}
    return out


def build_expl(px):
    panel = ip.feature_panel()
    panel = panel[panel['symbol'].isin(px.columns)]
    bundle = ip.load_model()
    out = {}
    for week in px.index:
        try:
            picks = ip.select(panel, week, bundle=bundle, top_n=10, min_dvol=50e6)
        except Exception as exc:
            print(f'[CMO-UNIVERSE] EXPL select failed for {week}: {exc}', flush=True)
            picks = pd.DataFrame()
        out[week] = set(picks['symbol']) if not picks.empty else set()
    return out


def build_daily_signal(wp, dp, weekly_e10, weekly_sma40):
    daily_close = dp['close']
    atr = dp['atr_stop']
    de10 = daily_close.apply(lambda s: ewm(s, 10))
    de40 = daily_close.apply(lambda s: ewm(s, 40))
    daily_dates = np.array(daily_close.index, dtype=object)
    weekly_dates = np.array(wp['close'].index, dtype=object)
    week_pos = np.searchsorted(weekly_dates, daily_dates - timedelta(days=7), side='right') - 1
    candidates = [[] for _ in daily_dates]
    for sym in daily_close.columns:
        close = daily_close[sym].to_numpy(dtype=float)
        daily_atr = atr[sym].to_numpy(dtype=float)
        e = de10[sym].to_numpy(dtype=float)
        s = de40[sym].to_numpy(dtype=float)
        we = weekly_e10[sym].to_numpy(dtype=float)
        ws = weekly_sma40[sym].to_numpy(dtype=float)
        wc = wp['close'][sym].to_numpy(dtype=float)
        cross = np.where((we > ws) & (np.r_[False, we[:-1] <= ws[:-1]]))[0]
        last = np.full(len(we), np.nan)
        for k in cross:
            last[k:] = k
        days = np.full(len(we), 999.0)
        for k in range(len(we)):
            if np.isfinite(last[k]):
                days[k] = (weekly_dates[k] - weekly_dates[int(last[k])]).days
        for j in range(len(daily_dates)):
            k = week_pos[j]
            if k < 0 or not np.isfinite(e[j]) or not np.isfinite(s[j]):
                continue
            if not np.isfinite(we[k]) or not np.isfinite(ws[k]) or we[k] <= ws[k] or e[j] <= s[j]:
                continue
            gap = (wc[k] - ws[k]) / ws[k] * 100
            ad = ((close[j] - daily_atr[j]) / close[j] * 100
                  if np.isfinite(daily_atr[j]) and daily_atr[j] > 0 else 0.0)
            score = min(gap / 20.0, 3.0) + min(ad / 1.5, 3.0) + max(0.0, 2.0 - days[k] / 60.0)
            candidates[j].append((score, sym))
    out = {}
    for j, day in enumerate(daily_dates):
        top = sorted(candidates[j], key=lambda x: (-x[0], x[1]))[:25]
        out[day] = {sym for _, sym in top}
    return out


def active_universe(sig_date, conn=None):
    wp, dp = load_panels(sig_date, conn=conn)
    weekly_e10, weekly_sma40, weekly_e40 = weekly_indicators(wp)
    rs = build_rs(wp, dp, weekly_e10, weekly_sma40, weekly_e40)
    mtf = build_mtf(wp['close'], weekly_e10, weekly_sma40, weekly_e40)
    takeoff = build_takeoff(wp)
    expl = build_expl(wp['close'])
    daily_signal = build_daily_signal(wp, dp, weekly_e10, weekly_sma40)

    weeks = sorted(set(rs) | set(mtf) | set(takeoff) | set(expl))
    valid = [w for w in weeks if w + timedelta(days=7) <= sig_date < w + timedelta(days=14)]
    week = max(valid) if valid else None
    active = set(daily_signal.get(sig_date, set()))
    if week is not None:
        for src in (rs, mtf, takeoff, expl):
            active |= src.get(week, set())

    counts = {
        'rs': len(rs.get(week, set())) if week else 0,
        'mtf': len(mtf.get(week, set())) if week else 0,
        'takeoff': len(takeoff.get(week, set())) if week else 0,
        'expl': len(expl.get(week, set())) if week else 0,
        'dsignal': len(daily_signal.get(sig_date, set())),
    }
    return {
        'date': sig_date,
        'week': week,
        'symbols': active,
        'counts': counts,
    }
