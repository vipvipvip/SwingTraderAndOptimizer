"""Live-adapter tests for the ETF portfolio guard (no network / no DB writes)."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import executor


class _FakeConn:
    def close(self):
        pass


def _state(**over):
    st = {
        'hwm': 100000.0,
        'reserve': 0.0,
        'pause_sessions': 0,
        'last_session': None,
        'last_action': '',
        'swept_total': 0.0,
        'stop_count': 0,
        'sweep_hwm': 100000.0,
    }
    st.update(over)
    return st


class TestGuardAdapter(unittest.TestCase):
    def _patches(self, positions, accounts, guard_state, modes=('etf',)):
        return [
            patch.object(executor, '_wait_for_network'),
            patch.object(executor, '_set_alpaca_keys'),
            patch.object(executor.config, 'GUARD_ENABLED', True),
            patch.object(executor.config, 'GUARD_MODES', modes),
            patch.object(executor.db_module, 'get_conn', return_value=_FakeConn()),
            patch.object(executor, '_get_alpaca_positions', return_value=positions),
            patch.object(executor, '_get_account', side_effect=accounts),
            patch.object(executor, 'latest_settled_daily_closes',
                         return_value={s: p['current_price'] for s, p in positions.items()}),
            patch.object(executor.db_module, 'get_guard_state',
                         return_value=(guard_state, '')),
        ]

    def _run(self, lines_of_patches, **kwargs):
        entered = []
        try:
            for p in lines_of_patches:
                entered.append(p.start())
            return executor.execute_rotation(**kwargs)
        finally:
            for p in reversed(lines_of_patches):
                p.stop()

    def test_weekly_close_stop_liquidates_dry_run_without_persisting(self):
        positions = {'AAA': {'qty': '100', 'market_value': '70000',
                             'current_price': '700'}}
        accounts = [{'equity': '100000', 'buying_power': '0', 'cash': '0'}]
        with patch.object(executor.db_module, 'save_guard_state') as save:
            lines = self._run(
                self._patches(positions, accounts, _state(reserve=40000)),
                top_symbols=['AAA'], score_detail={'AAA': {'close': 700.0}},
                mode='etf', dry_run=True)
        text = '\n'.join(lines)
        self.assertIn('Guard HWM stop', text)
        self.assertIn('DRY-RUN] SELL 100 AAA', text)
        self.assertIn('0 buys', text)
        self.assertNotIn('BUY', text)
        save.assert_not_called()

    def test_stock_config_uses_15pct_stop_and_no_sweep(self):
        stock = executor._guard_config('stock')
        self.assertAlmostEqual(stock.hwm_stop_pct, 0.15)
        self.assertEqual(stock.sweep_pct, 0.0)
        self.assertEqual(executor._guard_setting('stock', 'STOP_CHECK', 'weekly'),
                         'weekly')
        etf = executor._guard_config('etf')
        self.assertAlmostEqual(etf.hwm_stop_pct, 0.20)
        self.assertAlmostEqual(etf.sweep_pct, 0.25)

    def test_stock_weekly_stop_liquidates_dry_run_without_persisting(self):
        positions = {'AAA': {'qty': '100', 'market_value': '70000',
                             'current_price': '700'}}
        accounts = [{'equity': '70000', 'buying_power': '0', 'cash': '0'}]
        with patch.object(executor.db_module, 'save_guard_state') as save:
            lines = self._run(
                self._patches(positions, accounts, _state(),
                              modes=('etf', 'stock')),
                top_symbols=['AAA'], score_detail={'AAA': {'close': 700.0}},
                mode='stock', dry_run=True)
        text = '\n'.join(lines)
        self.assertIn('Guard HWM stop', text)
        self.assertIn('DRY-RUN] SELL 100 AAA', text)
        self.assertIn('0 buys', text)
        save.assert_not_called()

    def test_profit_sweep_preview_trims_without_persisting(self):
        positions = {'AAA': {'qty': '100', 'market_value': '130000',
                             'current_price': '1300'}}
        accounts = [{'equity': '130000', 'buying_power': '0', 'cash': '0'},
                    {'equity': '130000', 'buying_power': '0', 'cash': '0'},
                    {'equity': '130000', 'buying_power': '0', 'cash': '0'}]
        with patch.object(executor.db_module, 'save_guard_state') as save:
            lines = self._run(
                self._patches(positions, accounts, _state()),
                top_symbols=['AAA'], score_detail={'AAA': {'close': 1300.0}},
                mode='etf', dry_run=True)
        text = '\n'.join(lines)
        self.assertIn('Guard sweep $7,500.00', text)
        self.assertIn('DRY-RUN] TRIM 6 AAA', text)
        self.assertIn('Guard reserve $7,500.00', text)
        save.assert_not_called()

    def test_live_sweep_records_only_cash_actually_moved(self):
        positions = {'AAA': {'qty': '100', 'market_value': '130000',
                             'current_price': '1300'}}
        accounts = [{'equity': '130000', 'buying_power': '0', 'cash': '0'},
                    {'equity': '130000', 'buying_power': '0', 'cash': '0'},
                    {'equity': '130000', 'buying_power': '0', 'cash': '7800'}]
        fill = {'id': 'o1', 'status': 'filled', 'filled_qty': '6',
                'filled_avg_price': '1300'}
        with patch.object(executor, '_cancel_orders_for_symbol'), \
             patch.object(executor, '_cancel_all_open_orders'), \
             patch.object(executor, '_place_order', return_value=fill), \
             patch.object(executor, '_send_slack'), \
             patch.object(executor.db_module, 'get_ticker_id_from_symbol', return_value=1), \
             patch.object(executor.db_module, 'get_position',
                          return_value=(1, 'AAA', 100.0)), \
             patch.object(executor.db_module, 'adjust_position_qty'), \
             patch.object(executor.db_module, 'insert_trade'), \
             patch.object(executor.db_module, 'save_guard_state') as save:
            lines = self._run(
                self._patches(positions, accounts, _state()),
                top_symbols=['AAA'], score_detail={'AAA': {'close': 1300.0}},
                mode='etf', dry_run=False)
        text = '\n'.join(lines)
        self.assertIn('Guard sweep: $7,500.00', text)
        save.assert_called_once()
        saved = save.call_args.args[2]
        self.assertAlmostEqual(saved['reserve'], 7500.0)
        self.assertAlmostEqual(saved['swept_total'], 7500.0)
        self.assertAlmostEqual(saved['hwm'], 130000.0)


if __name__ == '__main__':
    unittest.main()
