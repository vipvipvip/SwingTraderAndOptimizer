#!/usr/bin/env python3
"""
Replicate the TOS DKC_MA_Crossover study (weekly EMA10>SMA40) from scanner data.

Emits a TOS-format trade report so engine output can be diffed against a real
Thinkorswim export, and reports signal/fill alignment.

Usage:
    python tos_replicate.py QQQ
    python tos_replicate.py QQQ SPY VTI --fill next
    python tos_replicate.py QQQ --compare /tmp/StrategyReports_QQQ_92526.csv
    python tos_replicate.py QQQ --stats

--fill next   : act on the following bar's open (default; matches TOS)
--fill signal : act on the crossover bar's own close (diagnostic only)

Alignment is judged on crossover DATES. Fill prices are reported but are not a
pass criterion: the scanner's adjustment convention differs from TOS's, so a
persistent price offset is expected and carries no signal-quality meaning.
"""
import argparse
import csv
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as dbm  # noqa: E402

EMA = 10
SMA = 40
SHARES = 100.0
COST = 0.0005
STRATEGY = "DKC_MA_Crossover"


def resolve_ticker(cur, symbol):
    cur.execute("SELECT id FROM tbl_stock_tickers WHERE symbol=%s", (symbol,))
    row = cur.fetchone()
    if row:
        return row[0], "stock"
    cur.execute("SELECT id FROM tbl_etf_tickers WHERE symbol=%s", (symbol,))
    row = cur.fetchone()
    if row:
        return row[0], "etf"
    return None, None


def load_weekly(cur, ticker_id):
    cur.execute(
        "SELECT date, open, close FROM tbl_scanner_tickers "
        "WHERE ticker_id=%s ORDER BY date",
        (ticker_id,),
    )
    rows = cur.fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows], [float(r[2]) for r in rows]


def crossover_signals(dates, closes):
    s = pd.Series(closes)
    ema = s.ewm(span=EMA, adjust=False).mean()
    sma = s.rolling(SMA).mean()
    sign = [
        0 if pd.isna(sma.iloc[i]) else (1 if ema.iloc[i] > sma.iloc[i] else -1)
        for i in range(len(s))
    ]
    out = []
    for i in range(1, len(s)):
        if sign[i] and sign[i - 1] and sign[i] != sign[i - 1]:
            out.append((dates[i], "BUY" if sign[i] > 0 else "SELL", i))
    return out


def build_signals(dates, opens, closes, signals, fill):
    out = []
    for date, side, i in signals:
        if fill == "next":
            j = i + 1
            if j >= len(dates):
                continue
            out.append((dates[j], side, opens[j]))
        else:
            out.append((date, side, closes[i]))
    return out


def build_orders(dates, opens, closes, signals, fill):
    orders = []
    if not signals:
        return orders
    first = signals[0]
    if fill == "next":
        entry_idx = SMA - 1
        if entry_idx >= len(dates):
            return orders
        orders.append((dates[entry_idx], "BUY", opens[entry_idx]))
    else:
        orders.append((dates[0], "BUY", opens[0]))
    for date, side, i in signals:
        if fill == "next":
            j = i + 1
            if j >= len(dates):
                continue
            orders.append((dates[j], side, opens[j]))
        else:
            orders.append((date, side, closes[i]))
    return orders


def money(v):
    if v < 0:
        return "(${:,.2f})".format(abs(v))
    return "${:,.2f}".format(v)


