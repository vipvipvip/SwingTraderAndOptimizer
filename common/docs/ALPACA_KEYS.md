# Alpaca Paper-Account Keys — Routing Reference

> **The ONE page to open whenever new Alpaca keys are issued.** Every paper
> account has exactly one home file (its `.env`). Apply a new key pair to the
> file(s) below and verify each against the live account API. All 4 key sets
> verified 2026-09-15.

## Account → File/Variable Map

| # | Account (paper) | Account # | Env file | Variable names |
|---|-----------------|-----------|----------|----------------|
| 1 | **CoreEW** (trio, Laravel `ExecuteEWETF`) | `#PA3GKZYLVO68` | `swingtrader/backend/.env` | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` |
| 2 | **Scanner** (read-only market data: `capture_hourly.py`, `populate_tickers.py`, Explorer) | (reuses CoreEW keys) | `scanner/backend/.env` | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` |
| 3 | **MTF-Stocks** (emasma top-N stock leg) | `#PA368CPXNS13` | `swingtrader/services/mtf/.env` | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` |
| 4 | **MTF-ETFs** (emasma ETF leg) | `#PA3U8GZ96PEN` | `swingtrader/services/mtf/.env` (SAME file as #3) | `ALPACA_ETF_API_KEY`, `ALPACA_ETF_SECRET_KEY` |

## The critical gotcha (broke ETF bars 2026-09-14→15)

**CoreEW keys are used TWICE** — in `swingtrader/backend/.env` **AND**
`scanner/backend/.env`. The scanner is a read-only consumer of the Alpaca IEX
market-data feed (it never places orders), and its `scanner/services/config.py`
loads keys from `scanner/backend/.env`, a DIFFERENT file from the one CoreEW
reads. When CoreEW keys rotate, you MUST update:
1. `swingtrader/backend/.env` (CoreEW trading)
2. `scanner/backend/.env` (scanner data)

If you only update #1, the scanner silently 401s on every market-data call from
the moment the new keys are issued — hourly/ETF bars freeze, Explorer + MTF
scoring go stale, and only the data-readiness gates or chart staleness surface
it (this exact failure: hourly/ETF capture 401 from 09-14 10:10 until 09-15).

## Verification (after every key change)

Run the account-status check — each row must show its own paper account #:

```bash
python3 - <<'PY'
import requests
def acct(env_path, key, sec):
    d = {}
    for line in open(env_path):
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            d[k] = v.strip().strip('"')
    r = requests.get('https://paper-api.alpaca.markets/v2/account',
        headers={'APCA-API-KEY-ID': d[key], 'APCA-API-SECRET-KEY': d[sec]}, timeout=15)
    return r.json().get('account_number', r.status_code)
print('CoreEW     (swingtrader/backend/.env   ALPACA)      ->', acct('swingtrader/backend/.env','ALPACA_API_KEY','ALPACA_SECRET_KEY'))
print('Scanner    (scanner/backend/.env       ALPACA)      ->', acct('scanner/backend/.env','ALPACA_API_KEY','ALPACA_SECRET_KEY'))
print('MTF stock  (mtf/.env                   ALPACA)      ->', acct('swingtrader/services/mtf/.env','ALPACA_API_KEY','ALPACA_SECRET_KEY'))
print('MTF ETF    (mtf/.env                   ALPACA_ETF)  ->', acct('swingtrader/services/mtf/.env','ALPACA_ETF_API_KEY','ALPACA_ETF_SECRET_KEY'))
PY
```

Expected: `CoreEW == Scanner == #PA3GKZYLVO68`, `MTF stock == #PA368CPXNS13`,
`MTF ETF == #PA3U8GZ96PEN`. A 401 anywhere = that key still not applied/rotated.

## Who loads which file (wiring, so future edits stay honest)

- `scanner/services/config.py:5` loads `scanner/backend/.env` → ALL scanner
  scripts (`capture_hourly.py`, `populate_tickers.py`, `data_readiness.py`,
  `compute_indicators.py` indirect, Explorer backend). Read-only IEX feed.
- `swingtrader/backend/.env` → Laravel `ExecuteEWETF` (CoreEW trading) + `alpaca_report.py --strategy coreew`.
- `swingtrader/services/mtf/config.py:4` `load_dotenv()` (WorkingDirectory =
  `swingtrader/services/mtf`) → `swingtrader/services/mtf/.env` → MTF runner/executor.
- `swingtrader/services/mtf/runner.py` uses `ALPACA_API_KEY` for stocks AND
  `ALPACA_ETF_API_KEY` for ETFs from the same MTF `.env` — the ONE file has both
  MTF variable pairs.
- `swingtrader/services/ema_sma_crossover/.env` → DB + Slack only (Daily Signal
  service) — **no Alpaca keys** (EMAC trading stopped).
- `swingtrader/services/scripts/alpaca_report.py` reads all 3 trading accounts
  from the same env files (read-only report, never places orders).

## Legacy locations that still read a CoreEW key

- `swingtrader/services/optimizer/.env` — disabled/nightly legacy (backtest/
  data-fetch scripts, no enabled timers) but its scripts call `load_dotenv()`
  on that file. It holds the CoreEW key pair (read-only use, like the scanner).
  If you ever re-enable the optimizer, refresh these too.

> Stale dead key `PK7DIID…` was found in `scanner/backend/.env` (the 09-14→15
> ETF outage) AND `swingtrader/services/optimizer/.env` on 2026-09-15; both
> now carry the valid key set. No stale copies remain repo-wide (grep
> `PK7DIID` returns nothing).

## Stopped / legacy accounts (do NOT put new keys here)

- EMAC `#PA3EHVX93SJT` — stopped 2026-08-10; key file only has DB/Slack now.
- MTCS `#PA3NCXU4O2CN` — stopped 2026-08-10; code deleted.
- Old MTF-Stocks `#PA3H8RAWIS0C` — abandoned; keys dead/401, cannot liquidate.
- CHAND `#PA31Z71315NM` — superseded by CoreEW reset `#PA3GKZYLVO68`.