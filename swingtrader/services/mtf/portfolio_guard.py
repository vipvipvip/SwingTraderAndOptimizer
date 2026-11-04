"""Pure portfolio HWM-stop + profit-sweep state machine.

This module is intentionally importable by both live execution and backtests.
It owns *policy only*: no DB, no Alpaca, no orders, no config module, no wall
clock. The caller supplies:

  * total equity, including the reserve;
  * a stable session id (date/bar id);
  * the persisted GuardState.

and applies the returned GuardDecision with its own execution adapter.

Rules
-----
* HWM stop: if total equity <= HWM * (1 - hwm_stop_pct), return
  ``liquidate=True`` and pause new buys for ``cooldown_sessions`` sessions.
  ``allow_stop=False`` still updates the HWM but defers the stop check, which
  lets a caller run a weekly-close stop or a disaster stop on chosen sessions.
* Profit sweep: on each new total-equity high, move ``sweep_pct`` of the gain
  into ``reserve``. The reserve is never re-invested by this module.
* One mark per session: re-calling with the same session id is a no-op, so a
  live rerun cannot double-sweep.

``step`` returns the *requested* sweep and advances ``sweep_hwm``; it does not
move cash. The execution adapter must call ``state.record_sweep(actual)`` after
the fill so the persisted reserve reflects money actually moved.

The caller must size the active book from ``total_equity - state.reserve`` and
must keep the reserve out of buying power.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class GuardConfig:
    """Per-account policy. Percentages are fractions: 0.06 == 6%."""

    hwm_stop_pct: float = 0.0
    sweep_pct: float = 0.0
    cooldown_sessions: int = 5
    min_sweep: float = 0.0
    reset_hwm_on_stop: bool = True

    def __post_init__(self):
        if not 0.0 <= self.hwm_stop_pct < 1.0:
            raise ValueError('hwm_stop_pct must be in [0, 1)')
        if not 0.0 <= self.sweep_pct <= 1.0:
            raise ValueError('sweep_pct must be in [0, 1]')
        if self.cooldown_sessions < 0:
            raise ValueError('cooldown_sessions must be >= 0')
        if self.min_sweep < 0:
            raise ValueError('min_sweep must be >= 0')

    @property
    def enabled(self) -> bool:
        return self.hwm_stop_pct > 0.0 or self.sweep_pct > 0.0


@dataclass
class GuardState:
    """Serializable state. One instance per (account, strategy)."""

    hwm: float
    reserve: float = 0.0
    pause_sessions: int = 0
    last_session: str | None = None
    last_action: str = ''
    swept_total: float = 0.0
    stop_count: int = 0
    sweep_hwm: float = 0.0

    def __post_init__(self):
        # A state created with only the stop HWM starts with no unswept gain.
        if self.sweep_hwm == 0.0:
            self.sweep_hwm = self.hwm

    def record_sweep(self, amount: float) -> None:
        """Record the cash actually moved into the reserve."""
        amount = float(amount)
        if amount <= 0.0:
            return
        self.reserve += amount
        self.swept_total += amount

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'GuardState':
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass(frozen=True)
class GuardDecision:
    """Execution intents. The caller owns fills, costs, and persistence."""

    sweep_amount: float = 0.0
    liquidate: bool = False
    allow_buys: bool = True
    paused: bool = False
    reason: str = ''


def step(state: GuardState, cfg: GuardConfig, *, equity: float,
         session: str, allow_sweep: bool = True,
         allow_stop: bool = True) -> tuple[GuardState, GuardDecision]:
    """Advance the guard by one session mark.

    ``equity`` must be TOTAL equity (active book + reserve). ``allow_sweep``
    lets the caller sweep only on chosen sessions (e.g. weekly rebalances).
    ``allow_stop`` lets the caller defer the HWM stop check to chosen sessions
    (e.g. weekly close) while the HWM still tracks every daily mark. The
    function mutates and returns ``state``; callers should persist it after
    applying the decision.
    """
    if state.last_session == session:
        paused = state.pause_sessions > 0
        return state, GuardDecision(
            allow_buys=not paused,
            paused=paused,
            reason='already_marked',
        )

    state.last_session = session
    equity = float(equity)

    if state.hwm <= 0.0:
        state.hwm = equity
        state.sweep_hwm = equity

    # Cooldown: block the whole session, then re-enable on the next one.
    if state.pause_sessions > 0:
        state.pause_sessions -= 1
        state.hwm = max(state.hwm, equity)
        state.last_action = 'cooldown'
        return state, GuardDecision(
            allow_buys=False,
            paused=True,
            reason='cooldown',
        )

    # Path-based stop is checked before a new-high sweep.
    if (allow_stop and cfg.hwm_stop_pct > 0.0
            and equity <= state.hwm * (1.0 - cfg.hwm_stop_pct)):
        # reset_hwm_on_stop=True starts the next cycle from the stopped-out
        # level. False keeps the old peak, so after the cooldown the guard
        # keeps re-stopping (staying in cash) until equity recovers above the
        # original stop line.
        if cfg.reset_hwm_on_stop:
            state.hwm = equity
            state.sweep_hwm = equity
        state.pause_sessions = cfg.cooldown_sessions
        state.stop_count += 1
        state.last_action = 'hwm_stop'
        return state, GuardDecision(
            liquidate=True,
            allow_buys=False,
            paused=True,
            reason='hwm_stop',
        )

    state.hwm = max(state.hwm, equity)

    if allow_sweep and cfg.sweep_pct > 0.0 and equity > state.sweep_hwm:
        sweep = (equity - state.sweep_hwm) * cfg.sweep_pct
        if sweep > 0.0 and sweep >= cfg.min_sweep:
            state.sweep_hwm = equity
            state.last_action = 'sweep'
            return state, GuardDecision(
                sweep_amount=sweep,
                allow_buys=True,
                reason='sweep',
            )

    state.last_action = 'normal'
    return state, GuardDecision(allow_buys=True, reason='normal')
