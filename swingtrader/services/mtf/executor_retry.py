#!/usr/bin/env python3
"""MTF daily executor with a bounded retry loop around the score step.

Why this exists
---------------
The 10:25 ET timer runs the emasma score step on settled daily bars and then
executes whatever the score step saved to `mtf_pending`. Both steps depend on
the scanner backfills being complete for the universe, and this box's mornings
are fragile: the 09:00 scanner-update timer usually fires on boot (~09:32) and
`Persistent=true` only just beats the executor, so a single attempt can face a
half-populated universe.

A failed attempt used to end the day silently. On 2026-09-28 the score step
produced zero candidates for BOTH legs (1,435/1,435 tickers excluded), the
execute step skipped the stale pending, the process exited 0, and the run still
posted a normal-looking sector/regime recap — the missed rotation was only
noticed by hand.

Contract
--------
1. Retry the score step until it has all the tickers' data (a successful score
   for BOTH legs -> exit 0) or until market close (16:00 ET).
2. Then run the execute step once, and exit.
3. Never run past the close. systemd will not start a second instance of a
   still-active oneshot, so a runaway loop would silently skip the next
   morning's run entirely — the 16:00 stop is what keeps tomorrow's 10:25
   trigger free. The unit also carries `RuntimeMaxSec` as a second backstop.

Each attempt re-runs the score step's own self-heal (backfill when the frontier
is stale, then the Data Readiness Gate), so waiting is what actually acquires
the missing bars. A healthy attempt with data already in place is cheap
(seconds); the expensive path only triggers when data is genuinely behind.
"""
import argparse
import os
import subprocess
import sys
import time as time_mod
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as db_module          # noqa: E402
import runner                   # noqa: E402

NY = ZoneInfo('America/New_York')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(BASE_DIR, 'runner.py')

# Hard stop: the last moment a retry loop may start an attempt. Anything later
# is left to tomorrow's 10:25 timer (and the 16:45 recap scorer is free of
# collisions because we are gone by then).
MARKET_CLOSE_ET = dt_time(16, 0)
DEFAULT_RETRY_MIN = 30
# Safety valve: ~12 attempts at the default cadence already spans 10:25->16:00,
# so this only bites when --retry-min is set very low.
MAX_ATTEMPTS = 12


def _now():
    return datetime.now(NY)


def _run_step(action, dry_run=False, strategy='emasma'):
    """Run one runner step. Returns its exit code (0 = the step got everything
    it needed, non-zero = at least one leg failed or produced nothing)."""
    cmd = [sys.executable, RUNNER, '--action', action, '--mode', 'all', '--strategy', strategy]
    if dry_run:
        cmd.append('--dry-run')
    print(f'[MTF-RETRY] $ {" ".join(cmd)}', flush=True)
    return subprocess.run(cmd).returncode


def retry_score(step, stop_at=MARKET_CLOSE_ET, retry_min=DEFAULT_RETRY_MIN,
                max_attempts=MAX_ATTEMPTS, now_fn=_now, sleep_fn=time_mod.sleep):
    """Call `step` until it succeeds or we hit the market-close stop.

    Returns (ok, attempts). Injectable clock/sleeper keep the control flow
    testable without waiting on wall time.
    """
    attempt = 0
    while True:
        attempt += 1
        rc = step()
        if rc == 0:
            print(f'[MTF-RETRY] score step OK on attempt {attempt} — all tickers loaded', flush=True)
            return True, attempt

        now = now_fn()
        deadline = now.replace(hour=stop_at.hour, minute=stop_at.minute, second=0, microsecond=0)
        if now >= deadline:
            print(f'[MTF-RETRY] {now:%H:%M} ET is at/after the {stop_at:%H:%M} ET stop — '
                  f'giving up after {attempt} attempt(s). No trades today; '
                  f'tomorrow\'s 10:25 run picks the signal set back up.', flush=True)
            return False, attempt
        if attempt >= max_attempts:
            print(f'[MTF-RETRY] attempt cap ({max_attempts}) reached — giving up at '
                  f'{now:%H:%M} ET.', flush=True)
            return False, attempt

        nap = min(retry_min * 60, (deadline - now).total_seconds())
        print(f'[MTF-RETRY] score step FAILED (rc={rc}) at {now:%H:%M} ET — sleeping '
              f'{nap / 60:.0f}m, then attempt {attempt + 1} (hard stop {stop_at:%H:%M} ET)',
              flush=True)
        sleep_fn(nap)


