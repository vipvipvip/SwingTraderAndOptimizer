#!/usr/bin/env python3
import sys
import pandas as pd
import psycopg2

def get_db():
    return psycopg2.connect(host='localhost', port=5432, dbname='swingtrader', user='swingtrader', password='swingtrader_dev_password')

def get_prices(conn, symbol, timeframe='daily', start=None):
    table = 'tbl_prices_daily' if timeframe == 'daily' else 'tbl_prices_weekly'
    q = f"""SELECT w.date, w.close, w.high, w.low
           FROM {table} w
           JOIN tbl_stock_tickers t ON t.id = w.ticker_id
           WHERE t.symbol=%s"""
    params = [symbol.upper()]
    if start: q += " AND w.date >= %s"; params.append(start)
    q += " ORDER BY w.date ASC"
    cur = conn.cursor(); cur.execute(q, params); rows = cur.fetchall(); cur.close()
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows, columns=['date','close','high','low'])
    df['date']=pd.to_datetime(df['date']); df.set_index('date',inplace=True)
    for c in ['close','high','low']: df[c]=df[c].astype(float)
    return df

def ema(s,span): return s.ewm(span=span, adjust=False).mean()

def detect_imminent(s, h, l, vspan=5, smooth=3):
    rng = h-l
    v = s.diff(vspan)/vspan if vspan>0 else s.diff(1)
    vs = ema(v, smooth)
    a = vs.diff(1); asig = ema(a, smooth)
    j = asig.diff(1)
    rs = ema(rng, smooth); rv = rs.diff(1); ra = rv.diff(1)
    for i in range(30, len(s)):
        bw = s.iloc[max(0,i-20):i+1]
        bh = bw.max(); bl = bw.min(); br = (bh-bl)/bl*100 if bl>0 else 999
        if (asig.iloc[i] > 0.1 and j.iloc[i] > 0.1 and vs.iloc[i] > vs.iloc[i-1] and j.iloc[i] > j.iloc[i-1] and vs.iloc[i] < 3 and vs.iloc[i] > -1.5 and ra.iloc[i] > 0.5 and br < 30):
            return {'date': s.index[i].date(), 'close': s.iloc[i], 'v': vs.iloc[i], 'a': asig.iloc[i], 'j': j.iloc[i], 'ra': ra.iloc[i], 'br': br}
    return None

def main():
    if len(sys.argv) < 2:
        print('usage: jerk_detect.py TICKER [daily|weekly] [start]')
        sys.exit(1)
    ticker = sys.argv[1]
    tf = sys.argv[2] if len(sys.argv) > 2 else 'daily'
    start = sys.argv[3] if len(sys.argv) > 3 else ('2026-01-01' if tf=='daily' else '2024-01-01')
    conn = get_db()
    df = get_prices(conn, ticker, timeframe=tf, start=start)
    conn.close()
    if df.empty:
        print('empty'); return
    res = detect_imminent(df['close'], df['high'], df['low'], vspan=5 if tf=='daily' else 4, smooth=3)
    if res is None:
        print('none')
    else:
        r = res
        print(f"{r['date']} c={r['close']:.2f} v={r['v']:.2f} a={r['a']:.3f} j={r['j']:.3f} ra={r['ra']:.3f} br={r['br']:.1f}%")

if __name__=='__main__':
    main()
