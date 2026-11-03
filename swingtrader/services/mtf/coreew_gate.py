#!/usr/bin/env python3
"""CoreEW P20w market-gate reader for the MTF stock leg.

Consumes the live PHP-canonical `trades:coreew-leg-ema-series` payload so the
Python side never re-implements the EMA crossover (safety rail). The live
series only contains settled weekly bars, so the last point is actionable on
the next trading day.
"""

import json
import os
import subprocess
import time

LEGS = ('QQQ', 'VTI', 'VTV')


def _backend_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', '..', 'backend'))


def parse_payload(payload, symbols=LEGS):
    """Return ({symbol: bool long}, week) from an artisan series payload."""
    if not payload or payload.get('error') or not payload.get('series'):
        err = (payload or {}).get('error') or 'empty series'
        raise RuntimeError(f'leg-EMA series failed: {err}')
    states = {}
    weeks = set()
    for sym in symbols:
        pts = payload['series'].get(sym)
        if not pts:
            raise RuntimeError(f'leg-EMA series missing {sym}')
        last = pts[-1]
        if 'long' not in last or 'week' not in last:
            raise RuntimeError(f'leg-EMA series malformed for {sym}: {last}')
        states[sym] = bool(last['long'])
        weeks.add(str(last['week'])[:10])
    if len(weeks) != 1:
        raise RuntimeError(f'leg-EMA series weeks disagree: {sorted(weeks)}')
    return states, weeks.pop()


def _parse_last_json(stdout):
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def fetch_leg_states(span=20, symbols=LEGS, timeout=120, retries=2):
    """Shell the artisan command and return ({symbol: long}, settled week)."""
    php = '/usr/bin/php' if os.path.exists('/usr/bin/php') else 'php'
    cmd = [php, '-d', 'xdebug.mode=off', '-d', 'display_errors=0',
           'artisan', 'trades:coreew-leg-ema-series',
           f'--span={span}', '--symbols=' + ','.join(symbols)]
    last_err = None
    for attempt in range(max(1, retries)):
        try:
            proc = subprocess.run(cmd, cwd=_backend_dir(), capture_output=True,
                                  text=True, timeout=timeout)
            payload = _parse_last_json(proc.stdout)
            if payload is None:
                raise RuntimeError(
                    f'could not parse leg-EMA JSON (rc={proc.returncode}); '
                    f'stdout={proc.stdout[-1000:]!r} stderr={proc.stderr[-1000:]!r}')
            return parse_payload(payload, symbols)
        except Exception as exc:  # noqa: BLE001 - retry any transport/parse failure
            last_err = exc
            if attempt + 1 < max(1, retries):
                time.sleep(2)
    raise RuntimeError(f'leg-EMA series unavailable: {last_err}')


def gate_off(states, mode='any', symbols=LEGS):
    """True when the configured leg rule says the stock book should be in cash."""
    on = sum(1 for s in symbols if states.get(s))
    if mode == 'any':
        return on < 1
    if mode == 'majority':
        return on < 2
    if mode == 'all':
        return on < len(symbols)
    if mode == 'qqq':
        return not bool(states.get('QQQ'))
    raise ValueError(f'unknown market gate mode: {mode}')


def describe(states, mode='any', span=20, week=None, symbols=LEGS):
    """Human-readable one-liner for the Slack digest."""
    on = [s for s in symbols if states.get(s)]
    off = gate_off(states, mode, symbols)
    leg_txt = ' '.join(f'{s}={"ON" if states.get(s) else "OFF"}' for s in symbols)
    wk = f' week {week}' if week else ''
    state = 'CASH' if off else 'INVESTED'
    return (f'P{span}w {mode}: {leg_txt} ({len(on)}/{len(symbols)} on){wk} '
            f'-> {state}')
