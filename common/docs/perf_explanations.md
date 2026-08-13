# Performance Explanations

Analysis of exit-logic bugs, live performance gaps, and whether fixes applied to one
strategy should propagate to others. Written 2026-08-13.

---

## 1. CHAND: peak-anchored Chandelier — no float-down bug

### Question
MTF's old stop (`close − 2×ATR`) was close-anchored and floated down with a crash, so it
could not trigger by construction (ZBRA rode −52.7% never exiting). We replaced it with a
peak-anchored ratchet: sell when `close < (highest close since entry) − 2×ATR`. Does CHAND
suffer from the same flaw and need the same fix?

### Answer: No — CHAND was already correct
CHAND is a proper Chandelier Exit, peak-anchored on the **highest high since entry**:

```
stop = max(high since entry_at) − ATR(chandelier_period) × chandelier_mult
exit when live price < stop
```

Source: `swingtrader/backend/app/Services/TradeExecutorService.php:825-840` (see also
`parameter_optimizer.py:286-292`, the backtest engine). The peak never drops, so the stop
cannot float down with the price. This is the same fix we applied to MTF — CHAND had it
from the start (arguably better: it anchors on high, not close).

### Evidence it works
- Worst closed trade on record: **−6.1%** (QQQ, 2026-07-09 → 07-27). No ZBRA-style rides.
- Live params (base_case): QQQ 18/3.5, VTI 18/3.5, VTV 18/2.5 (period/mult) + entry filter
  (`chandelier_entry_mult` 1.5-2.0) + regression-slope exit on QQQ/VTV.

### Known nuance (not a bug)
`stop = fixed peak − trailing ATR`. During a crash ATR spikes, which sags the stop and
slightly delays exits. It self-corrects as ATR contracts and is bounded (cannot float
indefinitely since the peak is fixed). Optional tightening: clamp ATR in
`calculateATR()` — not required.

### Power-window impact (2026-08-13 decision)
Under the 3.5h/day power window (ON Mon-Fri 09:00→10:15 + 16:30→17:10 ET), CHAND only
monitors **09:30-10:15** — its intraday live-price stop check stops after 10:15 and a
stop-break isn't caught until next morning's open (once-daily-at-open). The 16:30-17:10
window gives CHAND nothing (market closes 16:00; the `is_open` gate bails). This is
**accepted**: it matches the daily-close backtest the optimizer validated, and the open
window still catches overnight/weekend gaps at the highest-liquidity moment. Minor
collateral: `equity:snapshot` (16:05) and `logs:check-and-alert` (16:10) stop firing —
both non-critical (`positions:sync` still runs in the morning window, so DB self-healing
from Alpaca continues).

When the machine IS up during market hours, the intraday 5-minute check still runs — this
strays from the backtest in the **protective** direction (can exit mid-crash before the
daily close; rare whipsaw on dip-then-recover days at 3.5× mult). One-sided and benign;
no code changes made.

**Verdict: do not apply the MTF ratchet to CHAND; accept the once-daily degradation.**

---

## 2. MTF live: ETF leg vs stock leg

### Observation
As of 2026-08-13 the ETF leg is ahead of the stock leg (both live since 2026-07-30):

| Leg | Alpaca equity | Realized | Unrealized (open) | Total |
|-----|---------------|----------|-------------------|-------|
| Stock (#PA3PPZAZR76Z) | $101,407 | +$1,790 | −$1,042 | ≈ +$748 |
| ETF (#PA3U8GZ96PEN) | $105,901 | +$1,334 | +$3,931 | ≈ +$5,264 |

Gap: **~$4,495**. `mtf_trades.pnl_dollar` is unreliable for closed positions (reconciled
against a stale `entry_price`); use FIFO round-trips or Alpaca equity. DB-derived totals run
~$600-650/account below Alpaca (pre-07-30 history / starting capital).

### Why the gap — not a strategy-hierarchy reversal
1. **One perfect rotation call (≈ $2,913)**: ETF leg bought SMH/XLK/VGT/XLE on 08-03, right
   before the early-Aug tech/semis/energy rally → unrealized +994/+793/+717/+409. Sector
   ETFs ride a rising tide directly; this single call explains most of the gap.
2. **DAVE, a pre-ratchet crash (≈ −$3,000)**: stock leg bought 24 sh @ $434.27 on 08-05,
   price crashed to ~$307 by 08-12, sold $309.01 on 08-10. This is the **live smoking gun
   of the float-down bug**: the old `close−2×ATR` stop sat at 324.72 → 263.75 → 267.65 the
   whole way down, always below price, never firing. The exit was rotation-driven, not a
   stop. The ratchet (peak 434.27 − 2×ATR ≈ 385 on 08-06) would have exited ~08-06/08-07,
   saving roughly **$1,800**. Ratchet went live 08-12; first real execution 08-13 10:00.
3. **08-07 execution outage**: Alpaca read-timeout skipped the stock leg that day; ETF leg
   traded normally.

### Long-run backtest says the opposite
Over Jul 2023 → Jul 2026: stock rotation **+11,643%** (ratchet exit, 20.8% DD) vs sector-ETF
rotation **+46.9%** (which underperforms equal-weight B&H +127.9%). The 12-trading-day ETF
lead is regime luck + one fixable loss, not evidence that ETFs are structurally superior.

### Verdict
Keep both legs as-is; do not reallocate toward ETFs off a 2-week sample. The ratchet is
exactly the fix DAVE needed. If the ETF leg is still ahead after a full cycle (not just a
rally), revisit a blended allocation to reduce volatility.

---

## References
- Ratchet-ATR exit design + backtest: `AGENTS.md` → Key Decisions (2026-08-12)
- MTF executor: `swingtrader/services/mtf/executor.py` (`_compute_ratchet_stops`), config in `config.py`
- CHAND executor: `swingtrader/backend/app/Services/TradeExecutorService.php`
- MTF backtest engine: `swingtrader/services/mtf/backtest_topn_multitf.py`