def _last_score_runs():
    """Last score-run status per mode, for the give-up alert body."""
    out = []
    try:
        conn = runner._get_db_conn()
        try:
            for mode in ('stock', 'etf'):
                run_row = db_module.get_last_run(conn, mode, 'score')
                if run_row:
                    out.append(f"{runner.MODE_LABEL[mode]}: {run_row['status']} "
                               f"(sig {run_row['sig_date']}) {run_row['detail'] or ''}".strip())
                else:
                    out.append(f"{runner.MODE_LABEL[mode]}: no run recorded")
        finally:
            conn.close()
    except Exception as exc:  # never let alerting itself mask the failure
        out.append(f'(could not read mtf_runs: {exc})')
    return '\n'.join(f'  • {line}' for line in out)


def _alert_giveup(attempts, now=None):
    now = now or _now()
    runner._send_slack_alert(
        f'GAVE UP at {now:%H:%M} ET after {attempts} score attempt(s) — the score step '
        f'never got all the tickers\' data, so NO MTF orders were placed today. '
        f'Tomorrow\'s 10:25 run retries from scratch.\n{_last_score_runs()}', 'all')


def main():
    p = argparse.ArgumentParser(description='MTF emasma daily executor: score (retrying) + execute')
    p.add_argument('--dry-run', action='store_true',
                   help='forward --dry-run to both steps (rotation preview, no orders)')
    p.add_argument('--no-execute', action='store_true',
                   help='run/retry the score step only; never place orders')
    p.add_argument('--stop-at', default='16:00', metavar='HH:MM',
                   help='ET hard stop for starting a new attempt (default 16:00 = market close)')
    p.add_argument('--retry-min', type=float, default=DEFAULT_RETRY_MIN,
                   help=f'minutes between failed attempts (default {DEFAULT_RETRY_MIN})')
    p.add_argument('--max-attempts', type=int, default=MAX_ATTEMPTS,
                   help=f'attempt cap (default {MAX_ATTEMPTS})')
    p.add_argument('--strategy', default='emasma', help='runner strategy (default emasma)')
    args = p.parse_args()

    stop_at = dt_time(*(int(x) for x in args.stop_at.split(':')))
    print(f'[MTF-RETRY] {datetime.now(NY):%Y-%m-%d %H:%M} ET — score retries every '
          f'{args.retry_min:g}m until {stop_at:%H:%M} ET, then execute '
          f'(dry_run={args.dry_run}, no_execute={args.no_execute})', flush=True)

    ok, attempts = retry_score(
        lambda: _run_step('score', dry_run=args.dry_run, strategy=args.strategy),
        stop_at=stop_at, retry_min=args.retry_min, max_attempts=args.max_attempts)

    if not ok:
        _alert_giveup(attempts)
        return 1

    if args.no_execute:
        print('[MTF-RETRY] --no-execute: score only, no orders placed', flush=True)
        return 0

    rc = _run_step('execute', dry_run=args.dry_run, strategy=args.strategy)
    if rc != 0:
        runner._send_slack_alert(
            f'execute step exited {rc} after a successful score — check '
            f'`journalctl -u swingtrader-mtf-executor` and mtf_runs for the leg.', 'all')
        return rc
    return 0


if __name__ == '__main__':
    sys.exit(main())
