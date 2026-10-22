#!/usr/bin/env python3
"""
Fundamentals Research — revenue + earnings growth scoring (Tier A)
------------------------------------------------------------------
Rank each Earnings Crossover pick 0-8 on the fundamentals that matter for an
earnings setup, gate by the R&D-adoption framework's mid-cap scope ($5-50B), and
apply two red-flag deductions. Uses yfinance structured data only — no filing
text, no external sources.

Subtotal (max 8):
    +2  revenue YoY > 15%          (framework's growth threshold)
    +1  revenue YoY up (0-15%)
    +1  revenue up QoQ
    +2  earnings (net income) up YoY
    +1  earnings up QoQ
    +1  operating margin stable/expanding (op income, net-income fallback)

Red-flag deductions:
    -1  margin compression (revenue up but margin contracting)
    -2  goodwill impairment (balance-sheet goodwill down > 2% of market cap)

Scope gate: in-scope = market cap $5B-$50B. Out-of-scope tickers stay on the
momentum list but are marked `!` and excluded from the adoption ranking.

YoY prefers quarter-vs-same-quarter (4 quarters back), falling back to the latest
two annual figures. Results are cached per ticker so the 30-minute screener only
does the (slow) network fetch for new tickers; cache TTL is 30 days.

Usage:
    python fundamentals_research.py --ticker ZBRA
    python fundamentals_research.py --refresh
"""

import argparse
import json
import math
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import yfinance as yf

from table_fmt import is_missing, render_table, slack_table_block as build_slack_table

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '.earnings_fundamentals_cache.json'
)

TTL_DAYS = 30
CACHE_VERSION = 3
MAX_SCORE = 8
MIN_CAP = 5_000_000_000
MAX_CAP = 50_000_000_000
REV_YOY_THRESHOLD = 15.0
GOODWILL_IMPAIRMENT_PCT = 0.02

_RATING_GRADES = ((1.5, 'SB'), (2.5, 'B'), (3.5, 'H'), (4.5, 'S'))


def _row(df, label: str, n: int) -> List[Optional[float]]:
    """Return the first `n` values of a financial-statement row (newest first)."""
    if df is None or len(df) == 0 or label not in df.index:
        return []
    row = df.loc[label]
    if hasattr(row, "ndim") and row.ndim > 1:
        row = row.iloc[0]
    vals: List[Optional[float]] = []
    for v in list(row)[:n]:
        try:
            value = float(v)
        except (TypeError, ValueError):
            vals.append(None)
            continue
        vals.append(None if math.isnan(value) else value)
    return vals


def _at(seq: List[Optional[float]], i: int) -> Optional[float]:
    return seq[i] if len(seq) > i else None


def _up(cur: Optional[float], prev: Optional[float]) -> bool:
    return cur is not None and prev is not None and cur > prev


def _pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def _yoy_pair(q_seq: List[Optional[float]], y_seq: List[Optional[float]]):
    """(latest, year-ago) preferring quarter-vs-4q-back, else latest two annual."""
    cur, prev = _at(q_seq, 0), _at(q_seq, 4)
    if prev is None:
        cur, prev = _at(y_seq, 0), _at(y_seq, 1)
    return cur, prev


def _margin_trend(margins: List[Optional[float]]) -> Optional[bool]:
    """True if latest margin >= year-ago (fallback prior quarter); None if unknown."""
    cur = _at(margins, 0)
    base = _at(margins, 4)
    if base is None:
        base = _at(margins, 1)
    if cur is None or base is None:
        return None
    return cur >= base


