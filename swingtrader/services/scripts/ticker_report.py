#!/usr/bin/env python3
"""ticker_report.py — read-only MTF report for one or more tickers.

Reports the exact values the MTF Top-N system computes for a ticker and a
directional call (BUY / BUY MORE / HOLD / SELL / WATCH):
  - Multi-TF score components: weekly gap, ATR distance, freshness, score
  - Trend filters: weekly EMA10>SMA40, daily EMA10>SMA40, hourly close>ATR stop
  - Top-N context (informational only): in/out of the last rotation, cutoff
  - Held-position info when known: qty, entry, market value, PnL, ratchet stop

The directional call is driven by the ticker's OWN MTF signals (trend filters +
score) plus the ratchet stop when an entry date is known — it does NOT depend
on the top-10 rotation rank. Decide by passing --position for held names.

Pure reporting — reads the DB only. Never places orders and never writes
state (no mtf_pending / mtf_runs / mtf_trades / CSV mutations).

Usage:
  python ticker_report.py DELL PAYC BXC
  python ticker_report.py ZBRA BDX V --position "ZBRA:5:300:2026-07-01" \
      --position "BDX:2:170:2026-07-15"         # declare held + get PnL/ratchet
  python ticker_report.py --holdings            # all current MTF positions
  python ticker_report.py --holdings --json     # machine-readable output

--position format: SYMBOL:QTY:ENTRY_PRICE[:ENTRY_DATE] (repeatable).
  Repeat for the same symbol to model accumulation/DCA — qty sums, entry
  becomes the weighted average cost, and the ratchet anchor uses the earliest
  date. Entry date is required for the ratchet stop; without it the stop is
  skipped. Explicit --position overrides a DB position.

Run with the optimizer venv (same interpreter the MTF services use):
  swingtrader/services/optimizer/venv/bin/python3 swingtrader/services/scripts/ticker_report.py ...
"""

import argparse
import bisect
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'mtf'))
import config
import db as db_module
import runner
import executor


def _nearest_index(dates, target):
    """Index of the last date <= target (like the runner's _nearest_date_idx)."""
    i = bisect.bisect_right(dates, target) - 1
    return i if i >= 0 else None


