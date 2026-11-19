"""Unit tests for the CMO daily signal core (no DB, no network)."""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cmo_core as c


class TestMovingAverages(unittest.TestCase):
    def test_wma_linear_weights(self):
        out = c.wma([1, 2, 3, 4], 3)
        self.assertTrue(math.isnan(out[0]) and math.isnan(out[1]))
        self.assertAlmostEqual(out[2], 14 / 6)
        self.assertAlmostEqual(out[3], 20 / 6)

    def test_wma_short_series_is_nan(self):
        self.assertTrue(np.isnan(c.wma([1, 2], 3)).all())

    def test_ema_matches_recursion(self):
        out = c.ema([1, 2, 3], 3)
        self.assertEqual(list(out), [1.0, 1.5, 2.25])

    def test_ema_skips_leading_non_finite(self):
        out = c.ema([np.nan, np.nan, 5.0, 6.0], 3)
        self.assertTrue(math.isnan(out[0]) and math.isnan(out[1]))
        self.assertEqual(out[2], 5.0)
        self.assertAlmostEqual(out[3], 5.5)

    def test_sma(self):
        out = c.sma([1, 2, 3, 4], 2)
        self.assertTrue(math.isnan(out[0]))
        self.assertEqual(list(out[1:]), [1.5, 2.5, 3.5])


class TestCmo(unittest.TestCase):
    def test_all_up_is_100(self):
        out = c.cmo([1, 2, 3, 4, 5], 2)
        self.assertAlmostEqual(out[2], 100.0)
        self.assertAlmostEqual(out[4], 100.0)

    def test_all_down_is_minus_100(self):
        out = c.cmo([5, 4, 3, 2, 1], 2)
        self.assertAlmostEqual(out[2], -100.0)

    def test_mixed_hand_calc(self):
        out = c.cmo([1, 2, 1, 3], 2)
        self.assertAlmostEqual(out[2], 0.0)           # +1, -1
        self.assertAlmostEqual(out[3], 100.0 / 3.0)   # -1, +2

    def test_flat_is_zero(self):
        out = c.cmo([5, 5, 5, 5], 2)
        self.assertAlmostEqual(out[2], 0.0)

    def test_needs_period_plus_one_closes(self):
        out = c.cmo([1, 2], 2)
        self.assertTrue(np.isnan(out).all())


class TestMacd(unittest.TestCase):
    def test_diff_is_val_minus_avg(self):
        closes = np.exp(np.linspace(0, 2, 200))   # accelerating uptrend
        val, avg, diff = c.macd(closes)
        ok = np.isfinite(diff)
        self.assertTrue(ok.any())
        np.testing.assert_allclose(diff[ok], (val - avg)[ok])
        self.assertGreater(val[-1], 0)
        self.assertGreater(diff[-1], 0)           # signal lags a rising Val

    def test_ema_variant_runs(self):
        closes = np.linspace(10, 200, 200)
        val, avg, diff = c.macd(closes, ma_type='ema')
        self.assertTrue(np.isfinite(diff).any())

    def test_bollinger_mid_is_ema(self):
        closes = np.linspace(10, 200, 100)
        mid, up, lo = c.bollinger(closes, 20, 2.0, mid_type='ema')
        np.testing.assert_allclose(mid, c.ema(closes, 20))
        self.assertTrue(np.all(up[np.isfinite(up)] >= mid[np.isfinite(up)]))
        self.assertTrue(np.all(lo[np.isfinite(lo)] <= mid[np.isfinite(lo)]))


def _base_ind(n=120, macd=0.5, sma20=1.5):
    return {
        'close': np.linspace(10, 10 + n, n),
        'cmo': np.full(n, 10.0),
        'ema10': np.full(n, 3.0),
        'bb_mid': np.full(n, 2.0),
        'sma20': np.full(n, sma20),
        'macd_diff': np.full(n, macd),
        'macd_val': np.full(n, macd + 1.0),
        'macd_avg': np.full(n, 1.0),
    }


def _buy_ind(n=120):
    ind = _base_ind(n)
    ind['cmo'][100] = -1.0
    ind['cmo'][101:] = 10.0
    ind['ema10'][:102] = 1.0
    ind['ema10'][102:] = 3.0
    return ind


