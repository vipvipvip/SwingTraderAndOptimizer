"""CMO daily signal — the single source for BOTH live and backtest.

Owner's rule (2026-11-16), daily settled bars only:

    Buy  1. CMO(20) crosses above 0
         2. MACD Diff > 0            (Val - Avg; 10/20/40, Weighted)
         3. EMA10 > SMA20
         4. EMA10 crosses above the Bollinger(20) mid band (EMA20)
         conditions 1-4 all met within the last 10 trading bars

    Sell = the reverse of buy.

Two conditions are EVENTS (a cross happened); two are STATES (true on the decision
bar). The default `armed` reading requires the states today and the events inside
the 10-bar window. `any_in_window` and `same_bar` exist only for the sensitivity
run; do not silently change the default.

`chain` (owner's 2026-11-17 revision) counts each of the four conditions the
first time it prints, in any order, and buys on the bar the fourth one lands —
but each print expires after `window` bars (owner's trial: 30 daily bars). The
counters reset after that pulse, so the next buy needs a fresh print of all
four. Mirror sell uses the same chain on the four bearish conditions.
`window <= 0` disables expiry (legacy no-window chain).

The book is a per-name state machine (Mode A), NOT a rank rotation: a held name
leaves only when its own mirror sell window fires. See common/docs/CMO_STRATEGY.md.

Pure module: no DB, no I/O, no config side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

CMO_PERIOD = 20
MACD_FAST = 10
MACD_SLOW = 20
MACD_SIGNAL = 40
EMA_FAST = 10
SMA_MID = 20
BB_PERIOD = 20
BB_STD = 2.0
WINDOW = 10
WARMUP_BARS = 80

_MA_TYPES = ('wma', 'ema')
_WINDOW_MODES = ('armed', 'any_in_window', 'same_bar', 'chain', 'cmo_bb')
_SELL_MODES = ('mirror', 'any')

_NO_DAYS = 10 ** 6


# ───────────────────────────── moving averages ──────────────────────────────

def wma(values: Sequence[float], period: int) -> np.ndarray:
    """Linear-weighted moving average (TOS "Weighted").

    The newest bar gets weight `period`, the oldest weight 1:
    out[i] = sum(v[i-period+1+j] * (j+1), j=0..period-1) / (period*(period+1)/2).

    Leading values (and windows containing a non-finite input) are NaN.
    """
    v = np.asarray(values, dtype=np.float64)
    out = np.full(v.shape, np.nan, dtype=np.float64)
    if period <= 0 or len(v) < period:
        return out
    weights = np.arange(1, period + 1, dtype=np.float64)
    # np.correlate(v, weights, 'valid')[k] = sum(v[k+j]*weights[j]) — oldest gets
    # weight 1, newest weight `period`, which is exactly the WMA definition.
    # (np.convolve flips the kernel, so it would weight the oldest bar most.)
    out[period - 1:] = np.correlate(v, weights, mode='valid') / weights.sum()
    return out


def ema(values: Sequence[float], period: int) -> np.ndarray:
    """Recursive EMA, adjust=False, seeded at the first finite value.

    Matches db.ema / pandas .ewm(span=period, adjust=False). Leading
    non-finite values stay NaN until the first finite input.
    """
    v = np.asarray(values, dtype=np.float64)
    out = np.full(v.shape, np.nan, dtype=np.float64)
    if period <= 0 or len(v) == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    prev: Optional[float] = None
    for i, x in enumerate(v):
        if not np.isfinite(x):
            if prev is not None:
                out[i] = prev
            continue
        prev = float(x) if prev is None else alpha * float(x) + (1.0 - alpha) * prev
        out[i] = prev
    return out


def sma(values: Sequence[float], period: int) -> np.ndarray:
    """Simple moving average; leading values NaN."""
    v = np.asarray(values, dtype=np.float64)
    out = np.full(v.shape, np.nan, dtype=np.float64)
    if period <= 0 or len(v) < period:
        return out
    c = np.cumsum(np.insert(v, 0, 0.0))
    out[period - 1:] = (c[period:] - c[:-period]) / float(period)
    return out


def _ma(values: Sequence[float], period: int, ma_type: str) -> np.ndarray:
    if ma_type == 'wma':
        return wma(values, period)
    if ma_type == 'ema':
        return ema(values, period)
    raise ValueError(f'ma_type must be one of {_MA_TYPES}, got {ma_type!r}')


# ─────────────────────────────── indicators ─────────────────────────────────

def cmo(closes: Sequence[float], period: int = CMO_PERIOD) -> np.ndarray:
    """Chande Momentum Oscillator on close-to-close changes.

    CMO[i] = 100 * (SU - SD) / (SU + SD), where SU/SD are the sums of the
    positive/negative changes over the `period` changes ending at i.
    A flat window (SU+SD == 0) is 0. Needs `period + 1` closes.
    """
    c = np.asarray(closes, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan, dtype=np.float64)
    if period <= 0 or n < period + 1:
        return out
    d = np.diff(c)                       # d[k] = c[k+1] - c[k]; length n-1
    up = np.where(d > 0, d, 0.0)
    down = np.where(d < 0, -d, 0.0)
    cu = np.concatenate(([0.0], np.cumsum(up)))     # length n
    cd = np.concatenate(([0.0], np.cumsum(down)))   # length n
    for i in range(period, n):
        su = cu[i] - cu[i - period]
        sd = cd[i] - cd[i - period]
        denom = su + sd
        out[i] = 0.0 if denom == 0 else 100.0 * (su - sd) / denom
    return out


def macd(closes: Sequence[float], fast: int = MACD_FAST, slow: int = MACD_SLOW,
         signal: int = MACD_SIGNAL, ma_type: str = 'wma'):
    """MACD with the owner's chart settings: Val, Avg, Diff = Val - Avg.

    Val = MA(close, fast) - MA(close, slow); Avg = MA(Val, signal).
    `ma_type='wma'` is the live chart ("Weighted"); 'ema' is the sensitivity run.
    """
    c = np.asarray(closes, dtype=np.float64)
    val = _ma(c, fast, ma_type) - _ma(c, slow, ma_type)
    avg = _ma(val, signal, ma_type)
    diff = val - avg
    return val, avg, diff


def bollinger(closes: Sequence[float], period: int = BB_PERIOD,
              num_std: float = BB_STD, mid_type: str = 'ema'):
    """Bollinger bands. The mid band is EMA(period) (owner's chart); the 2-sigma
    bands are returned for reporting only and are not read by the signal."""
    c = np.asarray(closes, dtype=np.float64)
    mid = ema(c, period) if mid_type == 'ema' else sma(c, period)
    if len(c) < period:
        nan = np.full(c.shape, np.nan, dtype=np.float64)
        return mid, nan, nan
    # population stdev (ddof=0), the platform-standard Bollinger definition
    sd = np.full(c.shape, np.nan, dtype=np.float64)
    for i in range(period - 1, len(c)):
        seg = c[i - period + 1:i + 1]
        if np.isfinite(seg).all():
            sd[i] = float(np.std(seg))
    return mid, mid + num_std * sd, mid - num_std * sd


def indicators(daily: dict, ma_type: str = 'wma', bb_mid_type: str = 'ema') -> dict:
    """Compute every daily array the signal needs, aligned to daily['dates'].

    `daily` must carry 'close' (list/array); 'dates' is passed through.
    """
    close = np.asarray(daily['close'], dtype=np.float64)
    ema10 = ema(close, EMA_FAST)
    sma20 = sma(close, SMA_MID)
    bb_mid, bb_up, bb_lo = bollinger(close, BB_PERIOD, BB_STD, mid_type=bb_mid_type)
    cmo20 = cmo(close, CMO_PERIOD)
    macd_val, macd_avg, macd_diff = macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL, ma_type)
    return {
        'dates': daily.get('dates'),
        'close': close,
        'cmo': cmo20,
        'macd_val': macd_val,
        'macd_avg': macd_avg,
        'macd_diff': macd_diff,
        'ema10': ema10,
        'sma20': sma20,
        'bb_mid': bb_mid,
        'bb_upper': bb_up,
        'bb_lower': bb_lo,
    }


# ──────────────────────────── signal state machine ──────────────────────────

def _cross_up_event(fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    fast = np.asarray(fast, dtype=np.float64)
    slow = np.asarray(slow, dtype=np.float64)
    out = np.zeros(len(fast), dtype=bool)
    if len(fast) < 2:
        return out
    ok = np.isfinite(fast[1:]) & np.isfinite(slow[1:]) & np.isfinite(fast[:-1]) & np.isfinite(slow[:-1])
    out[1:] = ok & (fast[1:] > slow[1:]) & (fast[:-1] <= slow[:-1])
    return out


def _cross_down_event(fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    return _cross_up_event(-np.asarray(fast, dtype=np.float64),
                           -np.asarray(slow, dtype=np.float64))


def _cross_above_zero_event(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.zeros(len(x), dtype=bool)
    if len(x) < 2:
        return out
    ok = np.isfinite(x[1:]) & np.isfinite(x[:-1])
    out[1:] = ok & (x[1:] > 0) & (x[:-1] <= 0)
    return out


def _cross_below_zero_event(x: np.ndarray) -> np.ndarray:
    return _cross_above_zero_event(-np.asarray(x, dtype=np.float64))


def _last_event_index(events: np.ndarray) -> np.ndarray:
    """out[i] = index of the most recent True at/before i, or -1."""
    out = np.full(len(events), -1, dtype=np.int64)
    last = -1
    for i, hit in enumerate(events):
        if hit:
            last = i
        out[i] = last
    return out


def _within(last: np.ndarray, window: int) -> np.ndarray:
    """True where the last event is inside [i-window+1, i]."""
    idx = np.arange(len(last))
    return (last >= 0) & ((idx - last) < window)


def _rolling_any(mask: np.ndarray, window: int) -> np.ndarray:
    """True where mask is True on at least one bar in [i-window+1, i]."""
    m = np.asarray(mask, dtype=bool)
    cs = np.concatenate(([0], np.cumsum(m.astype(np.int64))))
    idx = np.arange(len(m))
    lo = np.maximum(0, idx - window + 1)
    return (cs[idx + 1] - cs[lo]) > 0


def _once_all(conds, valid: np.ndarray, window: int = 0) -> np.ndarray:
    """One-shot pulse when every condition has printed within `window` bars.

    Any order. A print older than `window` bars expires; `window <= 0` means
    never expires. Counting starts on valid bars only. The seen-set is cleared
    right after a pulse, so a later pulse needs a fresh print of every condition.
    """
    n = len(valid)
    out = np.zeros(n, dtype=bool)
    k = len(conds)
    seen = [False] * k
    last = [-10 ** 9] * k
    for i in range(n):
        if not valid[i]:
            continue
        for j, cond in enumerate(conds):
            if cond[i]:
                seen[j] = True
                last[j] = i
            elif window > 0 and i - last[j] >= window:
                seen[j] = False
        if all(seen):
            out[i] = True
            seen = [False] * k
            last = [i] * k
    return out


def build_signal_arrays(ind: dict, window: int = WINDOW, mode: str = 'armed',
                        sell_mode: str = 'mirror') -> dict:
    """Precompute buy/sell arrays for one ticker. Live and backtest both use this.

    Returns a dict of arrays aligned to `ind`:
      buy, sell, valid,
      last_cmo_up, last_bb_up, last_cmo_down, last_bb_down (event indices, -1 none),
      plus pass-through indicator arrays (cmo, macd_diff, ema10, bb_mid, sma20,
      macd_val, macd_avg, close) for reporting.
    """
    if mode not in _WINDOW_MODES:
        raise ValueError(f'mode must be one of {_WINDOW_MODES}, got {mode!r}')
    if sell_mode not in _SELL_MODES:
        raise ValueError(f'sell_mode must be one of {_SELL_MODES}, got {sell_mode!r}')

    close = np.asarray(ind['close'], dtype=np.float64)
    cmo = np.asarray(ind['cmo'], dtype=np.float64)
    ema10 = np.asarray(ind['ema10'], dtype=np.float64)
    bb_mid = np.asarray(ind['bb_mid'], dtype=np.float64)
    sma20 = np.asarray(ind['sma20'], dtype=np.float64)
    macd_diff = np.asarray(ind['macd_diff'], dtype=np.float64)
    n = len(close)

    cmo_up = _cross_above_zero_event(cmo)
    cmo_down = _cross_below_zero_event(cmo)
    bb_up = _cross_up_event(ema10, bb_mid)
    bb_down = _cross_down_event(ema10, bb_mid)

    last_cmo_up = _last_event_index(cmo_up)
    last_bb_up = _last_event_index(bb_up)
    last_cmo_down = _last_event_index(cmo_down)
    last_bb_down = _last_event_index(bb_down)

    valid = (np.isfinite(close) & np.isfinite(cmo) & np.isfinite(ema10)
             & np.isfinite(bb_mid) & np.isfinite(sma20) & np.isfinite(macd_diff))
    valid &= np.arange(n) >= (WARMUP_BARS - 1)

    macd_bull = np.isfinite(macd_diff) & (macd_diff > 0)
    macd_bear = np.isfinite(macd_diff) & (macd_diff < 0)
    ema_bull = np.isfinite(ema10) & np.isfinite(sma20) & (ema10 > sma20)
    ema_bear = np.isfinite(ema10) & np.isfinite(sma20) & (ema10 < sma20)

    if mode == 'cmo_bb':
        buy_raw = valid & cmo_up & (ema10 > bb_mid)
        sell_all = valid & cmo_down & (ema10 < bb_mid)
    elif mode == 'chain':
        buy_raw = _once_all([cmo_up, macd_bull, ema_bull, bb_up], valid, window)
        if sell_mode == 'any':
            sell_all = valid & (cmo_down | bb_down | macd_bear | ema_bear)
        else:
            sell_all = _once_all([cmo_down, macd_bear, ema_bear, bb_down], valid,
                                 window)
    elif mode == 'same_bar':
        buy_raw = macd_bull & ema_bull & cmo_up & bb_up
        sell_all = macd_bear & ema_bear & cmo_down & bb_down
    elif mode == 'any_in_window':
        buy_raw = (valid & _rolling_any(cmo_up, window) & _rolling_any(bb_up, window)
                   & _rolling_any(macd_bull, window) & _rolling_any(ema_bull, window))
        sell_all = (valid & _rolling_any(cmo_down, window) & _rolling_any(bb_down, window)
                    & _rolling_any(macd_bear, window) & _rolling_any(ema_bear, window))
    else:  # 'armed' (default): states today, fresh events in the window
        buy_raw = (valid & macd_bull & ema_bull
                   & _within(last_cmo_up, window) & _within(last_bb_up, window))
        sell_all = (valid & macd_bear & ema_bear
                    & _within(last_cmo_down, window) & _within(last_bb_down, window))

    if mode not in ('same_bar', 'chain', 'cmo_bb') and sell_mode == 'any':
        # Sensitivity only: any one bearish condition in the window is an exit.
        sell_all = (valid & (_rolling_any(cmo_down, window) | _rolling_any(bb_down, window)
                             | _rolling_any(macd_bear, window) | _rolling_any(ema_bear, window)))

    return {
        'buy': buy_raw,
        'sell': sell_all,
        'valid': valid,
        'last_cmo_up': last_cmo_up,
        'last_bb_up': last_bb_up,
        'last_cmo_down': last_cmo_down,
        'last_bb_down': last_bb_down,
        'close': close,
        'cmo': cmo,
        'macd_val': np.asarray(ind['macd_val'], dtype=np.float64),
        'macd_avg': np.asarray(ind['macd_avg'], dtype=np.float64),
        'macd_diff': macd_diff,
        'ema10': ema10,
        'bb_mid': bb_mid,
        'sma20': sma20,
    }


@dataclass(frozen=True)
class Signal:
    buy: bool
    sell: bool
    valid: bool
    cmo: float
    macd_val: float
    macd_avg: float
    macd_diff: float
    ema10: float
    bb_mid: float
    sma20: float
    days_cmo_up: int      # -1 when no up-cross in the data
    days_bb_up: int
    days_cmo_down: int
    days_bb_down: int


def _days_since(last: np.ndarray, i: int) -> int:
    j = int(last[i])
    return -1 if j < 0 else i - j


def signal_at(arr: dict, i: int) -> Signal:
    """Read the precomputed signal at bar index i."""
    def f(key):
        return float(arr[key][i])

    return Signal(
        buy=bool(arr['buy'][i]),
        sell=bool(arr['sell'][i]),
        valid=bool(arr['valid'][i]),
        cmo=f('cmo'),
        macd_val=f('macd_val'),
        macd_avg=f('macd_avg'),
        macd_diff=f('macd_diff'),
        ema10=f('ema10'),
        bb_mid=f('bb_mid'),
        sma20=f('sma20'),
        days_cmo_up=_days_since(arr['last_cmo_up'], i),
        days_bb_up=_days_since(arr['last_bb_up'], i),
        days_cmo_down=_days_since(arr['last_cmo_down'], i),
        days_bb_down=_days_since(arr['last_bb_down'], i),
    )


def signal_for_ticker(daily: dict, i: int, window: int = WINDOW,
                      mode: str = 'armed', sell_mode: str = 'mirror',
                      ma_type: str = 'wma') -> Signal:
    """Convenience for live: compute indicators + arrays for one ticker, read bar i."""
    return signal_at(build_signal_arrays(indicators(daily, ma_type=ma_type),
                                         window=window, mode=mode,
                                         sell_mode=sell_mode), i)


# ──────────────────────────────── book builder ──────────────────────────────

def rank_key(symbol: str, sig: Signal):
    """Deterministic new-entry rank: freshest CMO up-cross, then Diff, EMA gap, symbol."""
    days = sig.days_cmo_up if sig.days_cmo_up >= 0 else _NO_DAYS
    gap = sig.ema10 - sig.bb_mid
    if not np.isfinite(gap):
        gap = -np.inf
    diff = sig.macd_diff if np.isfinite(sig.macd_diff) else -np.inf
    return (days, -diff, -gap, symbol)


def build_book(held: Iterable[str], states: Dict[str, Signal], top_n: int) -> dict:
    """Mode A stateful book.

    held:   symbols currently in the account (mtf_positions / Alpaca).
    states: symbol -> Signal on the same settled bar (only scored names).
    Returns {target, sells, new, missing, held_alive}.
      - a held name is sold only when its mirror sell fires;
      - a held name with no state is preserved (missing data, never a blind sell);
      - free slots are filled by armed names, ranked by rank_key.
    """
    held = list(dict.fromkeys(held))
    held_alive: List[str] = []
    sells: List[str] = []
    missing: List[str] = []
    for sym in held:
        sig = states.get(sym)
        if sig is None:
            missing.append(sym)
            held_alive.append(sym)
        elif sig.sell:
            sells.append(sym)
        else:
            held_alive.append(sym)

    slots = max(0, int(top_n) - len(held_alive))
    blockers = set(held_alive) | set(sells)
    candidates = [(s, st) for s, st in states.items()
                  if st.buy and s not in blockers]
    candidates.sort(key=lambda item: rank_key(item[0], item[1]))
    new = [s for s, _ in candidates[:slots]]

    return {
        'target': held_alive + new,
        'sells': sells,
        'new': new,
        'missing': missing,
        'held_alive': held_alive,
        'candidate_count': len(candidates),
    }
