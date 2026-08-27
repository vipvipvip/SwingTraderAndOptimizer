"""
Prototype: MTF stock signal v2 ranking (research).

Spec (user-defined):
  - Score + trade at 1 PM EST on fresh hourly data.
  - Bull gate: hourly EMA10/SMA40 bullish cross where MACD agrees
      (macd_line > 0 AND macd_line > signal). Mismatched crosses ignored.
  - 200MA tier: diff = (price - 200MA)/200MA. Tier1 = diff>0 (above 200MA);
      Tier2 fallback only if no above-200MA candidate qualifies.
  - Rank: smallest positive diff first (fresh turn, not extended),
      lifted by bars-below-zero before MACD positive (anti-whipsaw).
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
import db

load_dotenv()

EMA_SPAN = 10
SMA_SPAN = 40
MA200_SPAN = 200
TOP_N = 10


def load_hourly(conn, ):
    pass


def main():
    conn = db.get_conn()
    cur = conn.cursor()

    cur.execute('''
        SELECT s.id, s.symbol, COUNT(d.id)
        FROM tbl_stock_tickers s
        LEFT JOIN tbl_scanner_tickers_1hour d ON d.ticker_id = s.id
        WHERE s.is_etf = false AND s.enabled = true
        GROUP BY s.id, s.symbol
        HAVING COUNT(d.id) >= %s
    ''', (MA200_SPAN,))
    tickers = [(r[0], r[1]) for r in cur.fetchall()]
    print(f'Candidates with >= {MA200_SPAN} hourly bars: {len(tickers)}')

    results = []
    for tid, sym in tickers:
        cur.execute(
            'SELECT date, close, macd_line, macd_signal '
            'FROM tbl_scanner_tickers_1hour WHERE ticker_id=%s ORDER BY date ASC',
            (tid,))
        rows = cur.fetchall()
        if not rows:
            continue
        closes = pd.Series([float(r[1]) for r in rows])
        macd_line = [float(r[2]) if r[2] is not None else None for r in rows]
        macd_signal = [float(r[3]) if r[3] is not None else None for r in rows]
        dates = [r[0] for r in rows]

        ema = closes.ewm(span=EMA_SPAN, adjust=False).mean().to_numpy()
        sma = closes.rolling(SMA_SPAN).mean().to_numpy()
        ma200 = closes.rolling(MA200_SPAN).mean().to_numpy()

        n = len(closes)
        price = float(closes.iloc[-1])

        # Most recent bullish EMA/SMA cross with MACD agreement
        last_bull_idx = None
        for i in range(n - 1, 0, -1):
            if ema[i] is None or sma[i] is None or ma200[i] is None:
                continue
            if ema[i - 1] is None or sma[i - 1] is None:
                continue
            if (pd.isna(ema[i]) or pd.isna(sma[i]) or pd.isna(ema[i - 1]) or pd.isna(sma[i - 1])):
                continue
            # bullish cross: ema crosses up through sma
            if ema[i] > sma[i] and ema[i - 1] <= sma[i - 1]:
                # MACD must be bullish at this cross: line>0 and line>signal
                ml = macd_line[i]
                ms = macd_signal[i]
                if ml is not None and ms is not None and ml > 0 and ml > ms:
                    last_bull_idx = i
                    break

        if last_bull_idx is None:
            continue

        # diff vs 200MA (percent)
        ma200v = ma200[last_bull_idx]
        if pd.isna(ma200v) or ma200v <= 0:
            continue
        diff_pct = (price - ma200v) / ma200v * 100.0

        # bars below zero before MACD became positive (histogram > 0)
        # count consecutive bars ending at last_bull_idx where macd_line < 0
        # (we require macd positive at the cross; count preceding negative bars)
        bars_below_zero = 0
        j = last_bull_idx - 1
        while j >= 0:
            ml = macd_line[j]
            if ml is not None and ml < 0:
                bars_below_zero += 1
                j -= 1
            else:
                break

        # current MACD zone (for display)
        cur_ml = macd_line[-1]
        cur_ms = macd_signal[-1]
        cur_macd_bull = cur_ml is not None and cur_ms is not None and cur_ml > 0 and cur_ml > cur_ms

        results.append({
            'symbol': sym,
            'price': price,
            'cross_date': dates[last_bull_idx],
            'cross_age_h': (dates[-1] - dates[last_bull_idx]).total_seconds() / 3600,
            'diff_pct': diff_pct,
            'bars_below_zero': bars_below_zero,
            'cur_macd_bull': cur_macd_bull,
            'cur_ml': cur_ml,
            'cur_ms': cur_ms,
        })

    # Tier 1: above 200MA (diff>0), Tier 2: below
    tier1 = [x for x in results if x['diff_pct'] > 0]
    tier2 = [x for x in results if x['diff_pct'] <= 0]
    print(f'\nTotal qualifying (bull cross + MACD agree): {len(results)}')
    print(f'  Tier 1 (above 200MA): {len(tier1)}')
    print(f'  Tier 2 (below 200MA): {len(tier2)}')

    # Rank within tier: smallest diff first; bars_below_zero as secondary lift
    # top-N if tier1 empty use tier2
    tier1_sorted = sorted(tier1, key=lambda x: (x['diff_pct'], -x['bars_below_zero']))
    tier2_sorted = sorted(tier2, key=lambda x: (-x['diff_pct'], -x['bars_below_zero']))
    chosen = tier1_sorted if len(tier1_sorted) > 0 else tier2_sorted
    winners = chosen[:TOP_N]

    print(f'\n=== Top {TOP_N} (Tier {"1 above-200MA" if len(tier1_sorted)>0 else "2 below-200MA"}) ===')
    print(f'{"#":<3}{"sym":<7}{"price":>8}{"cross":<18}{"ageH":>6}{"diff%":>8}{"bars<0":>7}{"MACDbull":>9}')
    for i, x in enumerate(winners, 1):
        print(f'{i:<3}{x["symbol"]:<7}{x["price"]:>8.2f}{str(x["cross_date"]):<18}'
              f'{x["cross_age_h"]:>6.0f}{x["diff_pct"]:>7.2f}%{x["bars_below_zero"]:>7}'
              f'{"Y" if x["cur_macd_bull"] else "N":>9}')
    print()
    print('Tier1 sorted list (all, by smallest diff):')
    print(f'{"sym":<7}{"price":>8}{"diff%":>8}{"bars<0":>7}{"ageH":>6}')
    for x in tier1_sorted:
        print(f'{x["symbol"]:<7}{x["price"]:>8.2f}{x["diff_pct"]:>7.2f}%{x["bars_below_zero"]:>7}{x["cross_age_h"]:>6.0f}')


if __name__ == '__main__':
    main()