class TestSignalArrays(unittest.TestCase):
    def test_armed_buy_window(self):
        arr = c.build_signal_arrays(_buy_ind(), window=10, mode='armed')
        self.assertTrue(arr['buy'][102])
        self.assertTrue(arr['buy'][105])
        self.assertFalse(arr['buy'][101])          # BB cross not yet
        self.assertFalse(arr['buy'][112])          # events older than 10 bars
        sig = c.signal_at(arr, 105)
        self.assertTrue(sig.buy)
        self.assertEqual(sig.days_cmo_up, 4)
        self.assertEqual(sig.days_bb_up, 3)

    def test_states_must_hold_today(self):
        ind = _buy_ind()
        ind['macd_diff'][100:] = -0.5              # state flips bearish after events
        arr = c.build_signal_arrays(ind, window=10, mode='armed')
        self.assertFalse(arr['buy'][105])

    def test_same_bar_mode(self):
        ind = _buy_ind()
        arr_same = c.build_signal_arrays(ind, window=10, mode='same_bar')
        arr_armed = c.build_signal_arrays(ind, window=10, mode='armed')
        self.assertFalse(arr_same['buy'][105])     # no cross on 105 itself
        self.assertTrue(arr_armed['buy'][105])

    def test_cmo_bb_mode(self):
        ind = _base_ind(n=120)
        ind['cmo'][98] = -1.0
        ind['cmo'][99:] = 10.0
        ind['ema10'][:98] = 1.0
        ind['ema10'][98:110] = 3.0
        ind['ema10'][110:] = 1.0
        ind['cmo'][109] = 10.0
        ind['cmo'][110:] = -10.0
        arr = c.build_signal_arrays(ind, mode='cmo_bb')
        self.assertTrue(arr['buy'][99])
        self.assertFalse(arr['buy'][100])
        self.assertTrue(arr['sell'][110])
        self.assertFalse(arr['sell'][111])

    def test_any_in_window_mode(self):
        ind = _buy_ind()
        ind['macd_diff'][100:105] = -0.5           # bearish earlier, bullish today
        arr = c.build_signal_arrays(ind, window=10, mode='any_in_window')
        self.assertTrue(arr['buy'][105])

    def _sell_ind(self, n=120):
        ind = _base_ind(n)
        # bullish until 109, then bearish
        ind['cmo'][100] = -1.0
        ind['cmo'][101:108] = 10.0
        ind['cmo'][108] = 10.0
        ind['cmo'][109:] = -10.0
        ind['ema10'][:102] = 1.0
        ind['ema10'][102:110] = 3.0
        ind['ema10'][110:] = 1.0
        ind['macd_diff'][:110] = 0.5
        ind['macd_diff'][110:] = -0.5
        return ind

    def test_mirror_sell(self):
        arr = c.build_signal_arrays(self._sell_ind(), window=10, mode='armed',
                                    sell_mode='mirror')
        self.assertFalse(arr['sell'][108])
        self.assertTrue(arr['sell'][111])
        self.assertTrue(arr['sell'][113])
        self.assertFalse(arr['sell'][120 - 1])     # window expired

    def test_any_sell_is_faster(self):
        ind = self._sell_ind()
        ind['ema10'][110:] = 3.0                   # BB down-cross does not happen
        mirror = c.build_signal_arrays(ind, window=10, mode='armed', sell_mode='mirror')
        any_sell = c.build_signal_arrays(ind, window=10, mode='armed', sell_mode='any')
        self.assertFalse(mirror['sell'][112])
        self.assertTrue(any_sell['sell'][112])

    def test_invalid_rejects(self):
        ind = _base_ind(n=60)                      # below warm-up
        arr = c.build_signal_arrays(ind)
        self.assertFalse(arr['buy'].any())
        self.assertFalse(arr['valid'].any())


