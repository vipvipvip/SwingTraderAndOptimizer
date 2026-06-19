#!/usr/bin/env python3
"""Build 30-min OHLCV candles from raw trade ticks.

Polls Alpaca's trades endpoint every cycle and groups ticks
into 30-min windows. Completed windows are flushed to emac_candles.
Incomplete window trades are persisted to disk for crash recovery.
"""
import json
import os
from datetime import datetime, timedelta, timezone

BAR_MINUTES = 30


def bar_timestamp(ts):
    """Round a datetime down to the nearest 30-min boundary (UTC)."""
    minute = (ts.minute // BAR_MINUTES) * BAR_MINUTES
    return ts.replace(minute=minute, second=0, microsecond=0)


def build_state_path():
    return os.path.join(os.path.dirname(__file__), '.emac_buffer.json')


class CandleBuilder:
    """Accumulates trade ticks, produces OHLCV candles.

    State is persisted so an incomplete bar survives a restart.
    """

    def __init__(self, db_conn, state_path=None):
        self.conn = db_conn
        self.path = state_path or build_state_path()
        # {(ticker_id, bar_ts): {open, high, low, close, volume, count}}
        self._buffer = {}
        self._last_ts = {}  # ticker_id -> latest trade timestamp seen
        self._load()

    # ── public API ──

    @staticmethod
    def _parse_ts(raw):
        if isinstance(raw, str):
            if raw.endswith('Z'):
                raw = raw[:-1]
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return raw

    @staticmethod
    def _fmt_ts(dt):
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    def feed(self, ticker_id, trades):
        """Ingest raw trade ticks. Each trade: {t, p, s}."""
        for t in trades:
            ts = self._parse_ts(t['t'])
            price = float(t['p'])
            size = int(t['s'])

            bts = bar_timestamp(ts)
            key = (ticker_id, bts)
            b = self._buffer.get(key)
            if b is None:
                self._buffer[key] = {
                    'open': price, 'high': price, 'low': price,
                    'close': price, 'volume': size, 'count': 1,
                }
            else:
                if price > b['high']:
                    b['high'] = price
                if price < b['low']:
                    b['low'] = price
                b['close'] = price
                b['volume'] += size
                b['count'] += 1

        if trades:
            ts = self._parse_ts(trades[-1]['t'])
            self._last_ts[ticker_id] = self._fmt_ts(ts)

    def pop_completed(self, ticker_id, now_utc=None):
        """Return completed OHLCV bars whose 30-min window is fully in the past.

        Returns list of (ticker_id, bar_ts, o, h, l, c, v).
        Removes them from the buffer.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        completed = []
        for (tid, bts), b in list(self._buffer.items()):
            if tid != ticker_id:
                continue
            bar_end = bts + timedelta(minutes=BAR_MINUTES)
            if bar_end <= now_utc:
                completed.append((tid, bts, b['open'], b['high'],
                                  b['low'], b['close'], b['volume']))
                del self._buffer[(tid, bts)]
        return completed

    def get_last_ts(self, ticker_id):
        """Return the last trade timestamp for a ticker (ISO str or None)."""
        return self._last_ts.get(ticker_id)

    def save(self):
        """Persist state to disk."""
        state = {
            'last_ts': self._last_ts,
            'buffer': [
                [tid, bts.isoformat(), b]
                for (tid, bts), b in self._buffer.items()
            ],
        }
        with open(self.path, 'w') as f:
            json.dump(state, f, default=str)

    def close(self):
        self.save()

    # ── private ──

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                state = json.load(f)
            self._last_ts = state.get('last_ts', {})
            for tid_str, bts_str, b in state.get('buffer', []):
                key = (int(tid_str), datetime.fromisoformat(bts_str))
                self._buffer[key] = b
        except Exception:
            self._buffer = {}
            self._last_ts = {}
