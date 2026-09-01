"""
v2 persistent-pool backtest (research prototype) - optimized.

Simulates MTF Stock v2 spec at daily 1 PM cadence:
  ENTRY (all): weekly+daily EMA10>SMA40 ; fresh hourly bull cross (<=FRESH_H) w/ MACD agree ;
               accelerating 200MA (2x15d chunks, both +ve, s2>s1) ; (variant) cross-count cap.
  HOLD: while MACD +ve (L>0 and L>sig) hold, crosses ignored. When MACD -ve, exit on bearish cross.
  SIZING: hold all qualified at equal weight.

Optimization: precompute per-ticker numpy indicator arrays + bull/bear cross index lists once,
then daily eval uses bisect for O(log n) lookups.
"""
import os, sys, bisect
sys.path.insert(0, '/home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf')
from dotenv import load_dotenv
load_dotenv()
import pandas as pd, numpy as np, db
from datetime import datetime, time as dtime

EMASPAN=10; SMASPAN=40; MA200=200
CHUNK=120            # 15 trading days = 120 hourly bars
FRESH_BARS=18        # 1-2 trading days x ~9 hourly bars/day freshness window
HIST_GUARD=True      # MACD histogram momentum guard (matches live runner config)
HIST_PEAK_LOOKBACK=24
HIST_PEAK_FLOOR=0.7
EVAL_HOUR=13
CAPITAL=100000.0
COST=0.0005

def ema_sma_bull(closes):
    if len(closes)<SMASPAN: return False
    s=pd.Series(closes)
    e=s.ewm(span=EMASPAN,adjust=False).mean().iloc[-1]
    m=s.rolling(SMASPAN).mean().iloc[-1]
    return not (pd.isna(e) or pd.isna(m)) and e>m

def macd_pos(ml,ms):
    return ml is not None and ms is not None and ml>ms

class TickerData:
    """Precomputed hourly indicators for one ticker."""
    def __init__(self, bars):
        self.dates=np.array([b[0] for b in bars], dtype=object)
        self.close=np.array([b[1] for b in bars], dtype=float)
        self.ml=np.array([b[2] if b[2] is not None else np.nan for b in bars], dtype=float)
        self.ms=np.array([b[3] if b[3] is not None else np.nan for b in bars], dtype=float)
        self.hist=self.ml-self.ms   # MACD histogram (nan-aware)
        self.atr=np.array([b[4] if b[4] is not None else np.nan for b in bars], dtype=float)
        n=len(self.close)
        s=pd.Series(self.close)
        ema=s.ewm(span=EMASPAN,adjust=False).mean().to_numpy()
        sma=s.rolling(SMASPAN).mean().to_numpy()
        ma200=s.rolling(MA200).mean().to_numpy()
        self.ema=ema; self.sma=sma; self.ma200=ma200
        # bullish crosses with MACD agree; bearish cross indices
        self.bullc=[]  # (idx, age tracked at eval)
        self.beac=[]   # bearish cross indices
        for i in range(1,n):
            if np.isnan(ema[i]) or np.isnan(sma[i]) or np.isnan(ema[i-1]) or np.isnan(sma[i-1]):
                continue
            if ema[i]>sma[i] and ema[i-1]<=sma[i-1]:
                self.bullc.append(i)
            if ema[i]<sma[i] and ema[i-1]>=sma[i-1]:
                self.beac.append(i)
        self.bullc_arr=np.array(self.bullc)
        self.beac_arr=np.array(self.beac)

    def qual(self, idx, MAX_X):
        """Return dict if qualifies at bar idx, else None.
        Entry = MACD +ve (histogram green, ml>ms) at eval AND last bullish CO within FRESH_BARS bars.
        HIST_GUARD: exclude when the MACD histogram has faded below
        HIST_PEAK_FLOOR of its peak over the trailing HIST_PEAK_LOOKBACK bars
        (shorter bars = decelerating drive, even while EMA/SMA CO is +ve)."""
        mlv=self.ml[idx]; msv=self.ms[idx]
        if not macd_pos(mlv,msv): return None
        if HIST_GUARD:
            hist_now=self.hist[idx]
            w0=max(0, idx-HIST_PEAK_LOOKBACK)
            w=self.hist[w0:idx]
            w=w[~np.isnan(w)]
            if w.size and not np.isnan(hist_now):
                if hist_now < float(np.max(w))*HIST_PEAK_FLOOR:
                    return None
        # freshness: last bull CO within FRESH_BARS bars of idx
        pos=bisect.bisect_right(self.bullc_arr, idx)-1
        if pos<0: return None
        bi=int(self.bullc_arr[pos])
        if idx-bi>FRESH_BARS: return None
        ma200v=self.ma200[idx]
        price=self.close[idx]
        if not np.isnan(ma200v) and ma200v>0:
            diff=(price-ma200v)/ma200v*100.0
        else:
            diff=0.0
        m_now=self.ma200[idx]; m_mid=self.ma200[idx-CHUNK]; m_old=self.ma200[idx-2*CHUNK]
        if not (np.isnan(m_now) or np.isnan(m_mid) or np.isnan(m_old)):
            s1=(m_mid-m_old)/m_old*100.0
            s2=(m_now-m_mid)/m_mid*100.0
        else:
            s1=s2=0.0
        # bars below zero before this bull cross
        bars0=0; j=bi-1
        while j>=0 and self.ml[j]<0:
            bars0+=1; j-=1
        return dict(price=price,diff=diff,bars0=bars0,s1=s1,s2=s2,cross_age_bars=idx-bi)