def compute_fundamentals(ticker: str) -> Optional[Dict]:
    """Fetch structured fundamentals and return the 0-8 score, metrics and flags."""
    try:
        t = yf.Ticker(ticker)
        q = t.quarterly_income_stmt
        a = t.income_stmt
        info = t.info
    except Exception:
        return None

    rev_q = _row(q, 'Total Revenue', 5)
    ni_q = _row(q, 'Net Income', 5)
    rev_y = _row(a, 'Total Revenue', 2)
    ni_y = _row(a, 'Net Income', 2)

    if not rev_q and not rev_y:
        return None

    op_q = _row(q, 'Operating Income', 5)
    if not op_q or all(v is None for v in op_q):
        op_q = ni_q
    margins = [
        (i / r) if (i is not None and r not in (None, 0)) else None
        for i, r in zip(op_q, rev_q)
    ]
    margins_ok = _margin_trend(margins)

    rev_yoy_cur, rev_yoy_prev = _yoy_pair(rev_q, rev_y)
    ni_yoy_cur, ni_yoy_prev = _yoy_pair(ni_q, ni_y)
    rev_qoq_cur, rev_qoq_prev = _at(rev_q, 0), _at(rev_q, 1)
    ni_qoq_cur, ni_qoq_prev = _at(ni_q, 0), _at(ni_q, 1)

    rev_yoy = _pct(rev_yoy_cur, rev_yoy_prev)

    market_cap = None
    recommendation_mean = None
    num_analysts = None
    target_mean = None
    try:
        market_cap = info.get('marketCap')
        recommendation_mean = info.get('recommendationMean')
        num_analysts = info.get('numberOfAnalystOpinions')
        target_mean = info.get('targetMeanPrice')
    except Exception:
        pass
    in_scope = market_cap is not None and MIN_CAP <= market_cap <= MAX_CAP

    # Goodwill impairment: balance-sheet goodwill down > 2% of market cap.
    goodwill_impairment = False
    try:
        gw = _row(t.balance_sheet, 'Goodwill', 2)
        if market_cap and _at(gw, 1) is not None and _at(gw, 0) is not None:
            drop = _at(gw, 1) - _at(gw, 0)
            goodwill_impairment = drop > 0 and drop > GOODWILL_IMPAIRMENT_PCT * market_cap
    except Exception:
        pass

    subtotal = 0
    if rev_yoy is not None and rev_yoy > REV_YOY_THRESHOLD:
        subtotal += 2
    if rev_yoy is not None and rev_yoy > 0:
        subtotal += 1
    if _up(rev_qoq_cur, rev_qoq_prev):
        subtotal += 1
    if _up(ni_yoy_cur, ni_yoy_prev):
        subtotal += 2
    if _up(ni_qoq_cur, ni_qoq_prev):
        subtotal += 1
    if margins_ok:
        subtotal += 1

    red_flags = {}
    if margins_ok is False:
        red_flags['margin_compression'] = -1
    if goodwill_impairment:
        red_flags['goodwill_impairment'] = -2

    total = max(0, min(MAX_SCORE, subtotal + sum(red_flags.values())))

    return {
        'ticker': ticker,
        'version': CACHE_VERSION,
        'subtotal': subtotal,
        'red_flags': red_flags,
        'score': total,
        'max_score': MAX_SCORE,
        'market_cap': market_cap,
        'in_scope': in_scope,
        'recommendation_mean': recommendation_mean,
        'num_analysts': num_analysts,
        'target_mean': target_mean,
        'rev_yoy': rev_yoy,
        'rev_qoq': _pct(rev_qoq_cur, rev_qoq_prev),
        'earn_yoy': _pct(ni_yoy_cur, ni_yoy_prev),
        'earn_qoq': _pct(ni_qoq_cur, ni_qoq_prev),
        'margins_ok': margins_ok,
        'goodwill_impairment': goodwill_impairment,
        'fetched_at': datetime.now().isoformat(),
    }


def format_label(fr: Optional[Dict]) -> str:
    """Compact score label for a table column, e.g. '8/8*', '5/8!', '-'."""
    if not fr or fr.get('score') is None:
        return '-'
    label = f"{fr['score']}/{fr.get('max_score', MAX_SCORE)}"
    if fr['score'] == fr.get('max_score', MAX_SCORE):
        label += '*'
    if fr.get('in_scope') is False:
        label += '!'
    return label


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:+.1f}%" if not is_missing(v) else "n/a"


