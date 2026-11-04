"""Unit tests for the pure HWM-stop / profit-sweep guard (no DB / no Alpaca)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_guard import GuardConfig, GuardState, step


class SweepTest(unittest.TestCase):
    def test_new_high_sweeps_configured_share(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(sweep_pct=0.50)
        state, d = step(state, cfg, equity=110_000.0, session='2026-01-02')
        self.assertEqual(d.sweep_amount, 5_000.0)
        self.assertEqual(state.reserve, 0.0)  # caller records the fill
        state.record_sweep(d.sweep_amount)
        self.assertEqual(state.reserve, 5_000.0)
        self.assertEqual(state.swept_total, 5_000.0)
        self.assertEqual(state.hwm, 110_000.0)
        self.assertTrue(d.allow_buys)
        self.assertEqual(d.reason, 'sweep')

    def test_no_sweep_below_hwm(self):
        state = GuardState(hwm=110_000.0, reserve=5_000.0)
        cfg = GuardConfig(sweep_pct=0.50)
        state, d = step(state, cfg, equity=108_000.0, session='2026-01-05')
        self.assertEqual(d.sweep_amount, 0.0)
        self.assertEqual(state.reserve, 5_000.0)
        self.assertTrue(d.allow_buys)

    def test_sweep_zero_disables_sweep(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(sweep_pct=0.0)
        state, d = step(state, cfg, equity=110_000.0, session='2026-01-02')
        self.assertEqual(d.sweep_amount, 0.0)
        self.assertEqual(state.reserve, 0.0)
        self.assertEqual(state.hwm, 110_000.0)

    def test_min_sweep_skips_small_gain_but_advances_hwm(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(sweep_pct=0.50, min_sweep=1_000.0)
        state, d = step(state, cfg, equity=101_000.0, session='2026-01-02')
        self.assertEqual(d.sweep_amount, 0.0)
        self.assertEqual(state.hwm, 101_000.0)

    def test_sweep_compounds_only_on_new_highs(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(sweep_pct=0.50)
        state, d = step(state, cfg, equity=110_000.0, session='2026-01-02')
        state.record_sweep(d.sweep_amount)
        state, _ = step(state, cfg, equity=110_000.0, session='2026-01-05')
        state, d = step(state, cfg, equity=115_000.0, session='2026-01-06')
        self.assertEqual(d.sweep_amount, 2_500.0)
        state.record_sweep(d.sweep_amount)
        self.assertEqual(state.reserve, 7_500.0)

    def test_disallowed_sweep_accumulates_until_allowed(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(sweep_pct=0.50)
        state, d = step(state, cfg, equity=110_000.0, session='d1',
                        allow_sweep=False)
        self.assertEqual(d.sweep_amount, 0.0)
        self.assertEqual(state.hwm, 110_000.0)
        self.assertEqual(state.sweep_hwm, 100_000.0)
        state, d = step(state, cfg, equity=112_000.0, session='d2',
                        allow_sweep=True)
        self.assertEqual(d.sweep_amount, 6_000.0)
        state.record_sweep(d.sweep_amount)
        self.assertEqual(state.reserve, 6_000.0)
        self.assertEqual(state.sweep_hwm, 112_000.0)


class StopTest(unittest.TestCase):
    def test_stop_liquidates_and_pauses(self):
        state = GuardState(hwm=110_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.06, cooldown_sessions=5)
        state, d = step(state, cfg, equity=103_400.0, session='2026-01-02')
        self.assertTrue(d.liquidate)
        self.assertFalse(d.allow_buys)
        self.assertTrue(d.paused)
        self.assertEqual(state.pause_sessions, 5)
        self.assertEqual(state.stop_count, 1)

    def test_stop_does_not_trigger_inside_threshold(self):
        state = GuardState(hwm=110_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.06)
        state, d = step(state, cfg, equity=103_500.0, session='2026-01-02')
        self.assertFalse(d.liquidate)
        self.assertTrue(d.allow_buys)

    def test_stop_resets_sweep_high(self):
        state = GuardState(hwm=110_000.0, sweep_hwm=105_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.06)
        state, d = step(state, cfg, equity=103_000.0, session='2026-01-02')
        self.assertTrue(d.liquidate)
        self.assertEqual(state.hwm, 103_000.0)
        self.assertEqual(state.sweep_hwm, 103_000.0)

    def test_hold_peak_stays_out_below_stop_line(self):
        state = GuardState(hwm=110_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.06, cooldown_sessions=1,
                          reset_hwm_on_stop=False)
        state, d = step(state, cfg, equity=103_000.0, session='d1')
        self.assertTrue(d.liquidate)
        self.assertEqual(state.hwm, 110_000.0)
        state, d = step(state, cfg, equity=103_000.0, session='d2')
        self.assertTrue(d.paused)
        self.assertFalse(d.allow_buys)
        state, d = step(state, cfg, equity=103_300.0, session='d3')
        self.assertTrue(d.liquidate)  # still below 110k * 0.94
        state, d = step(state, cfg, equity=103_500.0, session='d4')
        self.assertTrue(d.paused)     # cooldown, then recovery
        state, d = step(state, cfg, equity=103_500.0, session='d5')
        self.assertFalse(d.paused)
        self.assertTrue(d.allow_buys)

    def test_deferred_stop_updates_hwm_without_liquidating(self):
        state = GuardState(hwm=110_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.06)
        state, d = step(state, cfg, equity=103_000.0, session='d1',
                        allow_stop=False)
        self.assertFalse(d.liquidate)
        self.assertTrue(d.allow_buys)
        self.assertEqual(state.hwm, 110_000.0)
        state, d = step(state, cfg, equity=103_000.0, session='d2',
                        allow_stop=False)
        self.assertFalse(d.liquidate)
        state, d = step(state, cfg, equity=103_000.0, session='d3',
                        allow_stop=True)
        self.assertTrue(d.liquidate)

    def test_stop_zero_is_disabled(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.0)
        state, d = step(state, cfg, equity=50_000.0, session='2026-01-02')
        self.assertFalse(d.liquidate)

    def test_cooldown_blocks_then_releases(self):
        state = GuardState(hwm=110_000.0)
        cfg = GuardConfig(hwm_stop_pct=0.06, cooldown_sessions=2)
        state, d = step(state, cfg, equity=103_000.0, session='d1')
        self.assertTrue(d.liquidate)
        state, d = step(state, cfg, equity=103_000.0, session='d2')
        self.assertTrue(d.paused)
        self.assertFalse(d.allow_buys)
        state, d = step(state, cfg, equity=103_000.0, session='d3')
        self.assertTrue(d.paused)
        self.assertFalse(d.allow_buys)
        state, d = step(state, cfg, equity=103_000.0, session='d4')
        self.assertFalse(d.paused)
        self.assertTrue(d.allow_buys)

    def test_idempotent_same_session(self):
        state = GuardState(hwm=100_000.0)
        cfg = GuardConfig(sweep_pct=0.50)
        state, d1 = step(state, cfg, equity=110_000.0, session='2026-01-02')
        state.record_sweep(d1.sweep_amount)
        state, d2 = step(state, cfg, equity=110_000.0, session='2026-01-02')
        self.assertEqual(d1.sweep_amount, 5_000.0)
        self.assertEqual(d2.sweep_amount, 0.0)
        self.assertEqual(state.reserve, 5_000.0)
        self.assertEqual(d2.reason, 'already_marked')


class StateTest(unittest.TestCase):
    def test_record_sweep_ignores_nonpositive(self):
        state = GuardState(hwm=100_000.0)
        state.record_sweep(0.0)
        state.record_sweep(-1.0)
        self.assertEqual(state.reserve, 0.0)
        self.assertEqual(state.swept_total, 0.0)

    def test_round_trip(self):
        state = GuardState(hwm=110_000.0, reserve=5_000.0, pause_sessions=2,
                           last_session='2026-01-02', last_action='sweep',
                           swept_total=5_000.0, stop_count=1)
        self.assertEqual(GuardState.from_dict(state.to_dict()), state)

    def test_from_dict_ignores_unknown_fields(self):
        state = GuardState.from_dict({'hwm': 100_000.0, 'reserve': 0.0, 'bogus': 1})
        self.assertEqual(state.hwm, 100_000.0)

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            GuardConfig(hwm_stop_pct=1.0)
        with self.assertRaises(ValueError):
            GuardConfig(sweep_pct=-0.1)
        with self.assertRaises(ValueError):
            GuardConfig(cooldown_sessions=-1)


if __name__ == '__main__':
    unittest.main()