def ema10gt40_bull_series(dates, closes):
    """Return (dates_arr, bull_arr) where bull_arr[i]= EMA10>SMA40 as of bar i (False if invalid)."""
    n=len(closes)
    bull=[False]*n
    s=pd.Series(closes)
    ema=s.ewm(span=EMASPAN,adjust=False).mean().to_numpy()
    sma=s.rolling(SMASPAN).mean().to_numpy()
    for i in range(n):
        if np.isnan(ema[i]) or np.isnan(sma[i]): bull[i]=False
        else: bull[i]=bool(ema[i]>sma[i])
    return np.array(dates, dtype=object), np.array(bull)

def is_bull_on(dates_arr, bull_arr, day, start_t=0):
    """Is the series bullish on 'day' (using state as of its last bar <= day)?"""
    idx=bisect.bisect_right(dates_arr, day)-1
    if idx<0: return False
    return bool(bull_arr[idx])

def load(conn, include_etf=False):
    cur=conn.cursor()
    if include_etf:
        cur.execute("SELECT id,symbol FROM tbl_stock_tickers WHERE enabled=true")
        tickers=cur.fetchall()
    else:
        cur.execute("SELECT id,symbol FROM tbl_stock_tickers WHERE is_etf=false AND enabled=true")
        tickers=cur.fetchall()
    sid={s:t for t,s in tickers}
    # weekly/daily -> precompute bullish series per ticker
    wk_d={}; wk_b={}; dy_d={}; dy_b={}
    wk_raw={}; dy_raw={}
    cur.execute("SELECT ticker_id,date,close FROM tbl_scanner_tickers ORDER BY ticker_id,date")
    for tid,d,c in cur.fetchall(): wk_raw.setdefault(tid,[]).append((d,float(c)))
    cur.execute("SELECT ticker_id,date,close FROM tbl_scanner_tickers_daily ORDER BY ticker_id,date")
    for tid,d,c in cur.fetchall(): dy_raw.setdefault(tid,[]).append((d,float(c)))
    for tid,bars in wk_raw.items():
        dd=[b[0] for b in bars]; cc=[b[1] for b in bars]
        if len(cc)>=SMASPAN:
            wk_d[tid],wk_b[tid]=ema10gt40_bull_series(dd,cc)
    for tid,bars in dy_raw.items():
        dd=[b[0] for b in bars]; cc=[b[1] for b in bars]
        if len(cc)>=SMASPAN:
            dy_d[tid],dy_b[tid]=ema10gt40_bull_series(dd,cc)
    # hourly per ticker -> TickerData
    hr={}
    cur.execute("SELECT ticker_id,date,close,macd_line,macd_signal,atr_stop FROM tbl_scanner_tickers_1hour ORDER BY ticker_id,date")
    for tid,d,c,ml,ms,atr in cur.fetchall():
        hr.setdefault(tid,[]).append((d,float(c),float(ml) if ml is not None else None,float(ms) if ms is not None else None,float(atr) if atr is not None else None))
    tdata={tid:TickerData(bars) for tid,bars in hr.items()}
    return tickers, sid, wk_d, wk_b, dy_d, dy_b, tdata

