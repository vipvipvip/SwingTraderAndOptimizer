"""Unit tests for the 2026-11-02 MTF stock-leg risk fixes.

Covers the pure helpers only (no DB / no Alpaca):
  * multi-day ratchet cool-off cutoff
  * size-by-TOP_N + preserved-holdings gross cap
  * rebalance band + minimum trade notional
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import executor


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return FakeCursor(self._rows)


class CooldownCutoffTest(unittest.TestCase):
    def test_zero_days_is_same_day_only(self):
        today = date(2026, 11, 2)
        self.assertEqual(db.ratchet_cooldown_cutoff(FakeConn([]), 0, today), today)

    def test_five_days_returns_fifth_prior_session(self):
        today = date(2026, 11, 2)
        rows = [(date(2026, 10, 30),), (date(2026, 10, 29),), (date(2026, 10, 28),),
                (date(2026, 10, 27),), (date(2026, 10, 26),)]
        self.assertEqual(db.ratchet_cooldown_cutoff(FakeConn(rows), 5, today),
                         date(2026, 10, 26))

    def test_short_history_uses_oldest_available(self):
        today = date(2026, 11, 2)
        rows = [(date(2026, 10, 30),), (date(2026, 10, 29),)]
        self.assertEqual(db.ratchet_cooldown_cutoff(FakeConn(rows), 5, today),
                         date(2026, 10, 29))

    def test_no_calendar_falls_back_to_today(self):
        today = date(2026, 11, 2)
        self.assertEqual(db.ratchet_cooldown_cutoff(FakeConn([]), 5, today), today)


class PerPositionTest(unittest.TestCase):
    def test_legacy_sizing_divides_by_book_size(self):
        self.assertEqual(
            executor._risk_per_position(100_000, 100_000, 3, 25, False), 100_000 / 3)

    def test_size_by_top_n_caps_thin_book(self):
        # 3 picks on a $100K account used to be $33K each; now capped at $4K.
        self.assertEqual(
            executor._risk_per_position(100_000, 100_000, 3, 25, True), 4_000)

    def test_preserved_holdings_are_subtracted(self):
        # $100K equity, $15K parked in preserved names -> $85K investable.
        self.assertEqual(
            executor._risk_per_position(100_000, 85_000, 25, 25, True), 3_400)

    def test_full_book_gets_one_top_n_slot(self):
        self.assertEqual(
            executor._risk_per_position(100_000, 100_000, 25, 25, True), 4_000)

    def test_zero_investable_falls_back_to_book_average(self):
        self.assertEqual(
            executor._risk_per_position(100_000, 0, 10, 25, True), 10_000)

    def test_never_negative(self):
        self.assertEqual(
            executor._risk_per_position(100_000, -5_000, 10, 25, True), 10_000)


class RebalanceBandTest(unittest.TestCase):
    def test_trim_within_band_is_skipped(self):
        # $4,000 target, $4,600 value = +15% < 20% band.
        self.assertFalse(executor._should_trim(4_600, 4_000, 20.0, 500.0))

    def test_trim_outside_band_is_allowed(self):
        # $5,000 value = +25% > 20% band and excess $1,000 > $500 min.
        self.assertTrue(executor._should_trim(5_000, 4_000, 20.0, 500.0))

    def test_trim_outside_band_but_below_min_notional_is_skipped(self):
        self.assertFalse(executor._should_trim(4_900, 4_000, 20.0, 999.0))

    def test_top_up_within_band_is_skipped(self):
        # $3,500 held vs $4,000 target = $500 (12.5%) short.
        self.assertFalse(executor._should_top_up(500, 4_000, 20.0, 500.0))

    def test_top_up_outside_band_is_allowed(self):
        self.assertTrue(executor._should_top_up(1_000, 4_000, 20.0, 500.0))

    def test_zero_band_reproduces_old_exact_equal_weight(self):
        self.assertTrue(executor._should_trim(4_001, 4_000, 0.0, 0.0))
        self.assertTrue(executor._should_top_up(1, 4_000, 0.0, 0.0))

    def test_min_notional_blocks_tiny_orders(self):
        self.assertFalse(executor._should_top_up(100, 4_000, 0.0, 500.0))
        self.assertFalse(executor._should_trim(4_100, 4_000, 0.0, 500.0))


class PositionValueTest(unittest.TestCase):
    def test_market_value(self):
        self.assertEqual(executor._position_value({'market_value': '1234.5'}), 1234.5)

    def test_qty_times_price_fallback(self):
        self.assertEqual(
            executor._position_value({'qty': '-10', 'current_price': '12.5'}), 125.0)

    def test_empty(self):
        self.assertEqual(executor._position_value(None), 0.0)


if __name__ == '__main__':
    unittest.main()
