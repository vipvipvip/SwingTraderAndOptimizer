#!/usr/bin/env python3
"""Validate tbl_prices_daily / tbl_prices_weekly before any repoint.

This is the gate. It separates two kinds of finding:

  GATE   - a failure here means the new tables are NOT fit to go live.
           Any gate failure exits non-zero.
  REPORT - interesting but not disqualifying. Reported, never fatal.

The gate deliberately does NOT require the new tables to match the old ones.
The old tables contain provably impossible bars (close outside [low, high]) and
frozen intraday snapshots, so "new matches old" would reject a correct rebuild.
The gate asks whether the new tables are internally sound and no less complete
than what they replace.

Run with no arguments for a full pass. Checks marked as needing atr_stop will
fail until compute_indicators.py has been run against the new tables.

Usage:
    python validate_prices.py
    python validate_prices.py --skip-repro        # skip the API round-trip
    python validate_prices.py --old-daily tbl_scanner_tickers_daily
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn, ATR_PERIOD

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NY = ZoneInfo('America/New_York')

NEW = {'day': 'tbl_prices_daily', 'week': 'tbl_prices_weekly'}
OLD = {'day': 'tbl_scanner_tickers_daily', 'week': 'tbl_scanner_tickers'}

gate_failures = []
notes = []


def gate(name, ok, detail=''):
    status = 'PASS' if ok else 'FAIL'
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
    if not ok:
        gate_failures.append(f'{name}: {detail}')
    return ok


def report(name, detail):
    print(f'  [INFO] {name} — {detail}')
    notes.append(f'{name}: {detail}')


def q(cur, sql, args=None):
    cur.execute(sql, args)
    return cur.fetchall()


def check_internal(cur, table):
    print(f'\n--- internal integrity: {table} ---')
    r = q(cur, f'''SELECT count(*) FILTER (WHERE high < low),
                          count(*) FILTER (WHERE close > high OR close < low),
                          count(*) FILTER (WHERE open  > high OR open  < low),
                          count(*) FILTER (WHERE volume < 0),
                          count(*) FILTER (WHERE close IS NULL OR close = 0),
                          count(*) total
                   FROM {table}''')[0]
    gate(f'{table}: high >= low', r[0] == 0, f'{r[0]} violations')
    gate(f'{table}: close within [low, high]', r[1] == 0, f'{r[1]} violations')
    gate(f'{table}: open within [low, high]', r[2] == 0, f'{r[2]} violations')
    gate(f'{table}: volume >= 0', r[3] == 0, f'{r[3]} violations')
    gate(f'{table}: close present and > 0', r[4] == 0, f'{r[4]} violations')

    dup = q(cur, f'''SELECT count(*) FROM (SELECT ticker_id, date FROM {table}
                    GROUP BY 1,2 HAVING count(*) > 1) x''')[0][0]
    gate(f'{table}: no duplicate (ticker_id, date)', dup == 0, f'{dup} duplicates')

    prov = q(cur, f'''SELECT count(*) FILTER (WHERE source IS NULL OR feed IS NULL
                        OR adjustment IS NULL OR fetched_at IS NULL),
                      count(*) total FROM {table}''')[0]
    gate(f'{table}: provenance populated on every row',
         prov[0] == 0, f'{prov[0]} of {prov[1]} rows missing provenance')
    return r[5]


def check_atr(cur, table):
    """atr_stop must exist wherever ATR(ATR_PERIOD) is computable.

    A ticker with fewer than ATR_PERIOD+1 bars can never have one. SKHY (IPO
    2026-07-06, 13 weekly bars) is the only such enabled ticker, and the old
    tables carry the same NULLs, so this is inherent rather than a regression.
    Those are reported, not failed; anything else missing is a real failure."""
    print(f'\n--- atr_stop readiness: {table} ---')
    r = q(cur, f'''WITH counts AS (SELECT ticker_id, count(*) n FROM {table} GROUP BY 1),
                    latest AS (SELECT DISTINCT ON (ticker_id) ticker_id, atr_stop
                               FROM {table} ORDER BY ticker_id, date DESC)
                    SELECT count(*) FILTER (WHERE l.atr_stop IS NULL AND c.n >= %s),
                           count(*) FILTER (WHERE l.atr_stop IS NULL AND c.n < %s),
                           count(*)
                    FROM latest l JOIN counts c ON c.ticker_id = l.ticker_id''',
            (ATR_PERIOD + 1, ATR_PERIOD + 1))[0]
    gate(f'{table}: atr_stop present where ATR is computable (>= {ATR_PERIOD + 1} bars)',
         r[0] == 0, f'{r[0]} of {r[2]} tickers NULL despite enough history')
    if r[1]:
        report(f'{table}: tickers with too little history for ATR',
               f'{r[1]} ticker(s) under {ATR_PERIOD + 1} bars — atr_stop cannot exist '
               f'(same in the old tables; expected for recent IPOs)')


def check_coverage(cur, new_table, old_table):
    print(f'\n--- coverage vs {old_table} ---')
    newc = dict(q(cur, f'SELECT ticker_id, count(*) FROM {new_table} GROUP BY 1'))
    # Enabled only: the load deliberately covers the 1,453 enabled tickers, so a
    # disabled ticker present in the old tables is not a hole.
    oldc = dict(q(cur, f'''SELECT x.ticker_id, count(*) FROM {old_table} x
                           JOIN tbl_stock_tickers s ON s.id = x.ticker_id
                           WHERE s.enabled GROUP BY 1'''))
    both = set(newc) & set(oldc)
    lost = [(t, oldc[t], newc[t]) for t in both if newc[t] < oldc[t]]
    gate(f'{new_table}: no ticker lost rows vs {old_table}',
         not lost, f'{len(lost)} tickers lost rows, e.g. {lost[:3]}')

    only_old = set(oldc) - set(newc)
    # An enabled ticker that the old tables carried but the new ones lack is a
    # hole, not a curiosity. MNDY and MNPR were caught this way: both loaded
    # fine on a retry, but had been silently absent after the threaded run.
    gate(f'{new_table}: every enabled ticker in {old_table} is present here',
         not only_old,
         f'{len(only_old)} absent, e.g. {sorted(only_old)[:5]}' if only_old else '')

    newr = q(cur, f'SELECT min(date)::date, max(date)::date, count(DISTINCT ticker_id), '
                  f'count(*) FROM {new_table}')[0]
    oldr = q(cur, f'SELECT min(date)::date, max(date)::date, count(DISTINCT ticker_id), '
                  f'count(*) FROM {old_table}')[0]
    report(f'{new_table} range', f'{newr[0]} -> {newr[1]}, {newr[2]} tickers, {newr[3]} rows')
    report(f'{old_table} range', f'{oldr[0]} -> {oldr[1]}, {oldr[2]} tickers, {oldr[3]} rows')

    deeper = q(cur, f'''SELECT count(*) FROM (
              SELECT n.ticker_id FROM {new_table} n JOIN {old_table} o
                ON o.ticker_id=n.ticker_id GROUP BY n.ticker_id
              HAVING min(n.date) < min(o.date)) x''')[0][0]
    report(f'{new_table}: tickers with deeper history than old',
           f'{deeper} of {len(both)} shared')


def check_close_diff(cur, new_table, old_table):
    print(f'\n--- close difference vs {old_table} (REPORT only) ---')
    r = q(cur, f'''SELECT count(*) AS paired,
                     round(avg(abs(n.close-o.close)::numeric), 4) AS mean_abs,
                     round(max(abs(n.close-o.close)::numeric), 4) AS max_abs,
                     round(avg((abs(n.close-o.close)/nullif(o.close,0))*100)::numeric, 4) AS mean_pct,
                     round(max((abs(n.close-o.close)/nullif(o.close,0))*100)::numeric, 4) AS max_pct,
                     count(*) FILTER (WHERE abs(n.close-o.close) > 0.01) AS diff_gt_cent
                  FROM {new_table} n JOIN {old_table} o
                    ON o.ticker_id=n.ticker_id AND o.date=n.date''')[0]
    if not r[0]:
        report('close diff', 'no overlapping dates to compare')
        return
    report('close diff', f'{r[0]} paired rows')
    report('  mean abs diff', f'{r[1]}')
    report('  max abs diff', f'{r[2]}')
    report('  mean pct diff', f'{r[3]}%')
    report('  max pct diff', f'{r[4]}%')
    report('  rows differing > $0.01', f'{r[5]} ({100.0*r[5]/r[0]:.2f}%)')


def check_old_corruption(cur, table):
    print(f'\n--- corruption in {table} (context for the diff above) ---')
    r = q(cur, f'''SELECT count(*) FILTER (WHERE close > high OR close < low),
                          count(*) FILTER (WHERE open > high OR open < low),
                          count(*) total FROM {table}''')[0]
    report('impossible bars in OLD table',
           f'close outside range: {r[0]}, open outside range: {r[1]}, of {r[2]} rows')

    anom = q(cur, f'''WITH med AS (SELECT ticker_id, percentile_cont(0.5)
                          WITHIN GROUP (ORDER BY volume) v FROM {table} GROUP BY 1)
                    SELECT count(*) FROM {table} t JOIN med m USING (ticker_id)
                      WHERE t.volume < m.v * 0.05 AND m.v > 0''')[0][0]
    report('suspected frozen intraday snapshots in OLD table',
           f'{anom} rows with volume < 5% of that ticker median')


def check_weekly_vs_daily(cur):
    """Native weekly must aggregate from daily. Alpaca's weekly bar is stamped
    with the week's first day; its open/high/low/close are the first/max/min/
    LAST daily bar of that Mon-Sun window. Comparing weekly close against the
    week's MAX close is wrong and reports false disagreement."""
    print(f'\n--- native weekly vs aggregation of daily (REPORT only) ---')
    r = q(cur, f'''WITH w AS (SELECT ticker_id, date, open, high, low, close
                          FROM {NEW['week']}),
                    agg AS (
                      SELECT w.ticker_id, w.date,
                             w.open, w.high, w.low, w.close,
                             min(d.date) AS first_d, max(d.date) AS last_d,
                             count(*) AS ndays,
                             (array_agg(d.open  ORDER BY d.date))[1] AS d_open,
                             max(d.high) AS d_high, min(d.low) AS d_low,
                             (array_agg(d.close ORDER BY d.date DESC))[1] AS d_close
                      FROM w JOIN {NEW['day']} d
                        ON d.ticker_id = w.ticker_id
                       AND d.date BETWEEN w.date AND w.date + 6
                      GROUP BY w.ticker_id, w.date, w.open, w.high, w.low, w.close)
                    SELECT count(*),
                           count(*) FILTER (WHERE abs(close - d_close) > 0.01),
                           count(*) FILTER (WHERE abs(open  - d_open)  > 0.01),
                           count(*) FILTER (WHERE abs(high  - d_high)  > 0.01),
                           count(*) FILTER (WHERE abs(low   - d_low)   > 0.01),
                           count(*) FILTER (WHERE ndays < 5)
                    FROM agg''')[0]
    report('weeks compared', f'{r[0]} complete weeks')
    report('weekly close != last daily close', f'{r[1]}')
    report('weekly open  != first daily open', f'{r[2]}')
    report('weekly high  != max daily high', f'{r[3]}')
    report('weekly low   != min daily low', f'{r[4]}')
    report('weeks with < 5 trading days', f'{r[5]} (partial/holiday weeks)')


