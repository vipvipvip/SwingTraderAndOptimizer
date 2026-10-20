#!/usr/bin/env python3
import sys
import pandas as pd
import psycopg2

def get_db():
    return psycopg2.connect(host='localhost', port=5432, dbname='swingtrader', user='swingtrader')

def get_weekly(conn, symbol, start=None):
    q = """SELECT w.date, w.close, w.high, w.low
           FROM tbl_prices_weekly w
           JOIN tbl_stock_tickers t ON t.id = w.ticker_id
           WHERE t.symbol=%s"""
    params = [symbol.upper()]
    if start:
        q += " AND w.date>= %s"
        params.append(start)
    q += " ORDER BY w.date ASC"
    df = pd.read_sql_query(q, conn, params=params, index_col='date')
    for c in ['close','high','low']:
        if c in df: df[c] = df[c].astype(float)
    return df

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'MRNA'
    start = sys.argv[2] if len(sys.argv) > 2 else '2024-01-01'
    conn = get_db()
    df = get_weekly(conn, ticker, start)
    conn.close()
    if df.empty: print('empty'); sys.exit(1)
    s = df['close']; h = df['high']; l = df['low']
    rng = h-l
    v = s.diff(4)/4; vs = ema(v,4)
    a = vs.diff(1); asig = ema(a,4)
    j = asig.diff(1)
    rs = ema(rng,4); rv = rs.diff(1); ra = rv.diff(1)
    for i in range(20, len(s)):
        bw = s.iloc[max(0,i-12):i+1]
        bh = bw.max(); bl = bw.min(); br = (bh-bl)/bl*100 if bl>0 else 999
        if (asig.iloc[i]>0.01 and j.iloc[i]>0.01 and vs.iloc[i]>vs.iloc[i-1] and j.iloc[i]>j.iloc[i-1] and vs.iloc[i]>-1.0 and vs.iloc[i]<0.6 and ra.iloc[i]>0 and br<35):
            print(s.index[i].date(), f'c={s.iloc[i]:.2f}', f'v={vs.iloc[i]:.2f}', f'a={asig.iloc[i]:.3f}', f'j={j.iloc[i]:.3f}', f'volA={ra.iloc[i]:.3f}', f'base={bl:.1f}-{bh:.1f}({br:.1f}%)')
            break
    else:
        print('none')

if __name__=='__main__':
    main()
