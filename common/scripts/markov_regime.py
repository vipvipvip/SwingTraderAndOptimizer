"""Markov regime detection via Hidden Markov Models.

Shared between scanner (indicator computation) and optimizer (regime-aware backtesting).
"""

import logging
import warnings

import numpy as np
import pandas as pd

from hmmlearn import hmm

logger = logging.getLogger(__name__)


class MarkovRegime:
    """HMM-based regime classifier with automatic state labeling.

    Features:
      - log_return: log(close / close.shift(1))
      - volatility: rolling std of log returns (lookback window)
      - momentum: (close / close.shift(lookback) - 1)

    States are auto-labeled as Bull, Bear, Choppy by sorting on mean momentum.
    """

    def __init__(self, n_states=3, lookback=20, seed=42):
        if n_states not in (2, 3, 4):
            raise ValueError("n_states must be 2, 3, or 4")
        self.n_states = n_states
        self.lookback = lookback
        self.seed = seed
        self.model = None
        self._label_map = {}
        self._state_names = ['Bear', 'Choppy', 'Bull', 'Crisis']

    def _compute_features(self, df):
        close = df['close'].astype(float)
        log_ret = np.log(close / close.shift(1)).fillna(0)
        vol = log_ret.rolling(window=self.lookback).std().fillna(0)
        momentum = (close / close.shift(self.lookback) - 1).fillna(0)
        features = pd.DataFrame({
            'log_return': log_ret,
            'volatility': vol,
            'momentum': momentum,
        })
        if len(features) < self.lookback + 10:
            return None
        return features

    def fit(self, features):
        vals = features.values if isinstance(features, pd.DataFrame) else features
        self.model = hmm.GaussianHMM(
            n_components=self.n_states,
            covariance_type='diag',
            random_state=self.seed,
            n_iter=100,
            tol=1e-3,
        )
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.model.fit(vals)
        self._label_states(self.model)
        return self

    def _label_states(self, model):
        momentum_idx = 2
        means = model.means_[:, momentum_idx]
        if np.any(np.isnan(means)):
            self._label_map = {i: f'State_{i}' for i in range(self.n_states)}
            return
        sorted_idx = np.argsort(means)
        names = [n for n in self._state_names if n != 'Crisis'][:self.n_states]
        if self.n_states == 4:
            names = self._state_names[:4]
        self._label_map = {sorted_idx[i]: names[i] for i in range(self.n_states)}

    def _check_model(self):
        if self.model is None:
            return False
        try:
            self.model._check()
            return True
        except Exception:
            return False

    def predict(self, features):
        vals = features.values if isinstance(features, pd.DataFrame) else features
        if not self._check_model():
            return np.array([None] * len(vals))
        states = self.model.predict(vals)
        return np.array([self._label_map.get(s, f'State_{s}') for s in states])

    def predict_proba(self, features):
        vals = features.values if isinstance(features, pd.DataFrame) else features
        if not self._check_model():
            return np.ones((len(vals), self.n_states)) / self.n_states
        return self.model.predict_proba(vals)

    def predict_proba_labeled(self, features):
        vals = features.values if isinstance(features, pd.DataFrame) else features
        if not self._check_model():
            n = len(vals)
            result = np.zeros((n, self.n_states))
            result[:, 0] = 1.0
            return result
        raw_probs = self.model.predict_proba(vals)
        state_names = [self._label_map.get(i, f'State_{i}') for i in range(self.n_states)]
        ordered = []
        for name in ['Bull', 'Bear', 'Choppy', 'Crisis'][:self.n_states]:
            if name in state_names:
                idx = state_names.index(name)
                ordered.append(raw_probs[:, idx])
            else:
                ordered.append(np.zeros(len(vals)))
        return np.column_stack(ordered)

    def fit_predict(self, df):
        features = self._compute_features(df)
        if features is None:
            return None
        valid = features.dropna()
        if len(valid) < self.lookback + 10:
            return None
        try:
            self.fit(valid)
        except Exception:
            return None
        if not self._check_model():
            return None
        states = self.predict(valid)
        probs = self.predict_proba_labeled(valid)
        result = df.copy()
        result['hmm_regime'] = pd.NA
        result['hmm_regime'] = result['hmm_regime'].astype('string')
        name_cols = ['Bull', 'Bear', 'Choppy', 'Crisis'][:self.n_states]
        for i, name in enumerate(name_cols):
            result[f'hmm_{name.lower()}_prob'] = np.nan
            result.loc[valid.index, f'hmm_{name.lower()}_prob'] = probs[:, i]
        result.loc[valid.index, 'hmm_regime'] = states
        return result

    def walk_forward_predict(self, df, train_size=504, step=20):
        features = self._compute_features(df)
        if features is None:
            return None
        result = df.copy()
        result['hmm_regime'] = pd.NA
        result['hmm_regime'] = result['hmm_regime'].astype('string')
        for c in ['Bull', 'Bear', 'Choppy', 'Crisis'][:self.n_states]:
            result[f'hmm_{c.lower()}_prob'] = np.nan

        n = len(features)
        start = min(train_size, n // 2)
        for i in range(start, n, step):
            train = features.iloc[max(0, i - train_size):i].dropna()
            if len(train) < self.lookback + 10:
                continue
            local = MarkovRegime(n_states=self.n_states, lookback=self.lookback, seed=self.seed)
            try:
                local.fit(train)
            except Exception:
                continue
            if not local._check_model():
                continue
            end = min(i + step, n)
            test = features.iloc[i:end].dropna()
            if len(test) == 0:
                continue
            try:
                states = local.predict(test)
                probs = local.predict_proba_labeled(test)
            except Exception:
                continue
            name_cols = ['Bull', 'Bear', 'Choppy', 'Crisis'][:self.n_states]
            for j, name in enumerate(name_cols):
                result.loc[test.index, f'hmm_{name.lower()}_prob'] = probs[:, j]
            result.loc[test.index, 'hmm_regime'] = states
        return result
