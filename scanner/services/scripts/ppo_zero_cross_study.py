"""PPO zero-line cross: is "exit on the cross, re-enter on the cross" a valid exit?

RESEARCH / WHAT-IF. Not a strategy, not wired to anything live, and not a proposal
to change the live emasma path. Nothing here reads or writes a trade, a pending row
or a timer. It exists so the numbers behind the PPO chart pane's arrows are
reproducible instead of remembered.

Origin: the PPO pane in scanner/index.blade.php + explorer.blade.php was restored
2026-09-30 with green/red arrows on the PPO line's and the signal line's zero
crosses. The question was whether those arrows are worth acting on. Three findings,
all reproduced by this script:

  1. "EITHER line" is a no-op. Across 125/125 signal-line zero crosses, the PPO
     line had already crossed the same way -- the signal is a 9-EMA of the line, so
     it is a strict laggard and can never cross first. The second arrow set adds no
     entries and no exits; it is visual confirmation only.

  2. As a standalone long/flat flip it LOSES to buy & hold over a full cycle
     (QQQ daily 11.8% vs 20.3% CAGR; AAPL daily 4.5% vs 23.3%). But over the 2022
     bear it WINS on QQQ (87.4k vs 69.4k, maxDD -15.0% vs -35.0% on a -30.6% tape)
     and loses on AAPL, whose "bear" was only -12.1%. Bull-vs-bear is the wrong axis.

  3. The right axis is how deep the post-exit drawdown gets. Universe-wide, bucketed
     over 24,625 bearish signal crosses: the exit is dead money below roughly a
     -27% post-exit decline and pays above it (+41.6% given up in the 0..-10%
     bucket, -43.1% avoided below -60%). 64% of all crosses are dead money, and a
     median 23% of a >=35% decline is already gone by the time the cross fires, so
     this is never crash protection -- only "stay out of the rest of it".

The actual argument for a rule-based re-entry is not return, it is that re-entering
on the cross converts unbounded dead money (a discretionary "I'll decide when to get
back") into a bounded distribution: median 40 bars, p90 121, over a year in 7 of
24,625 crosses.

Conventions, per OPERATING_RULES.md:
  - settled bars only: daily date < today; weekly date + 7 <= today. Never live/partial.
  - fills at the NEXT bar's close (no same-bar lookahead)
  - COST = 0.0005 per side, CAPITAL = 100000
  - EMA seeded with an SMA of the first `period` values -- the same convention as the
    chart pane, so this reads the same series the arrows are drawn on
  - results are RELATIVE SIGNAL QUALITY, not returns. Backtest returns in this repo
    are not trustworthy as returns (survivorship, idealized fills, untrimmed winners).
  - universe screen is conditioned on the outcome (it selects declines that
    happened), so it sizes the good cases; it is not a hit rate.

Usage:
    python3 ppo_zero_cross_study.py                      # QQQ/AAPL + universe
    python3 ppo_zero_cross_study.py --symbols CHTR,MSTR # named symbols only
    python3 ppo_zero_cross_study.py --universe           # universe screen only
    python3 ppo_zero_cross_study.py --timeframe weekly

Reads tbl_scanner_tickers_daily -- the same table behind /scanner/data/{ticker} that
the chart pane consumes, so the numbers line up with what the arrows show.

Every price printed in the exit sections is the FILL (the next bar's close), not the
cross bar's close, so it is the price the engine would actually have traded. For
ROKU 2021-08-13 that is 356.50 (the 08-16 close) versus 357.38 on the cross bar.
"""

import argparse
import datetime
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn  # noqa: E402

COST = 0.0005
CAPITAL = 100000
HOT_LOOKBACK = 250
DEEP_DECLINE = -35.0
FWD = 250


# --------------------------------------------------------------------------- #
# indicators
# --------------------------------------------------------------------------- #
def ema_sma_seed(values, period):
    """EMA seeded with an SMA of the first `period` values.

    Matches the chart pane's closeSma40Ema10()/PPO math and the pandas
    ewm(adjust=False) conversion in earnings_screener.py. Returns a same-length
    array, NaN-seeded -- callers must align by index, not by slicing.
    """
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    prev = values[:period].mean()
    out[period - 1] = prev
    mult = 2.0 / (period + 1)
    for i in range(period, len(values)):
        prev = (values[i] - prev) * mult + prev
        out[i] = prev
    return out