def _rating_grade(mean: Optional[float]) -> Optional[str]:
    if mean is None:
        return None
    for cutoff, grade in _RATING_GRADES:
        if mean <= cutoff:
            return grade
    return 'SS'


def format_rating(fr: Optional[Dict]) -> str:
    """Compact consensus rating for a column, e.g. 'B 1.9' (Yahoo consensus, not CFRA)."""
    if not fr:
        return '-'
    mean = fr.get('recommendation_mean')
    grade = _rating_grade(mean)
    if grade is None:
        return '-'
    return f"{grade} {mean:.1f}"


def format_detail(fr: Optional[Dict]) -> str:
    """Human-readable detail line: cap, growth, margin trend, rating, flags."""
    if not fr:
        return 'no data'
    cap = fr.get('market_cap')
    parts = [f"MC ${cap/1e9:.1f}B" if cap else "MC n/a"]
    if fr.get('in_scope') is False:
        parts.append("OUT of $5-50B scope")
    parts.append(
        f"Rev {_fmt_pct(fr.get('rev_yoy'))} YoY ({_fmt_pct(fr.get('rev_qoq'))} QoQ) / "
        f"Earn {_fmt_pct(fr.get('earn_yoy'))} YoY ({_fmt_pct(fr.get('earn_qoq'))} QoQ)"
    )
    rating = format_rating(fr)
    if rating != '-':
        n = fr.get('num_analysts')
        tgt = fr.get('target_mean')
        parts.append(f"consensus {rating}" + (f", {n} analysts" if n else "")
                     + (f", tgt ${tgt:.0f}" if tgt else ""))
    if fr.get('margins_ok') is True:
        parts.append("margin ok")
    elif fr.get('margins_ok') is False:
        parts.append("MARGIN COMPRESSION -1")
    if fr.get('goodwill_impairment'):
        parts.append("GOODWILL IMPAIRMENT -2")
    return " · ".join(parts)


def _cap_parts(cap: Optional[float]) -> Optional[Tuple[float, str, int]]:
    """Split a market cap into (value, unit suffix, decimals) for column rendering."""
    if not cap or is_missing(cap):
        return None
    if cap >= 1e12:
        return cap / 1e12, 'T', 1
    if cap >= 1e9:
        return cap / 1e9, 'B', 1
    return cap / 1e6, 'M', 0


def _cap_cells(caps: List[Optional[float]]) -> List[str]:
    """Market-cap column — the '$' and the unit suffix line up for every row."""
    parts = [_cap_parts(cap) for cap in caps]
    width = max((len(f'{part[0]:.{part[2]}f}') for part in parts if part is not None), default=0)
    cells = []
    for part in parts:
        if part is None:
            cells.append('n/a'.rjust(width + 2))
            continue
        value, suffix, decimals = part
        cells.append(f'${value:>{width}.{decimals}f}{suffix}')
    return cells


def _pct_cells(values: List[Optional[float]]) -> List[str]:
    """Percent column — sign, digits and '%' line up for every row."""
    nums = [value for value in values if not is_missing(value)]
    width = max((len(f'{value:+.1f}') for value in nums), default=0)
    cells = []
    for value in values:
        if is_missing(value):
            cells.append('n/a'.rjust(width + 1))
        else:
            cells.append(f'{value:>+{width}.1f}%')
    return cells


def _scope_str(fr: Dict) -> str:
    if fr.get('market_cap') is None:
        return '?'
    return 'in' if fr.get('in_scope') else 'OUT'


def _flag_str(fr: Dict) -> str:
    flags = []
    if fr.get('margins_ok') is False:
        flags.append('MC')
    if fr.get('goodwill_impairment'):
        flags.append('GW')
    return ' '.join(flags)


