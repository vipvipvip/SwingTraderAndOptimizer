"""Unit tests for the CoreEW P20w market-gate helpers (no DB / no PHP)."""

import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_trio_ew
import coreew_gate
import executor
import runner


def _payload(qqq, vti, vtv, week='2026-10-26'):
    return {
        'symbols': ['QQQ', 'VTI', 'VTV'],
        'series': {
            'QQQ': [{'week': week, 'close': 1.0, 'ema': 0.9, 'long': qqq}],
            'VTI': [{'week': week, 'close': 1.0, 'ema': 0.9, 'long': vti}],
            'VTV': [{'week': week, 'close': 1.0, 'ema': 0.9, 'long': vtv}],
        },
    }


class TestParsePayload(unittest.TestCase):
    def test_returns_last_state_and_week(self):
        states, week = coreew_gate.parse_payload(_payload(True, False, True))
        self.assertEqual(states, {'QQQ': True, 'VTI': False, 'VTV': True})
        self.assertEqual(week, '2026-10-26')

    def test_error_payload_raises(self):
        with self.assertRaises(RuntimeError):
            coreew_gate.parse_payload({'error': 'no data', 'series': None})

    def test_missing_symbol_raises(self):
        p = _payload(True, True, True)
        del p['series']['VTV']
        with self.assertRaises(RuntimeError):
            coreew_gate.parse_payload(p)

    def test_mismatched_weeks_raise(self):
        p = _payload(True, True, True)
        p['series']['VTV'][0]['week'] = '2026-11-02'
        with self.assertRaises(RuntimeError):
            coreew_gate.parse_payload(p)


class TestGateOff(unittest.TestCase):
    def test_any_is_off_only_when_all_legs_off(self):
        self.assertTrue(coreew_gate.gate_off({'QQQ': False, 'VTI': False, 'VTV': False}, 'any'))
        self.assertFalse(coreew_gate.gate_off({'QQQ': True, 'VTI': False, 'VTV': False}, 'any'))
        self.assertFalse(coreew_gate.gate_off({'QQQ': True, 'VTI': True, 'VTV': True}, 'any'))

    def test_majority_needs_two(self):
        self.assertTrue(coreew_gate.gate_off({'QQQ': True, 'VTI': False, 'VTV': False}, 'majority'))
        self.assertFalse(coreew_gate.gate_off({'QQQ': True, 'VTI': True, 'VTV': False}, 'majority'))

    def test_all_needs_three(self):
        self.assertTrue(coreew_gate.gate_off({'QQQ': True, 'VTI': True, 'VTV': False}, 'all'))
        self.assertFalse(coreew_gate.gate_off({'QQQ': True, 'VTI': True, 'VTV': True}, 'all'))

    def test_qqq_uses_only_qqq(self):
        self.assertTrue(coreew_gate.gate_off({'QQQ': False, 'VTI': True, 'VTV': True}, 'qqq'))
        self.assertFalse(coreew_gate.gate_off({'QQQ': True, 'VTI': False, 'VTV': False}, 'qqq'))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            coreew_gate.gate_off({'QQQ': True, 'VTI': True, 'VTV': True}, 'nope')


class TestDescribe(unittest.TestCase):
    def test_cash_and_invested_labels(self):
        off = coreew_gate.describe({'QQQ': False, 'VTI': False, 'VTV': False}, 'any', 20,
                                   '2026-10-26')
        self.assertIn('CASH', off)
        self.assertIn('0/3', off)
        on = coreew_gate.describe({'QQQ': True, 'VTI': False, 'VTV': False}, 'any', 20,
                                  '2026-10-26')
        self.assertIn('INVESTED', on)
        self.assertIn('1/3', on)


class TestStagedWeights(unittest.TestCase):
    def test_weights_align_to_settled_weeks(self):
        payload = {
            'symbols': ['QQQ'],
            'series': {
                'QQQ': [
                    {'week': '2026-11-09', 'weight': 0.5},
                    {'week': '2026-11-16', 'weight': 1.0},
                ],
            },
        }
        days = [date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 23)]
        flags, weights = backtest_trio_ew.weights_from_live_leg_ema_staged_series(days, payload)
        self.assertEqual(list(weights['QQQ']), [0.0, 0.5, 1.0])
        self.assertEqual(list(flags['QQQ']), [False, True, True])