def run(tickers, sid, wk_d, wk_b, dy_d, dy_b, tdata, start_date, end_date, MAX_X, TOP_N=None, ATR_MULT=None):
    sess=set()
    for td in tdata.values():
        for d in td.dates: sess.add(d.date())
    sess=sorted(s for s in sess if start_date<=s<=end_date)
    positions={}
    cash=CAPITAL
    records=[]
    trades=[]
    for day in sess:
        cutoff=datetime.combine(day, dtime(EVAL_HOUR))
        # EXITS
        for sym in list(positions.keys()):
            td=tdata.get(sid.get(sym))
            if td is None: continue
            idx=bisect.bisect_right(td.dates, cutoff)-1
            if idx<0: continue
            p=positions[sym]
            ml=td.ml[idx]; ms=td.ms[idx]
            exit_px=None
            # A) trailing ATR ratchet stop: close < peak - ATR_MULT*atr
            if ATR_MULT is not None:
                atr=td.atr[idx]
                if not np.isnan(atr) and atr>0:
                    stop=p['peak']-ATR_MULT*atr
                    if td.close[idx]<stop:
                        exit_px=td.close[idx]
            # B) MACD -ve + bearish CO
            if exit_px is None and not macd_pos(ml,ms):
                estart=bisect.bisect_left(td.dates, datetime.combine(p['entry_d'], dtime(9,0)))
                lp=bisect.bisect_left(td.beac_arr, estart)
                if lp < len(td.beac_arr) and td.beac_arr[lp] <= idx:
                    exit_px=td.close[idx]
            if exit_px is not None:
                cash+=p['shares']*exit_px*(1-COST)
                p.update(exit_d=day,exit_px=exit_px,exit_hour=td.dates[idx].hour,
                         ret=exit_px/p['entry_px']*(1-COST)-1)
                trades.append(p)
                del positions[sym]
                continue
            # update running peak (highest close since entry)
            p['peak']=max(p['peak'], td.close[idx])
        # ENTRIES
        if True:
            new=[]
            for tid,sym in tickers:
                if sym in positions: continue
                if tid not in wk_d or tid not in dy_d: continue
                if not is_bull_on(wk_d[tid],wk_b[tid],day) or not is_bull_on(dy_d[tid],dy_b[tid],day): continue
                td=tdata.get(tid)
                if td is None: continue
                idx=bisect.bisect_right(td.dates, cutoff)-1
                if idx<0: continue
                res=td.qual(idx, MAX_X)
                if res is None: continue
                new.append((sym,res,td.dates[idx].hour))
            if new:
                # rank all by freshest CO (lowest cross_age_bars), tie-break by diff desc
                ranked=sorted(new, key=lambda c:(c[1]['cross_age_bars'], -c[1]['diff']))
                if TOP_N is not None:
                    ranked=ranked[:TOP_N]
                ranked=[c for c in ranked if c[0] not in positions]
                if ranked:
                    # total equity = cash + mark-to-market of open positions
                    open_val=0.0
                    for sym,p in positions.items():
                        td0=tdata.get(sid.get(sym))
                        if td0 is None: open_val+=p['shares']*p['entry_px']; continue
                        i0=bisect.bisect_right(td0.dates, cutoff)-1
                        open_val+=p['shares']*(td0.close[i0] if i0>=0 else p['entry_px'])
                    total_eq=cash+open_val
                    final_n=len(positions)+len(ranked)
                    target=total_eq/final_n if final_n>0 else 0
                    for sym,res,eh in ranked:
                        if cash < target:      # can't fund a full target -> skip (no phantom trade)
                            continue
                        shares=target/res['price']*(1-COST)
                        if shares<=0: continue
                        positions[sym]=dict(shares=shares,entry_px=res['price'],entry_d=day,sym=sym,
                                            entry_hour=eh,peak=res['price'],
                                            s1=res['s1'],s2=res['s2'],diff=res['diff'],
                                            bars0=res['bars0'],cross_age_bars=res['cross_age_bars'])
                        cash-=shares*res['price']*(1+COST)
        # MARK
        equity=cash
        for sym,p in positions.items():
            td=tdata.get(sid.get(sym))
            if td is None: equity+=p['shares']*p['entry_px']; continue
            idx=bisect.bisect_right(td.dates, cutoff)-1
            px=td.close[idx] if idx>=0 else p['entry_px']
            equity+=p['shares']*px
        records.append((day,len(positions),equity))
    return trades,records