def _load_ticker(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT id, is_etf, enabled FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
        row = cur.fetchone()
    if not row:
        return None, None, 'unknown ticker'
    tid, is_etf, enabled = row
    if not enabled:
        return None, None, 'ticker disabled in tbl_stock_tickers'
    return tid, is_etf, None


def _last_top_n(conn, mode):
    """Best-effort top-N context from the last scoring run.

    Prefers the unconsumed mtf_pending (has full score_detail with ranks);
    falls back to the pick-history CSV (top-10 + scores only).
    Returns (top_symbols, cutoff, rank_map, sig_date_str) — each may be None.
    """
    pending = db_module.get_pending(conn, mode)
    if pending and pending.get('score_detail'):
        sd = pending['score_detail']
        tops = pending['top_symbols']
        cutoff = None
        scored_syms = [s for s in tops if s in sd]
        if scored_syms:
            cutoff = min(sd[s]['score'] for s in scored_syms)
        ranked = sorted(sd.keys(), key=lambda s: -sd[s]['score'])
        rank_map = {s: i + 1 for i, s in enumerate(ranked)}
        sig = pending.get('sig_date')
        return tops, cutoff, rank_map, str(sig)[:10] if sig else None

    path = os.path.join(BASE, 'mtf', 'data', f'mtf_picks_{mode}.csv')
    if not os.path.exists(path):
        return None, None, None, None
    import csv
    rows = [r for r in csv.reader(open(path)) if r and r[0] and r[0] != 'date']
    if not rows:
        return None, None, None, None
    last_date = max(r[0] for r in rows)
    day_rows = [r for r in rows if r[0] == last_date]
    tops = [r[2] for r in day_rows if len(r) > 2]
    scores = {}
    rank_map = {}
    for r in day_rows:
        if len(r) > 3 and r[2]:
            try:
                scores[r[2]] = float(r[3])
            except ValueError:
                pass
            try:
                rank_map[r[2]] = int(r[1])
            except (ValueError, IndexError):
                pass
    cutoff = min(scores.values()) if scores else None
    return tops, cutoff, (rank_map or None), last_date


def _fresh_score(conn, tid, is_etf):
    """Compute the ticker's score on its latest complete data (matches runner logic)."""
    weekly = db_module.load_weekly(conn, tid)
    daily = db_module.load_daily(conn, tid)
    if weekly is None or daily is None:
        return None
    sig_date = daily['dates'][-1]
    di = len(daily['dates']) - 1
    wi = _nearest_index(weekly['dates'], sig_date)
    if wi is None or wi < config.WARMUP_BARS:
        return None
    if is_etf:
        return runner._compute_emasma_score(weekly, daily['close'][di], wi, sig_date)
    hourly = db_module.load_hourly(conn, tid)
    if hourly is None:
        return None
    hi = _nearest_index(hourly['dates'], sig_date)
    if hi is None or hi < 1:
        return None
    return runner._compute_score(weekly, daily, hourly, wi, di, hi, sig_date)


def _position_stats(conn, tid, symbol, is_etf, close, manual_pos=None):
    """Position info. manual_pos overrides the DB (for holdings outside mtf_positions).
    manual_pos = {qty, entry_price, entry_at(date|None)}."""
    pos = manual_pos if manual_pos else db_module.get_position(conn, tid)
    out = {'held': bool(pos), 'manual': bool(manual_pos)}
    if not pos:
        return out
    qty = float(pos.get('qty') if isinstance(pos, dict) else pos[1])
    entry = float(pos.get('entry_price') if isinstance(pos, dict) else pos[2])
    entry_at = pos.get('entry_at') if isinstance(pos, dict) else pos[3]
    out.update({'held': True, 'quantity': qty, 'entry_price': round(entry, 2)})
    if close and entry:
        out['market_value'] = round(qty * close, 2)
        out['pnl_pct'] = round((close - entry) / entry * 100, 1)
    if not is_etf:
        since = entry_at.date() if hasattr(entry_at, 'date') else entry_at
        if manual_pos:
            stop, peak = _manual_ratchet(conn, tid, since)
        else:
            stop = executor._compute_ratchet_stops(conn, [symbol]).get(symbol)
            peak = None
            if since:
                with conn.cursor() as cur:
                    cur.execute(
                        'SELECT close FROM tbl_scanner_tickers_daily '
                        'WHERE ticker_id = %s AND date::date >= %s ORDER BY date ASC',
                        (tid, since))
                    rows = cur.fetchall()
                if rows:
                    peak = max(float(r[0]) for r in rows)
        out['ratchet_stop'] = round(stop, 2) if stop is not None else None
        out['ratchet_skipped'] = stop is None and manual_pos
        out['peak_since_entry'] = round(peak, 2) if peak else None
    return out


def _manual_ratchet(conn, tid, since):
    """Same ratchet math as the live executor, but anchored to an arbitrary
    entry date (for positions not in mtf_positions). Returns (stop, peak)."""
    if not since:
        return None, None
    with conn.cursor() as cur:
        cur.execute(
            'SELECT date, close FROM tbl_scanner_tickers_daily '
            'WHERE ticker_id = %s AND date::date >= %s ORDER BY date ASC',
            (tid, since))
        d_rows = cur.fetchall()
    if not d_rows:
        return None, None
    h_by_day = {}
    with conn.cursor() as cur:
        cur.execute(
            'SELECT date, close, atr_stop FROM tbl_scanner_tickers_1hour '
            'WHERE ticker_id = %s ORDER BY date ASC', (tid,))
        for r in cur.fetchall():
            h_by_day[r[0].date()] = (float(r[1]) if r[1] else 0.0,
                                     float(r[2]) if r[2] else 0.0)
    peak = None
    ratchet = 0.0
    for r in d_rows:
        day = r[0].date() if hasattr(r[0], 'date') else r[0]
        dc = float(r[1]) if r[1] else 0.0
        peak = max(peak, dc) if peak is not None else dc
        hb = h_by_day.get(day)
        if not hb or hb[1] <= 0 or hb[0] <= hb[1]:
            continue
        atr = (hb[0] - hb[1]) / 2.0
        if atr <= 0:
            continue
        ratchet = max(ratchet, peak - config.RATCHET_ATR_MULT * atr)
    return (round(ratchet, 2) if peak is not None else None), \
           (round(peak, 2) if peak is not None else None)


def _stats_ctx(weekly, daily, hourly, sig_date, wi, di, hi, is_etf, fresh, close):
    import math
    ctx = {}
    wc, we, ws = weekly['close'][wi], weekly['ema'][wi], weekly['sma'][wi]
    ctx['weekly_ema'] = round(float(we), 2)
    ctx['weekly_sma'] = round(float(ws), 2)
    ctx['gap_w'] = round((float(wc) - float(ws)) / float(ws) * 100, 1)
    ctx['weekly_bullish'] = bool(not (math.isnan(we) or math.isnan(ws)) and we > ws)
    ctx['freshness'] = fresh.get('freshness') if fresh else None
    if is_etf:
        return ctx
    dc, de, ds = daily['close'][di], daily['ema'][di], daily['sma'][di]
    hc, ha = hourly['close'][hi], hourly['atr_stop'][hi]
    ctx['daily_ema'] = round(float(de), 2)
    ctx['daily_sma'] = round(float(ds), 2)
    ctx['daily_bullish'] = bool(not (math.isnan(de) or math.isnan(ds)) and de > ds)
    ctx['hourly_close'] = round(float(hc), 2)
    ctx['atr_stop'] = round(float(ha), 2)
    ctx['atr_dist'] = round((float(hc) - float(ha)) / float(hc) * 100, 2) if ha > 0 else 0.0
    ctx['hourly_bullish'] = bool(not math.isnan(hc) and not math.isnan(ha) and hc > ha)
    return ctx


def _direction(is_etf, scored, f, ratchet_stop, close, held):
    """Directional call from the ticker's own MTF signals (trend filters +
    score), plus the ratchet stop when a held entry date is known.
    Returns (action, reason). Guidance only — no orders are placed."""
    score = scored['score'] if scored else 0.0
    if ratchet_stop is not None and close is not None and close < ratchet_stop:
        return 'SELL', f'below ratchet stop ${ratchet_stop:.2f}'

    if is_etf:
        if not f.get('weekly_bullish', False):
            return ('SELL' if held else 'WATCH'), 'weekly EMA10 <= SMA40 (trend down)'
        if score >= 2.5:
            return ('BUY MORE' if held else 'BUY'), f'EMA/SMA strong (score {score})'
        return ('HOLD' if held else 'WATCH'), f'weekly trend up but momentum weak (score {score})'

    weekly_ok = f.get('weekly_bullish', False)
    daily_ok = f.get('daily_bullish', False)
    hourly_ok = f.get('hourly_bullish', False)
    if not weekly_ok:
        return ('SELL' if held else 'WATCH'), 'weekly trend broken (EMA10 <= SMA40)'
    if not (daily_ok and hourly_ok):
        return ('SELL' if held else 'WATCH'), \
            'momentum weakening — daily/hourly filter off (hold only if entry is cheap)'
    if score >= 4.5:
        return ('BUY MORE' if held else 'BUY'), \
            f'strong momentum (score {score}), all filters bullish'
    if score >= 3.0:
        return ('HOLD' if held else 'WATCH'), f'decent momentum (score {score})'
    return ('HOLD' if held else 'WATCH'), f'weak momentum (score {score})'


def report_one(conn, symbol, is_etf, top_ctx, manual_pos=None):
    tid, _is_etf, err = _load_ticker(conn, symbol)
    if err:
        return {'symbol': symbol, 'error': err}
    mode = 'etf' if is_etf else 'stock'
    fresh = _fresh_score(conn, tid, is_etf)
    close = fresh['close'] if fresh else None

    weekly = db_module.load_weekly(conn, tid)
    daily = db_module.load_daily(conn, tid)
    hourly = db_module.load_hourly(conn, tid) if not is_etf else None
    sig_date = daily['dates'][-1] if daily else None

    report = {'symbol': symbol, 'mode': mode}
    report['strategy'] = 'EMA/SMA' if is_etf else 'Multi-TF'
    if fresh:
        report['score'] = fresh['score']
        report['close'] = close
        report['close_date'] = str(sig_date)[:10]
        report['gap_w'] = fresh['gap_w']
        report['atr_dist'] = fresh['atr_dist']
        report['freshness'] = fresh['freshness']

    if weekly and daily:
        wi = _nearest_index(weekly['dates'], sig_date)
        di = len(daily['dates']) - 1
        hi = _nearest_index(hourly['dates'], sig_date) if hourly else None
        if wi is not None and (is_etf or hi is not None):
            report['filters'] = _stats_ctx(weekly, daily, hourly, sig_date, wi, di, hi,
                                           is_etf, fresh, close)

    tops, cutoff, rank_map, last_sig = top_ctx.get(mode, (None, None, None, None))
    in_top = tops is not None and symbol in tops
    report['in_top_n'] = in_top
    report['rank'] = rank_map.get(symbol) if rank_map else None
    report['cutoff'] = cutoff
    report['last_scored'] = last_sig

    pos = _position_stats(conn, tid, symbol, is_etf, close, manual_pos=manual_pos)
    report.update(pos)

    action, reason = _direction(is_etf, fresh, report.get('filters', {}),
                                pos.get('ratchet_stop'), close, pos['held'])
    report['action'] = action
    report['reason'] = reason
    return report


def _fmt_report(r):
    if 'error' in r:
        return f"== {r['symbol']}: {r['error']} =="
    mode = r['mode'].upper()
    tag = f"[{mode}]  {r['strategy']}"
    lines = [f"==== {r['symbol']}  {tag} ===="]
    if r.get('close') is not None:
        lines.append(f"  Price:  ${r['close']:.2f}  (daily close {r.get('close_date')})")
    if r.get('held'):
        pnl = f"  (PnL {r['pnl_pct']:+.1f}%)" if r.get('pnl_pct') is not None else ''
        lines.append(f"  Held:   {r['quantity']} sh @ ${r['entry_price']:.2f}  "
                     f"value ${r.get('market_value', 0):,.2f}{pnl}")
    lines.append("  " + "-" * 52)
    if r.get('score') is not None:
        ctx_s = ''
        if r.get('in_top_n') and r.get('rank'):
            ctx_s = f"  (in MTF top-10: rank #{r['rank']})"
        elif r.get('cutoff') is not None:
            ctx_s = f"  (top-10 cutoff {r['cutoff']})"
        lines.append(f"  MTF Score: {r['score']}{ctx_s}")
    f = r.get('filters', {})
    if f:
        gap = f"{f['gap_w']:+.1f}% gap" if f.get('gap_w') is not None else ''
        bull = '✓' if f.get('weekly_bullish') else '✗'
        lines.append(f"  Weekly:  EMA10 {f['weekly_ema']} > SMA40 {f['weekly_sma']}  ({gap})  [{bull}]")
        if 'daily_ema' in f:
            dbull = '✓' if f.get('daily_bullish') else '✗'
            lines.append(f"  Daily:   EMA10 {f['daily_ema']} > SMA40 {f['daily_sma']}  [{dbull}]")
        if 'hourly_close' in f:
            hbull = '✓' if f.get('hourly_bullish') else '✗'
            lines.append(f"  Hourly:  close ${f['hourly_close']:.2f} > ATR stop ${f['atr_stop']:.2f}  "
                         f"(dist +{f['atr_dist']:.2f}%)  [{hbull}]")
        if f.get('freshness') is not None and f['freshness'] < 999:
            lines.append(f"  Fresh:   {f['freshness']}d since weekly EMA/SMA cross")
        elif f.get('freshness') is not None:
            lines.append(f"  Fresh:   no recent weekly cross")
    if r.get('ratchet_stop') is not None:
        d = f"{((r['close'] - r['ratchet_stop']) / r['ratchet_stop'] * 100):+.1f}% above stop" \
            if r.get('close') else ''
        lines.append(f"  Ratchet: ${r['ratchet_stop']:.2f}  (peak ${r.get('peak_since_entry') or 0:.2f} − 2×ATR)  {d}")
    elif r.get('ratchet_skipped'):
        lines.append("  Ratchet: skipped (pass --position with an entry date for a stop)")
    lines.append("  " + "-" * 52)
    lines.append(f"  ACTION:  {r['action']}  —  {r['reason']}")
    return "\n".join(lines)


def _parse_positions(items):
    """Parse 'SYM:QTY:ENTRY[:YYYY-MM-DD]' entries into per-symbol holdings.

    Repeat for the same symbol to model accumulation / DCA: qty sums,
    entry price becomes the quantity-weighted average cost, and the entry
    date used for the ratchet anchor is the EARLIEST date supplied.
    """
    from datetime import date as dt_date
    manual = {}
    for item in items or []:
        parts = [p.strip() for p in item.split(':')]
        if len(parts) < 3:
            raise SystemExit(f'bad --position "{item}" — expected SYMBOL:QTY:ENTRY[:DATE]')
        sym, qty, entry = parts[0].upper(), float(parts[1]), float(parts[2])
        entry_at = None
        if len(parts) >= 4 and parts[3]:
            try:
                entry_at = dt_date.fromisoformat(parts[3])
            except ValueError:
                raise SystemExit(f'bad --position date "{parts[3]}" for {sym} — use YYYY-MM-DD')
        cur = manual.setdefault(sym, {'qty': 0.0, 'entry_price': 0.0, 'entry_at': None})
        total = cur['qty'] * cur['entry_price'] + qty * entry
        cur['qty'] += qty
        cur['entry_price'] = total / cur['qty']
        if entry_at and (cur['entry_at'] is None or entry_at < cur['entry_at']):
            cur['entry_at'] = entry_at
    return manual


def main():
    ap = argparse.ArgumentParser(description='Read-only MTF report for tickers.')
    ap.add_argument('tickers', nargs='*', help='symbols to report')
    ap.add_argument('--holdings', action='store_true', help='report all current MTF positions')
    ap.add_argument('--position', action='append', metavar='SYM:QTY:ENTRY[:DATE]',
                    help='declare a holding you own (adds PnL + ratchet stop)')
    ap.add_argument('--json', action='store_true', help='emit JSON instead of text')
    args = ap.parse_args()
    manual = _parse_positions(args.position)

    conn = db_module.get_conn()
    symbols = list(args.tickers)
    if args.holdings:
        symbols.extend(sorted(db_module.get_all_positions(conn).keys()))
    for sym in manual:
        if sym not in symbols:
            symbols.append(sym)

    if not symbols:
        ap.print_help()
        sys.exit(2)

    top_ctx = {mode: _last_top_n(conn, mode) for mode in ('stock', 'etf')}
    reports = []
    for sym in symbols:
        tid, is_etf, err = _load_ticker(conn, sym)
        if err:
            reports.append({'symbol': sym, 'error': err})
            continue
        reports.append(report_one(conn, sym, is_etf, top_ctx, manual_pos=manual.get(sym)))
    conn.close()

    if args.json:
        print(json.dumps(reports, indent=2))
        return

    for r in reports:
        print(_fmt_report(r))
        print()

    _print_summary(reports)


def _print_summary(reports):
    rows = []
    for r in reports:
        if 'error' in r:
            rows.append({'ticker': r['symbol'], 'action': '??', 'reason': r['error'], 'pnl': None})
        else:
            rows.append({'ticker': r['symbol'], 'action': r.get('action', '?'),
                         'reason': r.get('reason', ''), 'pnl': r.get('pnl_pct')})

    has_pnl = any(r['pnl'] is not None for r in rows)
    if has_pnl:
        hdr = f"{'Ticker':<8} {'PnL':>8}  {'Action':<10} Why"
    else:
        hdr = f"{'Ticker':<8} {'Action':<10} Why"
    print('==== Summary ====')
    print('  ' + hdr)
    print('  ' + '-' * len(hdr))
    for r in rows:
        p = f"{r['pnl']:+.1f}%" if r['pnl'] is not None else ''
        if has_pnl:
            line = f"{r['ticker']:<8} {p:>8}  {r['action']:<10} {r['reason']}"
        else:
            line = f"{r['ticker']:<8} {r['action']:<10} {r['reason']}"
        print('  ' + line)


if __name__ == '__main__':
    main()