class TestAsOfFlags(unittest.TestCase):
    def test_daily_flags_use_exact_settled_date(self):
        payload = {
            'span': 20,
            'symbols': ['QQQ'],
            'series': {
                'QQQ': [
                    {'date': '2026-11-20', 'long': False},
                    {'date': '2026-11-23', 'long': True},
                ],
            },
        }
        days = [date(2026, 11, 20), date(2026, 11, 23)]
        flags = backtest_trio_ew.flags_from_live_leg_ema_asof_series(days, payload)
        self.assertEqual(list(flags['QQQ']), [False, True])

    def test_missing_settled_date_raises(self):
        payload = {
            'span': 20,
            'symbols': ['QQQ'],
            'series': {'QQQ': [{'date': '2026-11-20', 'long': False}]},
        }
        with self.assertRaises(SystemExit):
            backtest_trio_ew.flags_from_live_leg_ema_asof_series(
                [date(2026, 11, 23)], payload)


class _FakeConn:
    def close(self):
        pass


class TestRunnerGate(unittest.TestCase):
    def test_gate_off_liquidates_without_pending(self):
        with patch.object(runner, '_get_db_conn', return_value=_FakeConn()), \
             patch.object(runner, '_market_gate_state',
                          return_value=(True, 'P20w any: CASH')), \
             patch.object(runner.db_module, 'get_pending', return_value=None), \
             patch.object(runner.executor, 'execute_rotation',
                          return_value=['  sold all']) as ex:
            ok, lines, sd = runner._run_execute_pending(
                'stock', date(2026, 11, 3), dry_run=True)
        self.assertTrue(ok)
        self.assertIn('market-gate liquidation', '\n'.join(lines))
        self.assertEqual(sd, '2026-11-03')
        ex.assert_called_once_with([], {}, 'stock', dry_run=True,
                                   market_gate_off=True)


class TestExecutorGate(unittest.TestCase):
    def test_gate_off_dry_run_sells_whole_book_and_skips_buys(self):
        positions = {
            'AAA': {'qty': '10', 'market_value': '1000'},
            'BBB': {'qty': '5', 'market_value': '500'},
        }
        with patch.object(executor, '_wait_for_network'), \
             patch.object(executor, '_set_alpaca_keys'), \
             patch.object(executor.config, 'GUARD_ENABLED', False), \
             patch.object(executor.db_module, 'get_conn', return_value=_FakeConn()), \
             patch.object(executor, '_get_alpaca_positions', return_value=positions), \
             patch.object(executor, '_get_account',
                          return_value={'equity': '100000', 'buying_power': '100000'}):
            lines = executor.execute_rotation(
                ['AAA'], {'AAA': {'close': 100.0}}, 'stock',
                dry_run=True, market_gate_off=True)
        text = '\n'.join(lines)
        self.assertIn('Market gate OFF', text)
        self.assertIn('DRY-RUN] SELL 10 AAA', text)
        self.assertIn('DRY-RUN] SELL 5 BBB', text)
        self.assertIn('0 buys', text)

    def test_etf_leg_ignores_gate_flag(self):
        positions = {'AAA': {'qty': '10', 'market_value': '1000'}}
        with patch.object(executor, '_wait_for_network'), \
             patch.object(executor, '_set_alpaca_keys'), \
             patch.object(executor.config, 'GUARD_ENABLED', False), \
             patch.object(executor.db_module, 'get_conn', return_value=_FakeConn()), \
             patch.object(executor, '_get_alpaca_positions', return_value=positions), \
             patch.object(executor, '_get_account',
                          return_value={'equity': '100000', 'buying_power': '100000'}):
            lines = executor.execute_rotation(
                ['AAA'], {'AAA': {'close': 100.0}}, 'etf',
                dry_run=True, market_gate_off=True)
        text = '\n'.join(lines)
        self.assertNotIn('Market gate OFF', text)


if __name__ == '__main__':
    unittest.main()
