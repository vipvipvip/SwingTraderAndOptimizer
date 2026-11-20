#!/usr/bin/env python3
"""Compare TOS DKC_MA_Crossover report with the DB EMA10/20 backtest, 2016+."""
import re
import sys
from datetime import datetime
sys.path.insert(0, '.tmp_research')
import numpy as np
import pandas as pd
import spy_ema10_ema20_daily as m

PATH = '/tmp/opencode/StrategyReports_SPY_111926.csv'
START = pd.Timestamp('2016-01-04')


def money(s):
    s = s.strip().replace('$', '').replace(',', '')
    return -float(s[1:-1]) if s.startswith('(') else float(s)


def parse():
    trades, buys = [], {}
    for line in open(PATH):
        if 'DKC_MA_Crossover' not in line:
            continue
        f = [x.strip() for x in line.split(';')]
        side, px, dt = f[2], money(f[4]), pd.Timestamp(datetime.strptime(f[5], '%m/%d/%y'))
        if 'Buy to Open' in side:
            buys[dt] = px
        elif 'Sell to Close' in side:
            bdt = max(d for d in buys if d <= dt)
            trades.append((buys.pop(bdt), bdt, px, dt))
    return sorted(trades, key=lambda t: t[1])


tos = [t for t in parse() if t[1] >= START]
df = m.load_spy()
df = df[df['date'] <= pd.Timestamp('2026-10-23')].reset_index(drop=True)
dates = df['date'].tolist()
_, eq, expo, my = m.simulate(df)
my = [t for t in my if t[5] and t[1] >= START]
didx = {d: i for i, d in enumerate(dates)}

print(f'TOS round trips from {START.date()}: {len(tos)}')
print(f'My backtest round trips in same window: {len(my)}')

# Match on fill dates.
ts = {(t[1].date(), t[3].date()) for t in tos}
ms = {(t[1].date(), t[3].date()) for t in my}
print(f'Exact (entry-date, exit-date) matches: {len(ts & ms)}/{len(ts)} TOS, '
      f'{len(ts & ms)}/{len(ms)} mine')
print('TOS only:', sorted(ts - ms))
print('Mine only:', sorted(ms - ts))

print('\nFirst/last TOS trades (fill dates, unadj prices):')
for t in tos[:3] + tos[-3:]:
    print(f'  {t[1].date()} {t[0]:>7.2f} -> {t[3].date()} {t[2]:>7.2f}  '
          f'{(t[2]/t[0]-1)*100:>+6.2f}%')

# TOS compounded on trade returns (unadjusted, no costs) vs my DB backtest.
tos_rets = np.array([t[2] / t[0] - 1 for t in tos])
print(f'\nTOS fixed-100-share: {len(tos)*100} shares, '
      f'cum $P/L {sum((t[2]-t[0])*100 for t in tos):,.0f}, '
      f'win {(tos_rets>0).mean()*100:.0f}%')
print(f'TOS trade returns compounded: {np.prod(1+tos_rets):.3f}x '
      f'({(np.prod(1+tos_rets)-1)*100:.1f}%)')
print(f'My DB backtest (adj prices, 5bp costs, full capital): '
      f'{eq[-1]/m.CAPITAL:.3f}x ({(eq[-1]/m.CAPITAL-1)*100:.1f}%)')
bh = df['close'].to_numpy() / df['close'].iloc[0] / (1 + m.COST)
print(f'SPY B&H same window (adj): {bh[-1]:.3f}x ({(bh[-1]-1)*100:.1f}%)')

# Apples-to-apples: my backtest with costs removed, forced to the TOS fill prices.
# Approximate by taking my DB trade returns gross and applying TOS unadj prices on
# the exact paired dates.
paired = []
for t in tos:
    key = (t[1].date(), t[3].date())
    if key in didx:
        pass
mine_by_key = {(t[1].date(), t[3].date()): t for t in my}
gross = []
for buy_dt, _, sell_dt, _ in [(t[1], t[0], t[3], t[2]) for t in tos]:
    k = (buy_dt.date(), sell_dt.date())
    if k in mine_by_key:
        mt = mine_by_key[k]
        gross.append(mt[4] / mt[2] * (1 + m.COST) / (1 - m.COST) - 1)
print(f'\nMy DB returns on the SAME {len(gross)} paired trades, costs removed: '
      f'{np.prod(1+np.array(gross)):.3f}x')
print(f'TOS unadj returns on those trades: {np.prod(1+tos_rets):.3f}x')
print(f'Avg/trade: TOS {tos_rets.mean()*100:+.2f}% vs DB gross {np.mean(gross)*100:+.2f}%')