_TABLE_COLUMNS = (
    ('Ticker', 'l', 8),
    ('MC', 'r', 8),
    ('RevYoY', 'r', 7),
    ('RevQoQ', 'r', 7),
    ('EarnYoY', 'r', 7),
    ('EarnQoQ', 'r', 7),
    ('Margin', 'r', 6),
    ('Rating', 'r', 7),
    ('Scope', 'r', 5),
    ('Flags', 'l', 6),
)


def format_table_rows(items) -> List[List[str]]:
    """Fundamentals cells for every row — shared by both table renderers."""
    frs = [fr or {} for _ticker, fr in items]
    mc = _cap_cells([fr.get('market_cap') for fr in frs])
    rev_yoy = _pct_cells([fr.get('rev_yoy') for fr in frs])
    rev_qoq = _pct_cells([fr.get('rev_qoq') for fr in frs])
    earn_yoy = _pct_cells([fr.get('earn_yoy') for fr in frs])
    earn_qoq = _pct_cells([fr.get('earn_qoq') for fr in frs])

    rows = []
    for idx, (ticker, fr) in enumerate(items):
        if not fr:
            rows.append([ticker, '-', '-', '-', '-', '-', '-', '-', '-', ''])
            continue
        margin = 'ok' if fr.get('margins_ok') is True else ('comp' if fr.get('margins_ok') is False else '-')
        rows.append([
            ticker,
            mc[idx],
            rev_yoy[idx],
            rev_qoq[idx],
            earn_yoy[idx],
            earn_qoq[idx],
            margin,
            format_rating(fr),
            _scope_str(fr),
            _flag_str(fr) or '-',
        ])
    return rows


def format_table(items) -> List[str]:
    """Aligned fundamentals table. `items` = list of (ticker, fundamentals-or-None)."""
    return render_table(_TABLE_COLUMNS, format_table_rows(items))


def slack_table_block(items) -> dict:
    """Native Slack table block for the fundamentals. `items` as in `format_table`."""
    return build_slack_table(_TABLE_COLUMNS, format_table_rows(items))


class FundamentalsResearch:
    """Per-ticker fundamentals cache: fetch only new tickers, reuse the rest."""

    def __init__(self, ttl_days: int = TTL_DAYS, cache_file: str = CACHE_FILE):
        self.ttl_days = ttl_days
        self.cache_file = cache_file
        self.cache = self._load()
        self._dirty = False

    def _load(self) -> Dict:
        try:
            with open(self.cache_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self):
        if not self._dirty:
            return
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=1)
            self._dirty = False
        except OSError:
            pass

    def _stale(self, entry: Dict) -> bool:
        if entry.get('version') != CACHE_VERSION:
            return True
        ts = entry.get('fetched_at')
        if not ts:
            return True
        try:
            age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 86400
            return age > self.ttl_days
        except ValueError:
            return True

    def get(self, ticker: str, refresh: bool = False) -> Optional[Dict]:
        entry = self.cache.get(ticker)
        if entry and not refresh and not self._stale(entry):
            return entry
        data = compute_fundamentals(ticker)
        if data:
            self.cache[ticker] = data
            self._dirty = True
        return data


def main():
    parser = argparse.ArgumentParser(description='Fundamentals Research — revenue/earnings growth score (0-8)')
    parser.add_argument('--ticker', type=str, help='Analyze a single ticker')
    parser.add_argument('--refresh', action='store_true', help='Clear the cache')
    args = parser.parse_args()

    if args.refresh:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        print(f"Cache cleared: {CACHE_FILE}")
        return

    if not args.ticker:
        parser.error('--ticker is required (or use --refresh)')

    fr = FundamentalsResearch().get(args.ticker.upper(), refresh=True)
    if not fr:
        print(f"No fundamentals data for {args.ticker}")
        return
    print(f"{fr['ticker']}  Fund {format_label(fr)}  (subtotal {fr['subtotal']}, red flags {fr['red_flags']})")
    print(f"  {format_detail(fr)}")


if __name__ == '__main__':
    main()