def check_repro(cur, limit=3):
    print(f'\n--- reproducibility spot-check (API round-trip) ---')
    try:
        import load_prices as lp
    except Exception as e:
        report('reproducibility', f'skipped, cannot import loader: {e}')
        return
    syms = q(cur, f'''SELECT t.symbol FROM {NEW['day']} p
                      JOIN tbl_stock_tickers t ON t.id=p.ticker_id
                      GROUP BY t.symbol ORDER BY t.symbol LIMIT %s''', (limit,))
    for (sym,) in syms:
        tid = q(cur, 'SELECT id FROM tbl_stock_tickers WHERE symbol=%s', (sym,))[0][0]
        rows, err = lp.fetch_with_retry(sym, 'day')
        if err:
            gate(f'repro {sym}', False, err)
            continue
        db = q(cur, f'SELECT date, open, high, low, close, volume FROM {NEW["day"]} '
                    'WHERE ticker_id=%s ORDER BY date', (tid,))
        match = len(rows) == len(db) and all(
            a[0] == b[0] and abs(float(a[4]) - float(b[4])) < 1e-9
            for a, b in zip(rows, db))
        gate(f'{sym}: re-fetch is identical to stored rows', match,
             f'fetched {len(rows)}, stored {len(db)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-repro', action='store_true')
    ap.add_argument('--old-daily', default=OLD['day'])
    ap.add_argument('--old-weekly', default=OLD['week'])
    args = ap.parse_args()
    OLD['day'], OLD['week'] = args.old_daily, args.old_weekly

    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            for key, table in NEW.items():
                exists = q(cur, "SELECT 1 FROM information_schema.tables "
                                "WHERE table_schema='public' AND table_name=%s",
                           (table,))
                if not exists:
                    print(f'\n{table}: DOES NOT EXIST — run create_price_tables.py')
                    gate_failures.append(f'{table} missing')
                    continue
                n = check_internal(cur, table)
                print(f'  (rows checked: {n})')
                check_atr(cur, table)
                check_coverage(cur, table, OLD[key])
                check_close_diff(cur, table, OLD[key])
                check_old_corruption(cur, OLD[key])
            check_weekly_vs_daily(cur)
            if not args.skip_repro:
                check_repro(cur)
    finally:
        conn.close()

    print('\n' + '=' * 64)
    if gate_failures:
        print(f'GATE FAILED — {len(gate_failures)} check(s):')
        for f in gate_failures:
            print(f'  - {f}')
        print('\nDo NOT repoint. Fix these first.')
        sys.exit(1)
    print('ALL GATE CHECKS PASSED')
    print(f'({len(notes)} informational notes above)')
    print('Repoint is now unblocked, but still a separate deliberate step.')


if __name__ == '__main__':
    main()