def ppo_series(closes, fast=12, slow=26, signal=9):
    """PPO line and signal line, in percent. Both same-length, NaN-seeded."""
    closes = np.asarray(closes, dtype=float)
    e_fast, e_slow = ema_sma_seed(closes, fast), ema_sma_seed(closes, slow)
    with np.errstate(divide='ignore', invalid='ignore'):
        line = np.where(np.isnan(e_slow) | (e_slow == 0), np.nan, (e_fast - e_slow) / e_slow * 100)
    valid = np.where(~np.isnan(line))[0]
    out = np.full(len(closes), np.nan)
    if len(valid):
        out[valid] = ema_sma_seed(line[valid], signal)
    return line, out


def zero_crosses(series):
    """{bar_index: +1 bullish / -1 bearish} for sign changes through zero."""
    s = np.asarray(series, dtype=float)
    ok = np.isfinite(s[1:]) & np.isfinite(s[:-1])
    up = np.where(ok & (s[:-1] <= 0) & (s[1:] > 0))[0] + 1
    dn = np.where(ok & (s[:-1] >= 0) & (s[1:] < 0))[0] + 1
    events = {int(i): 1 for i in up}
    events.update({int(i): -1 for i in dn})
    return events


def merge_events(a, b):
    """Union of two event maps; a bearish collision wins (risk first)."""
    out = dict(a)
    for i, d in b.items():
        out[i] = -1 if (i in out and out[i] != d) else d
    return out


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def is_settled(date, timeframe):
    today = datetime.date.today()
    if timeframe == 'daily':
        return date < today
    return date + datetime.timedelta(days=7) <= today


def load_symbols(symbols, timeframe='daily'):
    conn = get_db_conn()
    cur = conn.cursor()
    table = ('tbl_scanner_tickers_daily' if timeframe == 'daily' else 'tbl_scanner_tickers')
    out = {}
    try:
        for sym in symbols:
            cur.execute(
                f"SELECT d.date, d.close FROM {table} d "          # noqa: S608 - fixed table names
                "JOIN tbl_stock_tickers t ON t.id = d.ticker_id "
                "WHERE t.symbol = %s ORDER BY d.date", (sym,))
            rows = [r for r in cur.fetchall() if is_settled(r[0], timeframe)]
            out[sym] = ([r[0] for r in rows], np.array([float(r[1]) for r in rows]))
    finally:
        conn.close()
    return out