def write_report(path, symbol, orders, work_start, work_end):
    lines = [
        "Strategy report",
        "Symbol: {}".format(symbol),
        "Work Time: {} - {}".format(work_start, work_end),
        "",
        "",
        "Id;Strategy;Side;Amount;Price;Date/Time;Trade P/L;P/L;Position;",
    ]
    entry = None
    running = 0.0
    closed = 0
    max_trade = None
    for n, (date, side, price) in enumerate(orders, start=1):
        d = dt.date
        stamp = "{}/{}/{}".format(date.month, date.day, str(date.year)[2:])
        if side == "BUY":
            entry = price
            lines.append(
                "{};{}(BUY);Buy to Open;{};{};{};;{};{};".format(
                    n, STRATEGY, "{:.1f}".format(SHARES), money(price), stamp,
                    money(running), "{:.1f}".format(SHARES),
                )
            )
        else:
            if entry is None:
                continue
            pnl = (price - entry) * SHARES
            running += pnl
            closed += 1
            if max_trade is None or pnl > max_trade:
                max_trade = pnl
            lines.append(
                "{};{}(SELL);Sell to Close;{};{};{};{};{};0.0;".format(
                    n, STRATEGY, "{:.1f}".format(-SHARES), money(price), stamp,
                    money(pnl), money(running),
                )
            )
            entry = None
    lines += [
        "",
        "",
        "Max trade P/L: {};".format(money(max_trade) if max_trade is not None else "$0.00"),
        "",
        "Total P/L: {};".format(money(running)),
        "",
        "Total order(s): {};".format(closed),
    ]
    with open(path, "w", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
    return closed, running


def parse_tos(path):
    out = []
    meta = {}
    for row in csv.reader(open(path), delimiter=";"):
        if len(row) < 7:
            continue
        if row[0].strip() == "Symbol:" or row[0].startswith("Symbol"):
            meta["symbol"] = row[1].strip()
            continue
        if row[0].strip() == "Work" and len(row) > 1 and row[1].startswith("Time"):
            meta["work_time"] = row[2].strip()
            continue
        if not row[0].strip().isdigit():
            continue
        side = "BUY" if "BUY" in row[1] else "SELL"
        out.append(
            (
                dt.datetime.strptime(row[5], "%m/%d/%y").date(),
                side,
                float(row[4].replace("$", "").replace(",", "")),
            )
        )
    return out, meta


def round_trips(orders):
    out = []
    entry = None
    for date, side, price in orders:
        if side == "BUY":
            entry = (date, price)
        elif entry:
            out.append((entry[0], date, entry[1], price, price / entry[1] - 1))
            entry = None
    return out


def stats(label, orders):
    rts = round_trips(orders)
    if not rts:
        print("{}: no closed round trips".format(label))
        return
    wins = sum(1 for r in rts if r[4] > 0)
    comp = 1.0
    for r in rts:
        comp *= 1 + r[4]
    print("{}".format(label))
    for a, b, p1, p2, r in rts:
        print("   {} -> {}  {:8.2f} -> {:8.2f}  {:+7.2f}%  {}".format(
            a, b, p1, p2, r * 100, "WIN" if r > 0 else "LOSS"))
    print("   -> {} closed | wins {} | win rate {:.1f}% | compounded {:+.1f}%".format(
        len(rts), wins, wins / len(rts) * 100, (comp - 1) * 100))
    if orders and orders[-1][1] == "BUY":
        print("   -> open position: BUY {} @ {:.2f}".format(orders[-1][0], orders[-1][2]))


def max_drawdown(curve, dates):
    peak = curve[0]
    worst = 0.0
    pk = tr = dates[0]
    cur_pk = dates[0]
    for d, v in zip(dates, curve):
        if v > peak:
            peak = v
            cur_pk = d
        dd = v / peak - 1.0
        if dd < worst:
            worst = dd
            pk, tr = cur_pk, d
    return worst, pk, tr


def strategy_curve(dates, opens, closes, signals, start, cost=COST):
    actions = {}
    for _, side, i in signals:
        j = i + 1
        if j < len(dates):
            actions[j] = side
    cash, units, pos = 1.0, 0.0, 0
    curve = []
    for j in range(start, len(dates)):
        if j == start and j not in actions:
            units = cash / (opens[j] * (1 + cost))
            cash = 0.0
            pos = 1
        side = actions.get(j)
        if side == "BUY" and pos == 0:
            units = cash / (opens[j] * (1 + cost))
            cash = 0.0
            pos = 1
        elif side == "SELL" and pos == 1:
            cash = units * opens[j] * (1 - cost)
            units = 0.0
            pos = 0
        curve.append(cash + units * closes[j])
    return curve


def strategy_return(dates, opens, closes, signals, start, cost=COST):
    actions = {}
    for _, side, i in signals:
        j = i + 1
        if j < len(dates):
            actions[j] = side
    cash, units, pos = 1.0, 0.0, 0
    for j in range(start, len(dates)):
        if j == start and j not in actions:
            units = cash / (opens[j] * (1 + cost))
            cash = 0.0
            pos = 1
        side = actions.get(j)
        if side == "BUY" and pos == 0:
            units = cash / (opens[j] * (1 + cost))
            cash = 0.0
            pos = 1
        elif side == "SELL" and pos == 1:
            cash = units * opens[j] * (1 - cost)
            units = 0.0
            pos = 0
    if pos == 1:
        cash = units * closes[-1] * (1 - cost)
    return cash - 1.0


def buy_hold(dates, opens, closes, start, cost=COST):
    return closes[-1] / (opens[start] * (1 + cost)) * (1 - cost) - 1.0


def benchmark(dates, opens, closes, signals, bench_dates, bench_opens, bench_closes, cost=COST):
    start = SMA - 1
    bstart = 0
    for i, d in enumerate(bench_dates):
        if d <= dates[start]:
            bstart = i
    sc = strategy_curve(dates, opens, closes, signals, start, cost)
    sdates = dates[start:]
    bc = [closes[j] / (opens[start] * (1 + cost)) for j in range(start, len(dates))]
    bhc = [bench_closes[j] / (bench_opens[bstart] * (1 + cost))
           for j in range(bstart, len(bench_dates))]
    bdates = bench_dates[bstart:]
    s_dd = max_drawdown(sc, sdates)
    b_dd = max_drawdown(bc, sdates)
    bb_dd = max_drawdown(bhc, bdates)
    return {
        "start": dates[start],
        "end": dates[-1],
        "strategy": strategy_return(dates, opens, closes, signals, start, cost),
        "own_bh": buy_hold(dates, opens, closes, start, cost),
        "bench_bh": buy_hold(bench_dates, bench_opens, bench_closes, bstart, cost),
        "s_dd": s_dd, "b_dd": b_dd, "bb_dd": bb_dd,
    }


def compare(mine, theirs, tol_days=21, cov_start=None, cov_end=None):
    if not mine or not theirs:
        print("  nothing to compare (mine={} theirs={})".format(len(mine), len(theirs)))
        return
    start = min(mine[0][0], theirs[0][0])
    end = max(mine[-1][0], theirs[-1][0])
    m = list(mine)
    t = list(theirs)
    print("  OVERLAP {} -> {} | our signals {} | TOS orders {}".format(
        start, end, len(m), len(t)))
    print("  {:<3}{:<14s}{:<6s}   {:<3}{:<14s}{:<6s}{:>8s}".format(
        "#", "our crossover", "side", "", "TOS order", "side", "ddays"))
    print("  " + "-" * 70)
    used = set()
    matched = exact = within = 0
    deltas = []
    pds = []
    for i, (md, ms, mp) in enumerate(m, start=1):
        best = None
        for j, (td, ts, tp) in enumerate(t):
            if j in used or ts != ms:
                continue
            gap = (td - md).days
            if abs(gap) <= tol_days and (best is None or abs(gap) < abs((best[0] - md).days)):
                best = (td, ts, tp, gap, j)
        if best:
            td, ts, tp, gap, j = best
            used.add(j)
            matched += 1
            exact += gap == 0
            within += abs(gap) <= 7
            deltas.append(gap)
            pds.append((tp - mp) / mp * 100)
            print("  {:<3}{:<12s}{:<6s}   {:<3}{:<12s}{:<6s}{:>8d}".format(
                i, str(md), ms, j + 1, str(td), ts, gap))
        else:
            print("  {:<3}{:<12s}{:<6s}   {:<3}{}".format(
                i, str(md), ms, "-", "no match within {}d".format(tol_days)))
    print("  " + "-" * 66)
    n = len(m)
    verdict = "NO DATA"
    if n:
        grade = ("EXACT" if exact == n else
                 "ALIGNED" if within == n else
                 "PARTIAL" if matched == n else "DIVERGENT")
        print("  DATE ALIGNMENT: {}  |  matched {}/{} | same-date {}/{} | within 1 bar {}/{}".format(
            grade, matched, n, exact, n, within, n))
        if deltas:
            print("  date delta: same-bar {} | +7d {} | -7d {} | other {}".format(
                sum(1 for d in deltas if d == 0), sum(1 for d in deltas if d == 7),
                sum(1 for d in deltas if d == -7),
                sum(1 for d in deltas if d not in (0, 7, -7))))
        verdict = grade
    extra = [x for j, x in enumerate(t) if j not in used]
    real_extra = [x for x in extra
                  if (cov_start is None or x[0] >= cov_start)
                  and (cov_end is None or x[0] <= cov_end)]
    if real_extra:
        print("  MISSED by us, inside our data coverage ({}): {}".format(
            len(real_extra), ", ".join("{} {}".format(d, s) for d, s, _ in real_extra)))
    if pds:
        print("  [info only] fill price offset: mean {:+.1f}% | range {:+.1f}% .. {:+.1f}%".format(
            sum(pds) / len(pds), min(pds), max(pds)))
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--fill", choices=["signal", "next"], default="next")
    ap.add_argument("--outdir", default="/tmp/tos_replicate")
    ap.add_argument("--compare", action="append", default=[],
                    help="TOS csv to diff against; repeatable, matched by order to --tickers")
    ap.add_argument("--stats", action="store_true", help="print round-trip stats")
    ap.add_argument("--bench", default="SPY",
                    help="benchmark symbol for buy-and-hold comparison (default SPY)")
    ap.add_argument("--no-cost", action="store_true", help="ignore transaction costs")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    conn = dbm.get_conn()
    cur = conn.cursor()
    cost = 0.0 if args.no_cost else COST
    bench = None
    if args.bench:
        btid, bkind = resolve_ticker(cur, args.bench.upper())
        if btid is None:
            print("bench {}: NOT FOUND".format(args.bench))
        else:
            bench = load_weekly(cur, btid)
    rows_out = []
    for idx, symbol in enumerate(args.tickers):
        sym = symbol.upper()
        tid, kind = resolve_ticker(cur, sym)
        if tid is None:
            print("{}: NOT FOUND in ticker tables".format(sym))
            continue
        dates, opens, closes = load_weekly(cur, tid)
        if len(dates) < SMA + 1:
            print("{}: only {} weekly bars, need > {}".format(sym, len(dates), SMA))
            continue
        sigs = crossover_signals(dates, closes)
        sig_orders = build_signals(dates, opens, closes, sigs, args.fill)
        orders = build_orders(dates, opens, closes, sigs, args.fill)
        path = os.path.join(args.outdir, "{}_ours.csv".format(sym))
        closed, pnl = write_report(path, sym, orders, dates[0], dates[-1])
        print("{} ({}) {} bars {} -> {} | {} signals | {} orders | {} closed | P/L {:.2f}".format(
            sym, kind, len(dates), dates[0], dates[-1], len(sigs), len(orders), closed, pnl))
        print("   wrote {}".format(path))
        if args.stats:
            stats("  " + sym, orders)
        if bench:
            r = benchmark(dates, opens, closes, sigs, bench[0], bench[1], bench[2], cost)
            rows_out.append((sym, r))
            print("   window {} -> {} ({} bars) | costs {}".format(
                r["start"], r["end"], len(dates) - (SMA - 1),
                "off" if cost == 0 else "{:.4f}/side".format(cost)))
            print("      return   strategy {:+7.1%} | own B&H {:+7.1%} | {} B&H {:+7.1%}".format(
                r["strategy"], r["own_bh"], args.bench.upper(), r["bench_bh"]))
            print("      max DD   strategy {:7.1%} | own B&H {:7.1%} | {} B&H {:7.1%}".format(
                r["s_dd"][0], r["b_dd"][0], args.bench.upper(), r["bb_dd"][0]))
            print("      vs own B&H: return {:+.1f}pp | drawdown {:+.1f}pp".format(
                (r["strategy"] - r["own_bh"]) * 100,
                (r["s_dd"][0] - r["b_dd"][0]) * 100))
        if idx < len(args.compare):
            tos_path = args.compare[idx]
            if not os.path.exists(tos_path):
                print("   compare file missing: {}".format(tos_path))
                continue
            theirs, meta = parse_tos(tos_path)
            print("   vs {} ({})".format(tos_path, meta.get("work_time", "?")))
            compare(sig_orders, theirs, cov_start=dates[SMA - 1], cov_end=dates[-1])
            print()
    if rows_out:
        print("=" * 84)
        print("SUMMARY vs OWN B&H  window {} -> {}  |  costs {}".format(
            rows_out[0][1]["start"], rows_out[0][1]["end"],
            "off" if cost == 0 else "{:.4f}/side".format(cost)))
        print("  {:<6s}{:>11s}{:>11s}{:>12s}{:>11s}{:>11s}{:>13s}".format(
            "sym", "strategy", "own B&H", "ret delta", "strat DD", "own DD", "DD delta"))
        print("  " + "-" * 74)
        for sym, r in rows_out:
            print("  {:<6s}{:>10.1%}{:>11.1%}{:>11.1f}pp{:>11.1%}{:>11.1%}{:>12.1f}pp".format(
                sym, r["strategy"], r["own_bh"], (r["strategy"] - r["own_bh"]) * 100,
                r["s_dd"][0], r["b_dd"][0], (r["s_dd"][0] - r["b_dd"][0]) * 100))
        print("  " + "-" * 74)
        print("  {:<6s}{:>10.1%}{:>11.1%}{:>11s}{:>11.1%}{:>11.1%}".format(
            args.bench.upper(), rows_out[0][1]["bench_bh"], rows_out[0][1]["bench_bh"],
            "-", rows_out[0][1]["bb_dd"][0], rows_out[0][1]["bb_dd"][0]))
    conn.close()


if __name__ == "__main__":
    main()