class TestChainMode(unittest.TestCase):
    def test_chain_fires_on_fourth_condition_any_order(self):
        arr = c.build_signal_arrays(_buy_ind(), mode='chain')
        self.assertFalse(arr['buy'][101])
        self.assertTrue(arr['buy'][102])
        self.assertFalse(arr['buy'][103])        # one-shot, needs a fresh chain

    def test_chain_window(self):
        ind = _base_ind(n=140)
        ind['cmo'][84] = -1.0
        ind['cmo'][85:] = 10.0                   # CMO up-cross at 85
        ind['ema10'][:106] = 1.0
        ind['ema10'][106:] = 3.0                 # BB cross + EMA>SMA at 106
        chain30 = c.build_signal_arrays(ind, mode='chain', window=30)
        chain10 = c.build_signal_arrays(ind, mode='chain', window=10)
        chain0 = c.build_signal_arrays(ind, mode='chain', window=0)
        armed = c.build_signal_arrays(ind, mode='armed')
        self.assertTrue(chain30['buy'][106])     # 21 bars apart fits in 30
        self.assertFalse(chain10['buy'][106])    # expired under 10
        self.assertTrue(chain0['buy'][106])      # 0 = no expiry
        self.assertFalse(armed['buy'][106])      # outside the 10-bar window

    def test_chain_mirror_sell(self):
        ind = _base_ind(n=140)
        ind['cmo'][:] = -10.0
        ind['cmo'][100] = 10.0
        ind['cmo'][101:] = -10.0                 # CMO down-cross at 101
        ind['ema10'][:] = 1.0
        ind['ema10'][100] = 3.0
        ind['ema10'][101:] = 1.0                 # BB down-cross at 101
        ind['macd_diff'][:] = -0.5
        arr = c.build_signal_arrays(ind, mode='chain')
        self.assertFalse(arr['sell'][100])
        self.assertTrue(arr['sell'][101])
        self.assertFalse(arr['sell'][102])       # one-shot


class TestBook(unittest.TestCase):
    @staticmethod
    def _sig(buy=False, sell=False, days_cmo=1, diff=0.5, gap=1.0):
        return c.Signal(buy=buy, sell=sell, valid=True, cmo=1.0, macd_val=1.0,
                        macd_avg=0.5, macd_diff=diff, ema10=3.0, bb_mid=2.0,
                        sma20=1.5, days_cmo_up=days_cmo, days_bb_up=1,
                        days_cmo_down=-1, days_bb_down=-1)

    def test_sells_only_triggered_and_preserves_missing(self):
        states = {
            'AAA': self._sig(sell=True),
            'BBB': self._sig(buy=True, days_cmo=3, diff=0.4, gap=0.5),
            'CCC': self._sig(),                    # held, no buy, no sell
            'DDD': self._sig(buy=True, days_cmo=1, diff=0.9, gap=2.0),
        }
        book = c.build_book(['AAA', 'CCC', 'EEE'], states, top_n=3)
        self.assertEqual(book['sells'], ['AAA'])
        self.assertIn('CCC', book['target'])       # stateful hold
        self.assertIn('EEE', book['missing'])      # no data -> preserved
        self.assertEqual(len(book['target']), 3)
        self.assertIn('DDD', book['target'])       # fresher CMO cross wins the slot
        self.assertNotIn('BBB', book['target'])

    def test_never_exceeds_capacity(self):
        states = {f'S{i}': self._sig(buy=True, days_cmo=i) for i in range(5)}
        book = c.build_book(['H1', 'H2', 'H3'], states, top_n=3)
        self.assertEqual(len(book['target']), 3)
        self.assertEqual(book['new'], [])

    def test_held_without_signal_is_not_bought_again(self):
        states = {'AAA': self._sig()}
        book = c.build_book(['AAA'], states, top_n=25)
        self.assertEqual(book['target'], ['AAA'])
        self.assertEqual(book['new'], [])

    def test_rank_is_deterministic(self):
        a = self._sig(buy=True, days_cmo=2, diff=0.5, gap=1.0)
        b = self._sig(buy=True, days_cmo=2, diff=0.5, gap=1.0)
        self.assertEqual(c.rank_key('AAA', a), c.rank_key('AAA', b))
        self.assertLess(c.rank_key('AAA', a), c.rank_key('BBB', b))


if __name__ == '__main__':
    unittest.main()