def load_universe(min_bars=400, etfs=False):
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT t.symbol, d.date, d.close
              FROM tbl_scanner_tickers_daily d
              JOIN tbl_stock_tickers t ON t.id = d.ticker_id
             WHERE d.date < current_date AND t.is_etf = %s
             ORDER BY t.symbol, d.date
        """, (etfs,))
        rows = cur.fetchall()
    finally:
        conn.close()
    series = {}
    for sym, dt, cl in rows:
        series.setdefault(sym, ([], []))
        series[sym][0].append(dt)
        series[sym][1].append(float(cl))
    return {s: (d, np.array(c)) for s, (d, c) in series.items() if len(c) >= min_bars}


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
def run_flip(closes, events):
    """long <-> cash on the event, filled at the NEXT bar's close.

    Mark-to-market compounds the incremental bar-over-bar move while holding, so
    equity accrues exactly once per bar held. An open leg is marked to the last
    settled close and flagged.
    """
    equity, in_market, entry, prev = CAPITAL, False, None, None
    curve, trades, pending = [], [], None
    for i, px in enumerate(closes):
        if in_market and prev is not None:
            equity *= px / prev
        if pending == 'buy' and not in_market:
            equity *= (1 - COST)
            in_market, entry = True, px
            trades.append({'dir': 'buy', 'i': i, 'px': float(px)})
        elif pending == 'sell' and in_market:
            equity *= (1 - COST)
            trades.append({'dir': 'sell', 'i': i, 'px': float(px), 'ret': float(px / entry - 1)})
            in_market, entry = False, None
        prev = px
        curve.append(equity)
        pending = None
        direction = events.get(i)
        if direction == 1 and not in_market:
            pending = 'buy'
        elif direction == -1 and in_market:
            pending = 'sell'
    if in_market:
        trades.append({'dir': 'sell', 'i': len(closes) - 1, 'px': float(closes[-1]),
                       'ret': float(closes[-1] / entry - 1), 'open': True})
    return equity, curve, trades


def max_drawdown(curve):
    peak, worst = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return 100 * worst


def summarize(label, equity, curve, trades, dates):
    rets = [t['ret'] for t in trades if t['dir'] == 'sell']
    open_leg = any(t.get('open') for t in trades)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    years = (dates[-1] - dates[0]).days / 365.25
    cagr = (equity / CAPITAL) ** (1 / years) - 1 if years > 0 and equity > 0 else float('nan')
    return {
        'label': label,
        'final': equity,
        'n': len(rets) - (1 if open_leg else 0),
        'open': open_leg,
        'win': 100 * len(wins) / len(rets) if rets else float('nan'),
        'dd': max_drawdown(curve),
        'cagr': 100 * cagr,
        'avg_win': 100 * np.mean(wins) if wins else float('nan'),
        'avg_loss': 100 * np.mean(losses) if losses else float('nan'),
    }


def fmt(summary_row):
    def f(key):
        v = summary_row[key]
        return f'{v:6.1f}%' if v == v else '   n/a'
    n = str(summary_row['n']) + ('*' if summary_row['open'] else ' ')
    return (f"{summary_row['label']:<20}{summary_row['final']:>11,.0f} {n:>4}"
            f"{f('win'):>8}{f('dd'):>9}{f('cagr'):>9}{f('avg_win'):>9}{f('avg_loss'):>10}")


# --------------------------------------------------------------------------- #
# per-symbol sections
# --------------------------------------------------------------------------- #
def section_flip(sym, dates, closes, timeframe):
    """A/B/D: PPO-line cross vs signal-line cross vs "either" vs buy & hold."""
    line, sig = ppo_series(closes)
    ev_line, ev_sig = zero_crosses(line), zero_crosses(sig)
    print(f'\n=== {sym} {timeframe}  {dates[0]} -> {dates[-1]}  ({len(closes)} settled bars) ===')
    print(f'{"variant":<20}{"final$":>11} {"n":>4}{"win":>8}{"maxDD":>9}'
          f'{"CAGR":>9}{"avgWin":>9}{"avgLoss":>10}')
    rows = []
    for label, ev in [('A ppo-line cross', ev_line), ('B signal cross', ev_sig),
                      ('C either cross', merge_events(ev_line, ev_sig))]:
        equity, curve, trades = run_flip(closes, ev)
        rows.append(summarize(label, equity, curve, trades, dates))
    equity, curve, trades = run_flip(closes, {0: 1})          # buy & hold, same convention
    rows.append(summarize('D buy & hold', equity, curve, trades, dates))
    for row in rows:
        print(fmt(row))
    print(f'  zero crosses: ppo-line={len(ev_line)}  signal={len(ev_sig)}  '
          f'either={len(merge_events(ev_line, ev_sig))}   (* = open leg at the last settled bar)')


def section_exit_value(sym, dates, closes, ev):
    """Per exit: what the exit dodged vs what it gave up, and how much was already gone."""
    print(f'\n--- {sym}: per-exit forward return from the exit price ---')
    print(f'{"exit":<12}{"@close":>9}' + ''.join(f'{"fwd+"+str(h):>9}' for h in (20, 60, 120, 250))
          + f'{"minDD":>8}{"recovered":>11}')
    buckets = {h: [] for h in (20, 60, 120, 250)}
    mins, recovered = [], 0
    for i in sorted(k for k, v in ev.items() if v == -1):
        entry = i + 1
        if entry >= len(closes):
            continue
        px = closes[entry]
        row = []
        for h in (20, 60, 120, 250):
            fwd = 100 * (closes[min(entry + h, len(closes) - 1)] / px - 1)
            row.append(fwd)
            buckets[h].append(fwd)
        window = closes[entry:min(entry + 250, len(closes))]
        low = 100 * (window.min() / px - 1)
        mins.append(low)
        recovered += window.max() >= px
        print(f'{ds(dates[entry]):<12}{px:>9.2f}' + ''.join(f'{v:>9.1f}' for v in row)
              + f'{low:>8.1f}{("yes" if window.max() >= px else "NO"):>11}')
    if not mins:
        return
    n = len(mins)
    print(f'{"MEAN":<12}{"":>9}' + ''.join(f'{np.mean(buckets[h]):>9.1f}'
                                           for h in (20, 60, 120, 250))
          + f'{np.mean(mins):>8.1f}{100*recovered/n:>10.0f}%')
    for h in (60, 250):
        v = buckets[h]
        good = [x for x in v if x < 0]
        bad = [x for x in v if x > 0]
        print(f'   fwd+{h:<4} avoided a loss: {len(good):>3}/{len(v)}'
              + (f' mean {np.mean(good):+.1f}%' if good else '')
              + f'   gave up upside: {len(bad):>3}/{len(v)}'
              + (f' mean {np.mean(bad):+.1f}%' if bad else '')
              + f'   net per exit {np.mean(v):+.1f}%')


def section_roundtrip(sym, dates, closes, ev_up, ev_dn):
    """Of each round trip: decline already given back at the exit vs dodged after it."""
    print(f'\n--- {sym}: round-trip split (the exit cannot beat its own lag) ---')
    print(f'{"entry":<12}{"exit":<12}{"peak":>9}{"exitpx":>9}{"trough":>9}'
          f'{"gaveBack":>10}{"dodged":>9}{"captured":>10}')
    gave, dodged, captured = [], [], []
    for bi in sorted(ev_up):
        later = [j for j in sorted(ev_dn) if j > bi]
        if not later or bi + 1 >= len(closes):
            continue
        si = later[0]
        if si + 1 >= len(closes):
            continue
        in_px, out_px = closes[bi + 1], closes[si + 1]
        peak = closes[bi + 1:si + 1].max()
        trough = closes[si + 1:min(si + 1 + FWD, len(closes))].min()
        gb = 100 * (1 - out_px / peak)
        dd = 100 * (1 - trough / out_px)
        cap = 100 * dd / (gb + dd) if (gb + dd) > 0 else float('nan')
        gave.append(gb); dodged.append(dd); captured.append(cap)
        print(f'{ds(dates[bi+1]):<12}{ds(dates[si+1]):<12}{peak:>9.2f}{out_px:>9.2f}{trough:>9.2f}'
              f'{gb:>9.1f}%{dd:>8.1f}%{cap:>9.0f}%')
    if gave:
        c = [x for x in captured if x == x]
        print(f'{"MEAN":<24}{"":>27}{np.mean(gave):>9.1f}%{np.mean(dodged):>8.1f}%'
              f'{(np.mean(c) if c else float("nan")):>9.0f}%')
        print('  captured% is low on whipsaw round trips with no decline to catch '
              '(0%); it is the point of the exercise on the ones that matter.')


def section_reentry(sym, dates, closes, ev_up, ev_dn):
    """Is the re-cross 'not too late'? Where it lands between trough and old peak."""
    print(f'\n--- {sym}: re-entry lateness ---')
    print(f'{"exit":<12}{"re-entry":<12}{"bars":>6}{"%offPeak":>10}{"%aboveTrough":>14}')
    lags, off, above = [], [], []
    for si in sorted(ev_dn):
        later = [j for j in sorted(ev_up) if j > si]
        if not later or si + 1 >= len(closes) or later[0] + 1 >= len(closes):
            continue
        ri = later[0]
        out_px, in_px = closes[si + 1], closes[ri + 1]
        segment = closes[si + 1:ri + 1]
        if not len(segment):
            continue
        prior = closes[max(0, si - 60):si + 1]
        peak = prior.max() if len(prior) else out_px
        lags.append(ri - si)
        off.append(100 * (1 - in_px / peak))
        above.append(100 * (in_px / segment.min() - 1))
        print(f'{ds(dates[si+1]):<12}{ds(dates[ri+1]):<12}{ri-si:>6}'
              f'{100*(1-in_px/peak):>9.1f}%{100*(in_px/segment.min()-1):>13.1f}%')
    if lags:
        print(f'{"MEAN":<12}{"":<12}{np.mean(lags):>6.0f}{np.mean(off):>9.1f}%'
              f'{np.mean(above):>13.1f}%')


def section_dead_money(sym, dates, closes, ev):
    """Orphan signals and every flat bar attributed to a reason.

    warmup   flat only because the EMAs are not seeded yet (backtest artifact; live
             EMAs are already seeded from prior history)
    orphan   flat because a bearish cross fired with no position to sell
    wait     flat after a real exit, waiting for the re-buy
    stranded flat at the window's end with the re-buy still to come
    """
    n = len(closes)
    events = sorted(ev)
    first = events[0] if events else None
    reason, in_market, exits, gaps = None, False, [], []
    orphan_sell, orphan_buy = [], []
    per_bar = [None] * n
    for i in range(n):
        if first is None or i < first:
            per_bar[i] = 'warmup'
            reason = 'warmup'
        else:
            per_bar[i] = 'long' if in_market else (reason or 'orphan')
        direction = ev.get(i)
        if direction == 1 and not in_market:
            if reason == 'wait':
                gaps.append((exits[-1], i))
                reason = 'stranded'
            in_market, reason = True, None
        elif direction == 1 and in_market:
            orphan_buy.append(i)
        elif direction == -1 and in_market:
            exits.append(i)
            in_market, reason = False, 'wait'
        elif direction == -1 and not in_market:
            orphan_sell.append(i)
            if first is not None and i >= first:
                reason = 'orphan'
    if reason == 'wait':
        gaps.append((exits[-1], n - 1))

    bearish = [d for d in ev.values() if d == -1]
    counts = {}
    for tag in per_bar:
        if tag:
            counts[tag] = counts.get(tag, 0) + 1
    total = sum(counts.values())
    opener = 'SELL (orphan, no prior buy)' if ev and ev[first] == -1 else 'BUY'
    print(f'\n--- {sym}: orphan signals and dead money ---')
    print(f'  first signal: {opener}' + (f' on {dates[first]}' if first is not None else ' (none)'))
    print(f'  bearish crosses {len(bearish)}: acted on {len(exits)}, '
          f"ORPHAN sells {len(orphan_sell)} "
          f"{', '.join(ds(dates[x]) for x in orphan_sell) if orphan_sell else ''}")
    print(f'  bullish crosses {len(ev) - len(bearish)}: ORPHAN buys (already long) '
          f'{len(orphan_buy)}'
          f"{' ' + ', '.join(ds(dates[i]) for i in orphan_buy) if orphan_buy else ''}")
    for tag in ('long', 'wait', 'orphan', 'warmup', 'stranded'):
        if counts.get(tag):
            print(f'    {tag:<9}{counts[tag]:>6} bars  {100*counts[tag]/total:>5.1f}%')
    dead = total - counts.get('long', 0)
    print(f'    => DEAD MONEY (flat, nothing deployed): {dead} bars = {100*dead/total:.1f}%')
    if gaps:
        days = sorted((dates[min(b, n - 1)] - dates[a]).days for a, b in gaps)
        print(f'  exit -> re-buy gaps (n={len(gaps)}): median {days[len(days)//2]}d  '
              f'p90 {days[int(0.9*(len(days)-1))]}d  max {max(days)}d')
        over = [x for x in days if x > 365]
        print(f'    gaps over a year: {len(over)}' + (f' {over}' if over else ' (none)'))


def section_symbol(sym, dates, closes, timeframe):
    line, sig = ppo_series(closes)
    ev_line, ev_sig = zero_crosses(line), zero_crosses(sig)
    ev = ev_sig                                     # variant B: the better of the two
    section_flip(sym, dates, closes, timeframe)
    section_exit_value(sym, dates, closes, ev)
    section_roundtrip(sym, dates, closes, zero_crosses_line(ev, 1), zero_crosses_line(ev, -1))
    section_reentry(sym, dates, closes, zero_crosses_line(ev, 1), zero_crosses_line(ev, -1))
    section_dead_money(sym, dates, closes, ev)


def zero_crosses_line(events, direction):
    return {i: d for i, d in events.items() if d == direction}


def ds(date):
    """ISO date for printing.

    datetime.date.__format__ delegates to strftime, which passes unknown format
    characters through verbatim -- so '{d:<12}' renders the literal '<12' instead of
    padding. Always format dates through str().
    """
    return date.isoformat() if hasattr(date, 'isoformat') else str(date)


# --------------------------------------------------------------------------- #
# universe sections
# --------------------------------------------------------------------------- #
def section_signal_lag(series):
    """CLAIM 1 -- a laggard cannot lead. How often does the signal cross first?"""
    ahead = behind = 0
    for dates, closes in series.values():
        line, sig = ppo_series(closes)
        ev_line, ev_sig = zero_crosses(line), zero_crosses(sig)
        for i, d in ev_sig.items():
            if any(j <= i and ev_line[j] == d for j in ev_line):
                behind += 1
            else:
                ahead += 1
    print(f'\nCLAIM 1 -- signal zero crosses where the PPO line had NOT already crossed: '
          f'{ahead}')
    print(f'  signal cross is a strict laggard: {behind}/{behind + ahead} = '
          f'{100*behind/max(behind+ahead,1):.0f}% arrive second, so "either" == "line"')


def section_universe_buckets(series):
    """CLAIM 2 -- the exit is only worth arming past a ~-27% post-exit decline."""
    recs = []
    for dates, closes in series.values():
        line, sig = ppo_series(closes)
        ev_line, ev_sig = zero_crosses(line), zero_crosses(sig)
        bull = np.array(sorted(i for i, d in ev_sig.items() if d == 1))
        n = len(closes)
        for i, d in ev_sig.items():
            if d != -1 or i + 1 >= n:
                continue
            px = closes[i + 1]
            window = closes[i + 1:min(i + 1 + FWD, n)]
            if len(window) < 60:
                continue
            later = bull[bull > i]
            recs.append({
                'fwd': 100 * (closes[min(i + 1 + FWD, n - 1)] / px - 1),
                'dd': 100 * (window.min() / px - 1),
                'rebars': int(later[0] - i) if len(later) else None,
            })
    print(f'\nCLAIM 2 -- {len(recs):,} bearish signal crosses, bucketed by the decline that follows')
    print(f'{"post-exit DD":<15}{"n":>7}{"fwd+250":>10}{"verdict":>12}{"flat bars":>11}{"flat >1y":>10}')
    edges = [(0, -10), (-10, -20), (-20, -30), (-30, -40), (-40, -60), (-60, -1000)]
    for lo, hi in edges:
        sel = [r for r in recs if hi < r['dd'] <= lo]
        if not sel:
            continue
        fwd = np.array([r['fwd'] for r in sel])
        rb = [r['rebars'] for r in sel if r['rebars'] is not None]
        year = sum(1 for x in rb if x > 252)
        print(f'{f"{lo} to {hi}%":<15}{len(sel):>7}{fwd.mean():>9.1f}%'
              f'{("exit PAID" if fwd.mean() < 0 else "exit COST"):>12}'
              f'{(np.mean(rb) if rb else float("nan")):>11.0f}{year:>10}')
    allf = np.array([r['fwd'] for r in recs])
    print(f'{"ALL":<15}{len(recs):>7}{allf.mean():>9.1f}%{"mixed":>12}')
    print(f'  share of crosses that were dead money (fwd+250 > 0): {100*(allf > 0).mean():.0f}%')


def section_universe_lag_cost(series):
    """CLAIM 1 quantified -- how much of a real decline is gone before the cross fires."""
    shares = []
    for sym, (dates, closes) in series.items():
        line, sig = ppo_series(closes)
        n = len(closes)
        for i, d in zero_crosses(sig).items():
            if d != -1 or i < 60 or i + 1 >= n:
                continue
            window = closes[i + 1:min(i + 1 + FWD, n)]
            if len(window) < 60:
                continue
            if 100 * (window.min() / closes[i + 1] - 1) > DEEP_DECLINE:
                continue
            peak = closes[max(0, i - 60):i + 1].max()
            if peak <= closes[i + 1]:
                continue
            gave = 100 * (1 - closes[i + 1] / peak)
            avoided = abs(100 * (window.min() / closes[i + 1] - 1))
            if gave + avoided > 0:
                shares.append(100 * gave / (gave + avoided))
    shares = np.array(shares)
    print(f'\nCLAIM 1 quantified -- of a >={abs(DEEP_DECLINE):.0f}% post-exit decline, '
          f'share ALREADY gone at the cross')
    print(f'  n={len(shares)}  median {np.median(shares):.0f}%  '
          f'p25 {np.percentile(shares, 25):.0f}%  p75 {np.percentile(shares, 75):.0f}%')
    print(f'  => the exit can address the other {100-np.median(shares):.0f}% at best. '
          f'This is not crash protection.')


def section_hot_to_cold(series, top=15):
    """The case the exit exists for: hot, then cold. Conditioned on the outcome,
    so this sizes the good cases -- it is NOT a hit rate."""
    cands = []
    for sym, (dates, closes) in series.items():
        n = len(closes)
        if n < HOT_LOOKBACK + 350:
            continue
        line, sig = ppo_series(closes)
        bull = np.array(sorted(i for i, d in zero_crosses(sig).items() if d == 1))
        for i, d in zero_crosses(sig).items():
            if d != -1 or i < HOT_LOOKBACK or i + 1 >= n:
                continue
            was_hot = 100 * (closes[i] / closes[i - HOT_LOOKBACK] - 1)
            if was_hot < 50:
                continue
            window = closes[i + 1:min(i + 1 + FWD, n)]
            if len(window) < 60:
                continue
            went_cold = 100 * (window.min() / closes[i + 1] - 1)
            if went_cold > DEEP_DECLINE:
                continue
            later = bull[bull > i]
            cands.append({
                'sym': sym, 'exit': dates[i], 'px': closes[i + 1], 'hot': was_hot,
                'cold': went_cold, 'rebars': int(later[0] - i) if len(later) else None,
                'regained': 100 * (closes[min(i + 1 + FWD, n - 1)] / closes[i + 1] - 1),
            })
    cands.sort(key=lambda r: r['cold'])
    print(f'\nHOT -> COLD -- {len(cands)} episodes universe-wide '
          f'(run-up >=+50%, then >={abs(DEEP_DECLINE):.0f}% after the cross). '
          f'Conditioned on the outcome: sizes the wins, not a hit rate.')
    print(f'{"sym":<8}{"exit":<12}{"px":>9}{"was_hot":>9}{"went_cold":>11}'
          f'{"rebars":>8}{"1y later":>10}')
    for r in cands[:top]:
        reb = 'never' if r['rebars'] is None else str(r['rebars'])
        print(f'{r["sym"]:<8}{ds(r["exit"]):<12}{r["px"]:>9.2f}{r["hot"]:>8.0f}%'
              f'{r["cold"]:>10.0f}%{reb:>8}{r["regained"]:>9.0f}%')
    if cands:
        rb = [r['rebars'] for r in cands if r['rebars'] is not None]
        noregen = sum(1 for r in cands if r['regained'] < 0)
        print(f'  still below the exit price 1y later: {noregen}/{len(cands)} = '
              f'{100*noregen/len(cands):.0f}%')
        if rb:
            print(f'  re-buy gap bars: median {int(np.median(rb))} ({np.median(rb)/252:.2f}y)  '
                  f'p90 {int(np.percentile(rb, 90))}  max {max(rb)} ({max(rb)/252:.2f}y)')


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--symbols', default='QQQ,AAPL',
                    help='comma-separated tickers for the per-symbol sections')
    ap.add_argument('--timeframe', default='daily', choices=['daily', 'weekly'])
    ap.add_argument('--universe', action='store_true',
                    help='also run the universe screen (slow, ~24k crosses)')
    ap.add_argument('--etfs', action='store_true', help='include ETFs in the universe screen')
    args = ap.parse_args()

    print('PPO zero-line cross study -- RESEARCH / WHAT-IF, not a live strategy.')
    print('Relative signal quality only; backtest returns here are not trustworthy as returns.')

    symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    for sym in symbols:
        data = load_symbols([sym], args.timeframe).get(sym)
        if not data or len(data[1]) < 300:
            print(f'\n(skipped {sym}: fewer than 300 settled {args.timeframe} bars)')
            continue
        section_symbol(sym, data[0], data[1], args.timeframe)

    if args.universe:
        print(f'\n{"="*78}\nUNIVERSE SCREEN (settled daily, non-ETF)' if not args.etfs
              else f'\n{"="*78}\nUNIVERSE SCREEN (settled daily, incl. ETFs)')
        series = load_universe(etfs=args.etfs)
        print(f'{len(series)} tickers with enough history')
        section_signal_lag(series)
        section_universe_lag_cost(series)
        section_universe_buckets(series)
        section_hot_to_cold(series)


if __name__ == '__main__':
    main()
