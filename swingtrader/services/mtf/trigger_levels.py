"""Trigger levels — next buy/sell price per ticker for the ETF strategies.

Spec: common/docs/SPEC_trigger_levels.md. Read-only Slack report, NO orders, NO state writes.

  * CoreEW P20w (QQQ/VTI/VTV): the flip price is the last settled weekly EMA(20), read from the
    PHP series (PHP-canonical — the signal is never re-implemented here).
  * MTF-ETF (top-3): the flip price is the lowest weekly close at which the ticker is in the top-3.
    Found by bisection over the REAL emasma_core.compute_emasma_score / rank_candidates, so the
    eligibility rule, score rounding and tie-break can never drift from live.

Everything except the bisection, the candidate glue and the table formatter is imported.
Run with the MTF scorer venv from this directory; `--dry-run` prints instead of posting.
"""
import argparse
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

import config
import db as db_module
import executor
import runner
from backtest_trio_ew import fetch_live_leg_ema_series
from emasma_core import compute_emasma_score, rank_candidates, settled_weekly_idx

NY = ZoneInfo('America/New_York')
COREEW_SPAN = 20
COREEW_SYMBOLS = ['QQQ', 'VTI', 'VTV']
NEXT_N = 3          # imminent names shown below the top-N
PRICE_CAP_MULT = 10  # search ceiling: 10x the last weekly close; beyond that the level is n/a

EXPLAINER = (
    'Each ticker has ONE flip price: out of the position it is the BUY trigger,\n'
    'in the position it is the SELL trigger. Only the Friday weekly CLOSE counts\n'
    '(acts the following Monday); touching it mid-week does nothing.\n'
    'CoreEW: weekly close vs its EMA20. MTF-ETF: top-3 membership (EMA10>SMA40 and\n'
    'beating the cut-line score). MTF levels assume the other ETFs hold their scores.'
)


# ---------------------------------------------------------------- MTF-ETF scoring
class EtfBook:
    """Settled-week state of the ETF universe, scored exactly as runner._run_single_mode does."""

    def __init__(self, conn, today):
        self.today = today
        self.tickers = dict(db_module.get_all_tickers(conn, is_etf=True))  # tid -> symbol
        tids = set(self.tickers)
        self.weekly = db_module.bulk_load_weekly(conn, tids)
        self.daily = db_module.bulk_load_daily(conn, tids)
        self.wi = {}
        self.sig_date = max(d for tid in self.daily for d in self.daily[tid]['dates'] if d < today)
        self.candidates = []
        for tid, w in self.weekly.items():
            if tid not in self.daily:
                continue
            idx = {d: i for i, d in enumerate(w['dates'])}
            wi = settled_weekly_idx(idx, w['dates'], today)
            dd = self.daily[tid]
            di = max((i for i, d in enumerate(dd['dates']) if d <= self.sig_date), default=None)
            if wi is None or di is None or (self.sig_date - dd['dates'][di]).days > 1:
                continue  # same stale-bar exclusion as the live run
            self.wi[tid] = (wi, di)
            res = compute_emasma_score(w, dd['close'][di], wi, self.sig_date)
            if res:
                res.update(tid=tid, symbol=self.tickers[tid])
                self.candidates.append(res)

    def settled_week(self):
        wi = next(iter(self.wi.values()))[0]
        tid = next(iter(self.wi))
        return self.weekly[tid]['dates'][wi]

    def score_at(self, tid, close):
        """Score if this ticker's NEXT settled weekly bar closes at `close` (None = ineligible)."""
        w, (wi, di) = self.weekly[tid], self.wi[tid]
        closes = w['close'][:wi + 1] + [close]
        syn = {'close': closes,
               'ema': np.array(db_module.ema(closes, config.EMA_PERIOD), dtype=float),
               'sma': np.array(db_module.sma(closes, config.SMA_PERIOD), dtype=float),
               'dates': w['dates'][:wi + 1] + [w['dates'][wi] + timedelta(days=7)]}
        res = compute_emasma_score(syn, self.daily[tid]['close'][di], wi + 1, self.sig_date)
        if res:
            res.update(tid=tid, symbol=self.tickers[tid])
        return res

    def in_top(self, tid, close):
        res = self.score_at(tid, close)
        if res is None:
            return False
        others = [c for c in self.candidates if c['tid'] != tid]
        return any(t['tid'] == tid for t in rank_candidates(others + [res], True))

    def eligible(self, tid, close):
        return self.score_at(tid, close) is not None

    def flip_price(self, tid, test):
        """Lowest price on the cent grid where test(tid, price) holds (monotone in price), or None."""
        hi = int(self.weekly[tid]['close'][self.wi[tid][0]] * PRICE_CAP_MULT * 100)
        lo = 1
        if not test(tid, hi / 100) or test(tid, lo / 100):
            return None
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if test(tid, mid / 100):
                hi = mid
            else:
                lo = mid
        # self-check against the real scorer: flips exactly here, and stays flipped above
        if not test(tid, hi / 100) or test(tid, (hi - 1) / 100) or not test(tid, hi / 100 * 1.05):
            return None
        return hi / 100

    def level(self, tid):
        """(trigger_price, binding) for one ticker, or (None, reason)."""
        price = self.flip_price(tid, self.in_top)
        if price is None:
            return None, 'n/a'
        elig = self.flip_price(tid, self.eligible)
        if elig is not None and price <= elig:
            return price, 'ELIGIBILITY'
        others = [c for c in self.candidates if c['tid'] != tid]
        if len(others) < config.ETF_TOP_N:
            return price, 'RANK'
        comp = rank_candidates(others, True)[config.ETF_TOP_N - 1]
        return price, f"RANK vs {comp['symbol']} {comp['score']:.1f}"