def main():
    import argparse
    global FRESH_BARS, HIST_GUARD, HIST_PEAK_LOOKBACK, HIST_PEAK_FLOOR
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2024-01-01')
    ap.add_argument('--end',default='2026-08-26')
    ap.add_argument('--max-x',type=int,default=2)
    ap.add_argument('--max-x-none',action='store_true')
    ap.add_argument('--fresh-bars',type=int,default=FRESH_BARS)
    ap.add_argument('--hist-guard',dest='hist_guard',action='store_true',default=HIST_GUARD)
    ap.add_argument('--no-hist-guard',dest='hist_guard',action='store_false')
    ap.add_argument('--hist-lookback',type=int,default=HIST_PEAK_LOOKBACK)
    ap.add_argument('--hist-floor',type=float,default=HIST_PEAK_FLOOR)
    ap.add_argument('--top-n',type=int,default=None,help='buy only the N freshest CO names per day (None=all)')
    ap.add_argument('--atr-mult',type=float,default=None,help='trailing ATR ratchet stop multiplier (None=off)')
    ap.add_argument('--out',default=None,help='write per-trade CSV report to this path')
    ap.add_argument('--symbols',default=None,help='comma-separated symbols to backtest only (e.g. QQQ)')
    args=ap.parse_args()
    FRESH_BARS=args.fresh_bars
    HIST_GUARD=args.hist_guard
    HIST_PEAK_LOOKBACK=args.hist_lookback
    HIST_PEAK_FLOOR=args.hist_floor
    MAX_X=None if args.max_x_none else args.max_x
    conn=db.get_conn()
    print("loading data...")
    ticketers,sid,wk_d,wk_b,dy_d,dy_b,tdata=load(conn, include_etf=bool(args.symbols))
    if args.symbols:
        want=set(x.strip().upper() for x in args.symbols.split(','))
        ticketers=[(t,s) for t,s in ticketers if s in want]
        sid={s:t for t,s in ticketers}
    print(f"universe {len(ticketers)}, tdata {len(tdata)}")
    start=datetime.strptime(args.start,'%Y-%m-%d').date()
    end=datetime.strptime(args.end,'%Y-%m-%d').date()
    trades,records=run(ticketers,sid,wk_d,wk_b,dy_d,dy_b,tdata,start,end,MAX_X,
                       TOP_N=args.top_n, ATR_MULT=args.atr_mult)
    wins=[t for t in trades if t['ret']>0]
    print(f"\n=== RESULTS (window {args.start}..{args.end}, MAX_X={MAX_X}) ===")
    print(f"Closed trades: {len(trades)}")
    if trades:
        avg=sum(t['ret'] for t in trades)/len(trades)
        print(f"  win rate: {len(wins)/len(trades)*100:.1f}%")
        print(f"  avg trade return (incl cost): {avg*100:+.2f}%")
        print(f"  avg hold (days): {sum((t['exit_d']-t['entry_d']).days for t in trades)/len(trades):.1f}")
        rets=sorted(t['ret'] for t in trades)
        print(f"  best {rets[-1]*100:+.1f}%  worst {rets[0]*100:+.1f}%")
        print(f"  avg pool size: {sum(r[1] for r in records)/len(records):.1f}")
    if records:
        start_eq=records[0][2]; end_eq=records[-1][2]
        peak=None; mdd=0
        for _,_,eq in records:
            if peak is None or eq>peak: peak=eq
            dd=(eq-peak)/peak
            if dd<mdd: mdd=dd
        tot=end_eq/CAPITAL-1
        years=max((records[-1][0]-records[0][0]).days/365.25,0.01)
        print(f"\nEquity: {start_eq:.0f} -> {end_eq:.0f}  (total {tot*100:+.1f}%, CAGR {((1+tot)**(1/years)-1)*100:+.1f}% over {years:.1f}y)")
        print(f"  max drawdown: {mdd*100:.1f}%")

    if args.out and trades:
        import csv
        with open(args.out,'w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['symbol','entry_date','entry_hour','exit_date','exit_hour','entry_px','exit_px','shares',
                        'gross_pnl','net_pnl','ret_pct','hold_days','diff_pct','s1_15d',
                        's2_15d','bars_below_zero','cross_age_bars','win'])
            for t in sorted(trades,key=lambda x:x['entry_d']):
                gross=t['exit_px']-t['entry_px']
                entry_cost=t['entry_px']*COST; exit_cost=t['exit_px']*COST
                net=gross-entry_cost-exit_cost
                w.writerow([t['sym'],t['entry_d'],t.get('entry_hour',''),t['exit_d'],t.get('exit_hour',''),
                            f"{t['entry_px']:.2f}",f"{t['exit_px']:.2f}",f"{t['shares']:.2f}",
                            f"{gross*t['shares']:.2f}",f"{net*t['shares']:.2f}",
                            f"{t['ret']*100:.2f}",(t['exit_d']-t['entry_d']).days,
                            f"{t['diff']:.2f}",f"{t['s1']:.2f}",f"{t['s2']:.2f}",
                            t['bars0'],f"{t['cross_age_bars']:.1f}",
                            'W' if t['ret']>0 else 'L'])
        print(f"\nTrade report written: {args.out} ({len(trades)} rows)")

if __name__=='__main__':
    main()
