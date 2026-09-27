"""As-of (no-lookahead) guard for the trio backtester.

The rule this module enforces: a bar may only be read at a decision instant if
that bar's CONTENT has already materialized. Content is not the label.

A weekly bar is stamped at the ISO-week start (Monday) but carries that week's
FINAL close, so the row dated 2026-09-21 holds Friday 2026-09-25's close. Live,
the gate reads it on Monday 2026-09-28: content exists Fri 16:00 ET, the decision
happens Mon 09:35 ET, the fill happens Mon. That ordering is honest and it is the
live behaviour. The same row read on 2026-09-21 is four days early.

`content_end()` derives a bar's content boundary from the label plus the bar
duration, using pure calendar arithmetic. It never reads a price, so the guard
cannot peek and mask the very lookahead it exists to catch. Every auditor below
is therefore a function of labels and dates alone.

Lead days are reported as (content_end - decision_date): positive means the bar's
content had not yet formed when the decision was taken.
"""
from datetime import date, timedelta
from collections import namedtuple

WEEKLY = 'weekly'
DAILY = 'daily'

_DURATION = {
    WEEKLY: timedelta(days=7),
    DAILY: timedelta(days=1),
}


def content_end(label, timeframe):
    """First instant at which the bar labelled `label` is fully known.

    Exclusive boundary: a weekly bar stamped Monday W is only complete once the
    ISO week has closed, so its content ends at the start of W+7. A daily bar
    dated d is complete at the start of d+1.
    """
    if timeframe not in _DURATION:
        raise ValueError(f'unknown timeframe {timeframe!r}')
    return label + _DURATION[timeframe]


Violation = namedtuple('Violation', 'day bar_label content_end lead_days')
Report = namedtuple('Report', 'name checked violations worst_lead')


def audit_weekly(daily_dates, w_dates, ref, name):
    """Audit a day -> weekly-bar-index mapping.

    `ref[i]` is the index into `w_dates` that the variant consults on
    `daily_dates[i]`. Each consulted bar must have been complete by that day.
    """
    violations = []
    worst = 0
    for i, d in enumerate(daily_dates):
        wi = ref[i]
        if wi is None or wi < 0:
            continue
        end = content_end(w_dates[wi], WEEKLY)
        lead = (end - d).days
        if lead > worst:
            worst = lead
        if lead > 0:
            violations.append(Violation(d, w_dates[wi], end, lead))
    return Report(name, len(daily_dates), violations, worst)


def settled_weekly_ref(daily_dates, w_dates):
    """Index of the last weekly bar whose content has fully formed by each day."""
    ref = []
    j = -1
    for d in daily_dates:
        while j + 1 < len(w_dates) and content_end(w_dates[j + 1], WEEKLY) <= d:
            j += 1
        ref.append(j)
    return ref


def in_progress_weekly_ref(daily_dates, w_dates):
    """The legacy mapping: the Monday-dated row for the week currently in
    progress. Retained only as a negative control -- every day reads a bar whose
    content ends a full week later."""
    ref = []
    j = -1
    for d in daily_dates:
        while j + 1 < len(w_dates) and w_dates[j + 1] <= d:
            j += 1
        ref.append(j)
    return ref


def audit_daily_close(daily_dates, name):
    """Audit the close-of-day convention used by the SMA-gate family.

    A daily bar dated d is complete at d's close. The gate decides on d's close
    and holds from the next session, so the state must already exist by the hold
    date. Auditing against the hold date (not the decision date) is what makes
    the zero-lead result meaningful: content_end(d) lands exactly on the boundary
    the hold begins, never past it. Across a weekend the lead goes negative --
    extra settled time, not a leak.
    """
    violations = []
    for i in range(1, len(daily_dates)):
        hold = daily_dates[i]
        bar = daily_dates[i - 1]
        end = content_end(bar, DAILY)
        lead = (end - hold).days
        if lead > 0:
            violations.append(Violation(hold, bar, end, lead))
    worst = max((v.lead_days for v in violations), default=0)
    return Report(name, len(daily_dates) - 1, violations, worst)


def render(reports):
    """Human-readable audit table."""
    lines = []
    for r in reports:
        status = 'PASS' if not r.violations else 'FAIL'
        lines.append(
            f'  {status}  {r.name:<34s} {r.checked:>5d} reads  '
            f'worst lead {r.worst_lead:>2d}d  violations {len(r.violations):>5d}'
        )
        for v in r.violations[:3]:
            lines.append(
                f'          first: {v.day} read bar dated {v.bar_label} '
                f'(content ends {v.content_end}, {v.lead_days}d early)'
            )
    return '\n'.join(lines)


def enforce(reports, label='as-of guard'):
    """Hard precondition: abort the run if any audited variant reads ahead."""
    failed = [r for r in reports if r.violations]
    if not failed:
        return
    print(f'\nLOOKAHEAD DETECTED -- {label} failed:\n')
    print(render(failed))
    raise SystemExit(
        'Refusing to report results from a variant that reads bars before their '
        'content exists. Fix the day->bar mapping (see asof.settled_weekly_ref) '
        'or re-run the lookahead-free variant.'
    )
