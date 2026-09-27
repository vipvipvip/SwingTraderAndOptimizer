"""EG100 data acquisition: read-only DB loads + one read-only shell-out to
the live gate's --json diagnostic, used purely as a ground-truth check.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from acquire_ohlc import load_daily

BACKEND_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'swingtrader', 'backend'))


def load_eg_legs(conn, symbols=None):
    """{symbol: DataFrame(date, open, high, low, close, volume)} for each of
    config.EG_LEGS (or `symbols`) -- settled daily bars only (load_daily's
    `date < CURRENT_DATE` guard), same source table/rule replayIndexEgGate
    reads (tbl_scanner_tickers_daily, is_etf legs)."""
    symbols = symbols or config.EG_LEGS
    return {s: load_daily(conn, s) for s in symbols}


def fetch_live_flip_ground_truth(span=None):
    """Shells out to `php artisan trades:execute-EW-gate100 --json`, which
    hits TradeExecutorService::indexEgGateState() -> replayIndexEgGate() -- a
    read-only DB read with NO Alpaca calls, no orders, no dedupe-file writes
    (confirmed from source: the --json branch returns before the clock check
    and the warm-up gate; replayIndexEgGate itself is a plain DB SELECT).

    Returns the parsed JSON dict: last_date/index/ema/bars/signal_changes/
    last_flip/flips (each {date, to}).
    """
    span = span or config.EG_SPAN
    cmd = ['php', '-d', 'xdebug.mode=off', '-d', 'display_errors=0',
           'artisan', 'trades:execute-EW-gate100', '--json', f'--span={span}']
    proc = subprocess.run(cmd, cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120)
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if payload is None:
        raise RuntimeError(
            f'could not parse EG100 ground truth from `{" ".join(cmd)}`\n'
            f'stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}')
    if payload.get('error'):
        raise RuntimeError(f'EG100 gate state error: {payload["error"]}')
    return payload
