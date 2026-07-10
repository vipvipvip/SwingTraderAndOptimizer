#!/usr/bin/env python3
"""MTCS chart: price + sine/lead overlay."""
import sys
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import config
import db as db_module
import spectral


def chart(symbol, save=None):
    import matplotlib
    if save or not os.environ.get('DISPLAY'):
        matplotlib.use('Agg')
    db_module.init_db()
    conn = db_module.get_conn()
    tid = db_module.get_ticker_id(conn, symbol)
    if not tid:
        print(f'Ticker {symbol} not found')
        return

    closes, count = db_module.get_daily_candles(conn, tid)
    if count < config.WARMUP_BARS:
        print(f'{symbol}: only {count} bars, need {config.WARMUP_BARS}')
        return

    prices = np.array(closes)
    dc = spectral.dominant_cycle(prices)
    sine = dc['sine_smoothed']
    lead = dc['lead_smoothed']
    fft = dc.get('fft_cycles', [])
    cycles = ', '.join(f"{c['period']}d" for c in fft[:3]) if fft else '--'

    s0, s1 = sine[-2], sine[-1]
    l0, l1 = lead[-2], lead[-1]
    buy = s0 < l0 and s1 >= l1
    sell = s0 > l0 and s1 <= l1
    sig = 'BUY' if buy else ('SELL' if sell else 'NONE')

    pos = db_module.get_position(conn, tid)
    in_pos = pos is not None and float(pos[1]) > 0

    conn.close()

    cur = prices[-1]
    print(f'{symbol}: ${cur:.2f}  signal={sig}  in_pos={in_pos}  cycles={cycles}')

    dates = dc['dates'] if 'dates' in dc else np.arange(len(prices))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), gridspec_kw={'height_ratios': [2, 1]})
    fig.suptitle(f'{symbol} — MTCS Hilbert Transform Cycle', fontsize=13, fontweight='bold')

    ax1.plot(dates, prices, color='#e1e4e8', linewidth=1, label='Close')
    ax1.set_ylabel('Price')
    ax1.grid(True, alpha=0.15)
    ax1.legend(loc='upper left')

    ax2.axhline(0, color='#4a4d59', linewidth=0.5)
    ax2.plot(dates, sine, color='#58a6ff', linewidth=1.2, label='Sine')
    ax2.plot(dates, lead, color='#f85149', linewidth=1.2, label='Lead')
    ax2.set_ylabel('Cycle')
    ax2.grid(True, alpha=0.15)
    ax2.legend(loc='upper left')

    if buy:
        ax2.axvline(x=dates[-1], color='#3fb950', linestyle='--', alpha=0.6, label='BUY')
    elif sell:
        ax2.axvline(x=dates[-1], color='#f85149', linestyle='--', alpha=0.6, label='SELL')

    for ax in (ax1, ax2):
        ax.set_xlabel('')
        if isinstance(dates[0], datetime):
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())

    info = f'Cycles: {cycles}  |  Signal: {sig}  |  Position: {in_pos}  |  Close: ${cur:.2f}'
    fig.text(0.5, 0.01, info, ha='center', fontsize=9, color='#8b949e')

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    if save:
        path = os.path.join(os.path.dirname(__file__), save)
        fig.savefig(path, dpi=150, bbox_inches='tight')
        print(f'  Chart saved to {path}')
    else:
        plt.show()


if __name__ == '__main__':
    symbols = sys.argv[1:] if len(sys.argv) > 1 else config.TICKERS
    for sym in symbols:
        chart(sym.upper())
        print()
