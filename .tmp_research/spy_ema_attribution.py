#!/usr/bin/env python3
"""Attribute the SPY EMA10/20-vs-B&H return gap by day type and trade timing."""
import sys
sys.path.insert(0, '.tmp_research')
import numpy as np
import pandas as pd
import spy_ema10_ema20_daily as m

df = m.load_spy()
dates = df['date'].tolist()
opn, close = df['open'].to_numpy(), df['close'].to_numpy()
e10, e20 = m.ema(close, 10), m.ema(close, 20)
n = len(df)
signal = np.where(np.isfinite(e10) & np.isfinite(e20), e10 > e20, None)

held = False
cash, shares = m.CAPITAL, 0.0
eq = np.zeros(n)
kind = ['warmup'] * n
for i in range(n):
    action = 'none'
    if i > 0 and signal[i - 1] is not None:
        sig = bool(signal[i - 1])
        if sig and not held:
            action = 'entry'
            shares = cash / (opn[i] * (1 + m.COST))
            cash = 0.0
            held = True
        elif not sig and held:
            action = 'exit'
            cash = shares * opn[i] * (1 - m.COST)
            shares = 0.0
            held = False
    eq[i] = cash + shares * close[i]
    kind[i] = action if action != 'none' else ('long' if held else 'cash')

bh = close / close[0] * m.CAPITAL / (1 + m.COST)
sl = np.diff(np.log(eq))
ml = np.diff(np.log(bh))
gap = sl - ml
kind = np.array(kind[1:])

print(f'Log-return gap: strategy {np.log(eq[-1]/m.CAPITAL):.4f}  '
      f'B&H {np.log(bh[-1]/m.CAPITAL):.4f}  diff {np.log(eq[-1]/m.CAPITAL)-np.log(bh[-1]/m.CAPITAL):.4f}')
print(f'Sum of daily gaps: {gap.sum():.4f}\n')
print('Attribution by day type (log-return points, negative = lost vs B&H):')
for k in ('cash', 'long', 'entry', 'exit', 'warmup'):
    mask = kind == k
    if mask.sum() == 0:
        continue
    print(f'  {k:<7} days {mask.sum():>4}  strategy {sl[mask].sum():>+8.4f}  '
          f'B&H {ml[mask].sum():>+8.4f}  gap {gap[mask].sum():>+8.4f}')

print('\nBiggest MISSED up days while in cash:')
idx = np.where(kind == 'cash')[0]
top = sorted(idx, key=lambda i: -ml[i])[:12]
for i in top:
    print(f'  {dates[i+1].date()}  mkt {np.expm1(ml[i])*100:>+6.2f}%  '
          f'strat {np.expm1(sl[i])*100:>+6.2f}%  missed {ml[i]*100:>+6.2f} log pts')

print('\nBiggest AVOIDED down days while in cash:')
top = sorted(idx, key=lambda i: ml[i])[:12]
for i in top:
    print(f'  {dates[i+1].date()}  mkt {np.expm1(ml[i])*100:>+6.2f}%  '
          f'strat {np.expm1(sl[i])*100:>+6.2f}%  saved {-ml[i]*100:>+6.2f} log pts')

print('\nCash-day market move summarised:')
cash_ml = ml[kind == 'cash']
print(f'  cash days {len(cash_ml)}, mkt sum {cash_ml.sum():+.4f} log = '
      f'{(np.exp(cash_ml.sum())-1)*100:+.1f}% cumulative')
print(f'  up days {(cash_ml>0).sum()} ({np.expm1(cash_ml[cash_ml>0]).mean()*100:+.2f}% avg), '
      f'down days {(cash_ml<0).sum()} ({np.expm1(cash_ml[cash_ml<0]).mean()*100:+.2f}% avg)')

# Trade-level: strategy timing vs B&H over the exact same holding windows.
_, _, _, trades = m.simulate(df)
didx = {d: i for i, d in enumerate(dates)}
rows = []
for t in trades:
    if not t[5]:
        continue
    ei, xi = didx[t[1]], didx[t[3]]
    sret = t[4] / t[2] * (1 - m.COST) / (1 + m.COST) - 1
    bret = close[xi] / close[ei] - 1
    rows.append((t[1].date(), t[3].date(), sret, bret, sret - bret))
arr = np.array([r[2:] for r in rows])
print(f'\nTrade timing ({len(rows)} closed round trips):')
print(f'  strategy avg/roundtrip {arr[:,0].mean()*100:+.2f}%  median {np.median(arr[:,0])*100:+.2f}%')
print(f'  B&H same windows      {arr[:,1].mean()*100:+.2f}%  median {np.median(arr[:,1])*100:+.2f}%')
print(f'  timing edge (s-BH)    {arr[:,2].mean()*100:+.2f}%  '
      f'wins {np.sum(arr[:,2]>0)}/{len(rows)}')
print(f'  compounded: strategy {np.prod(1+arr[:,0]):.3f}x  B&H windows {np.prod(1+arr[:,1]):.3f}x')
print(f'  total cost drag approx {(((1-m.COST)/(1+m.COST))**len(rows))-1:.4f} '
      f'({(1-((1-m.COST)/(1+m.COST))**len(rows))*100:.1f}% of compounded capital)')
print(f'\nCash days split: up log sum {cash_ml[cash_ml>0].sum():+.4f}, '
      f'down log sum {cash_ml[cash_ml<0].sum():+.4f}')