# ---------------------------------------------------------------- report rows
def mtf_rows(book, held):
    top = rank_candidates(book.candidates, True)
    rest = [c for c in book.candidates if c not in top]
    nxt = rank_candidates(rest, True)[:NEXT_N] if len(rest) >= config.ETF_TOP_N else rest[:NEXT_N]
    out = {'TOP': [], 'NEXT': []}
    for section, group, base in (('TOP', top, 0), ('NEXT', nxt, len(top))):
        for i, c in enumerate(group, base + 1):
            trig, binding = book.level(c['tid'])
            out[section].append(dict(rank=i, sym=c['symbol'], score=c['score'], held=c['symbol'] in held,
                                     live=None, settled=None, trig=trig, side='SELL <' if section == 'TOP' else 'BUY  >', basis=binding))
    return out


def coreew_rows(live, settled):
    payload = fetch_live_leg_ema_series(COREEW_SPAN, COREEW_SYMBOLS)
    rows = []
    for sym in COREEW_SYMBOLS:
        last = payload['series'][sym][-1]
        is_long = bool(payload['state'][sym])
        trig = round(last['ema'], 2) if payload.get('warm') and last['week'] == payload['last_week'] else None
        rows.append(dict(sym=sym, long=is_long, live=live.get(sym), settled=settled.get(sym), trig=trig,
                         side='SELL <' if is_long else 'BUY  >', basis=f'EMA{COREEW_SPAN}'))
    return rows


# ---------------------------------------------------------------- formatting
def _px(v):
    return f'{v:,.2f}' if v is not None else 'n/a'


def _dist(trig, live):
    if trig is None or not live:
        return 'n/a'
    return f'{(trig - live) / live * 100:+.1f}%'


def table(headers, rows, right):
    """Header + dashed rule + rows, columns padded to their widest cell; `right` = right-aligned indexes."""
    cols = [headers] + rows
    w = [max(len(r[i]) for r in cols) for i in range(len(headers))]
    cell = lambda r: '  '.join(r[i].rjust(w[i]) if i in right else r[i].ljust(w[i]) for i in range(len(r))).rstrip()
    return [cell(headers), '  '.join('-' * x for x in w)] + [cell(r) for r in rows]


def trig_cell(r):
    return f"{r['side']} {_px(r['trig'])}" if r['trig'] is not None else 'n/a'


def build_message(now, week, core, mtf, explainer, next_decision):
    h = ['Ticker', 'State', 'Live', 'Settled', 'Trigger', 'Dist', 'Basis']
    core_t = table(h, [[r['sym'], 'LONG' if r['long'] else 'CASH', _px(r['live']), _px(r['settled']),
                        trig_cell(r), _dist(r['trig'], r['live']), r['basis']] for r in core], {2, 3, 5})
    h = ['Rank', 'Ticker', 'State', 'Score', 'Live', 'Settled', 'Trigger', 'Dist', 'Basis']
    mk = lambda rs, st: table(h, [[f"#{r['rank']}", r['sym'], st(r), f"{r['score']:.2f}", _px(r['live']),
                                   _px(r['settled']), trig_cell(r), _dist(r['trig'], r['live']), r['basis']]
                                  for r in rs], {3, 4, 5, 7})
    top_t = mk(mtf['TOP'], lambda r: 'HELD' if r['held'] else 'BUY-PEND')
    nxt_t = mk(mtf['NEXT'], lambda r: 'HELD*' if r['held'] else 'OUT')
    blk = lambda lines: '```\n' + '\n'.join(lines) + '\n```'
    parts = [f"*Triggers — {now:%H:%M} ET · {now:%Y-%m-%d} · settled week {week}*"]
    if explainer:
        parts.append('_How to read_\n' + blk(EXPLAINER.splitlines()))
    parts += ['*CoreEW P20w*\n' + blk(core_t),
              f'*MTF-ETF  TOP {config.ETF_TOP_N}* (sell below)\n' + blk(top_t),
              f'*MTF-ETF  NEXT {NEXT_N}* (buy above)\n' + blk(nxt_t),
              next_decision]
    return '\n'.join(parts)


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--no-explainer', action='store_true', help='omit the HOW TO READ block')
    ap.add_argument('--dry-run', action='store_true', help='print the message, do not post to Slack')
    args = ap.parse_args(argv)
    now = datetime.now(NY)
    conn = None
    try:
        conn = runner._get_db_conn()
        book = EtfBook(conn, now.date())
        week = book.settled_week()
        held = set(db_module.get_all_positions(conn))
        executor._set_alpaca_keys('etf')           # MTF-ETF key pair (stable, longest-running)
        mtf = mtf_rows(book, held)
        symbols = sorted({r['sym'] for sect in mtf.values() for r in sect} | set(COREEW_SYMBOLS))
        live = {s: executor._latest_trade_price(s) for s in symbols}
        settled = executor.latest_settled_daily_closes(conn, symbols)
        for sect in mtf.values():
            for r in sect:
                r['live'], r['settled'] = live.get(r['sym']), settled.get(r['sym'])
        core = coreew_rows(live, settled)
        decide = week + timedelta(days=7 + 4)
        foot = f'Decides Fri {decide} close · acts Mon {decide + timedelta(days=3)}'
        msg = build_message(now, week, core, mtf, not args.no_explainer, foot)
    except Exception:
        if not args.dry_run:
            runner._send_crash_alert(sys.exc_info(), 'etf')
        raise
    finally:
        if conn:
            conn.close()
    print(msg)
    print(f'[TRIGGERS] message chars={len(msg)}')
    if not args.dry_run:
        runner._send_slack(msg, 'etf')
        print('[TRIGGERS] posted')


if __name__ == '__main__':
    main()
