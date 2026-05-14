# Testing Strategy (v7.5)

## Signal Logic Testing

### Chandelier Exit Signal Logic

Test the signal computation in `TradeExecutorService::computeChandelierSignal()`:

**Test Case 1: Entry When Flat**
```
Scenario: No position open
  inPosition = false
Expected: Return 1 (BUY) — always re-enter when flat
```

**Test Case 2: Hold While In Position (Stop Not Hit)**
```
Scenario: In position, price well above stop
  inPosition = true
  close = 700, stop_level = 680
Expected: Return 0 (HOLD)
```

**Test Case 3: Exit When Stop Is Hit**
```
Scenario: In position, price crosses below trailing stop
  inPosition = true
  close = 675, stop_level = 680 (close < stop)
Expected: Return -1 (SELL)
```

**Test Case 4: Same-Day Exit Guard**
```
Scenario: Exited today, don't re-enter
  inPosition = false
  exitedToday = true
Expected: Return 0 (HOLD) — skip re-entry for rest of day
```

**Test Case 5: Trailing Stop Moves Up**
```
Scenario: Price rises after entry, stop trails higher
  Entry at 690, highest_high since entry = 720
  atr = 8, multiplier = 2.0
  stop = 720 - 8 × 2.0 = 704
  close = 710 (above stop) → HOLD
  If close drops to 700 (below stop) → SELL
```

### Manual Signal Testing

Run trade executor manually during market hours:

```bash
cd backend
php artisan trades:execute-daily -v

# Monitor signal output
sudo journalctl -u swingtrader-backend -f | grep -i "signal\|chandelier\|atr\|stop"
```

## Parameter Optimization Testing

### Chandelier Grid Search

Test that optimizer evaluates all 9 combinations:

```bash
cd optimizer
source venv/bin/activate

# Run manual optimization
python nightly_optimizer.py --tickers SPY --timeframe 1Hour

# Check logs
tail -f logs/nightly.log | grep -i "period\|multiplier\|testing"

# Verify results saved
psql -U swingtrader -d swingtrader -c "
  SELECT macd_fast as period, bb_std as multiplier, sharpe_ratio, total_return, total_trades
  FROM strategy_parameters
  WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = 'SPY')
  AND base_case = false
  ORDER BY sharpe_ratio DESC LIMIT 5;
"
```

**Expected:** 9 parameter combinations tested, best one has highest Sharpe ratio.

## Integration Tests (Hit Real APIs)

These tests connect to real Alpaca services. Run before API-related changes.

| Test | Service | Detects |
|------|---------|---------|
| `AlpacaServiceTest::test_getBars_connects_to_real_alpaca_api` | Alpaca Data API | Auth failure, endpoint deprecation |
| `AlpacaServiceTest::test_getAccount_connects_to_trading_api` | Alpaca Trading API | Paper trading account availability |
| `AlpacaServiceTest::test_getPositions_returns_valid_format` | Alpaca Positions API | Position schema changes |

**Run integration tests:**
```bash
cd backend
./vendor/bin/phpunit tests/Feature/AlpacaServiceTest.php -v
```

## Allocation Weight Testing

Verify per-ticker allocation is applied correctly:

```bash
# Check database allocation weights
psql -U swingtrader -d swingtrader -c "
  SELECT symbol, allocation_weight FROM tickers 
  ORDER BY symbol;
"
# Expected: SPY=40, QQQ=45, IWM=15

# Check recorded trade used correct allocation
psql -U swingtrader -d swingtrader -c "
  SELECT t.symbol, lt.entry_price, lt.qty, 
         (lt.qty * lt.entry_price) as position_value
  FROM live_trades lt
  JOIN tickers t ON lt.ticker_id = t.id
  ORDER BY lt.created_at DESC LIMIT 3;
"
```

## Database Integrity Testing

```bash
# Check candidate cleanup (only latest per ticker)
psql -U swingtrader -d swingtrader -c "
  SELECT ticker_id, COUNT(*) as candidate_count
  FROM strategy_parameters
  WHERE base_case = false
  GROUP BY ticker_id;
"
# Expected: 0 or 1 row per ticker

# Verify P&L sync
psql -U swingtrader -d swingtrader -c "
  SELECT t.symbol, 
         COUNT(*) as trades,
         ROUND(SUM(pnl_dollar)::numeric, 2) as total_pnl,
         ROUND(AVG(return)::numeric, 4) as avg_return
  FROM live_trades lt
  JOIN tickers t ON lt.ticker_id = t.id
  GROUP BY t.symbol;
"
```

## Key Testing Practices (v7.5)

1. **Test Chandelier Exit logic independently:**
   - Verify trailing stop calculation: `stop = highest_high - ATR × multiplier`
   - Test same-day exit guard
   - Test re-entry on next day

2. **Test nightly optimizer:**
   - Verify all 9 Chandelier combinations are tested
   - Check best result saved to `strategy_parameters`
   - Verify old candidates deleted (no bloat)

3. **Test live execution:**
   - Run manually during market hours
   - Verify stop levels are calculated correctly
   - Check position size matches allocation weight
   - Confirm trades recorded with all fields

4. **Integration tests:**
   - Run Alpaca API tests before merging API changes
   - These catch upstream API deprecations

5. **Monitor logs continuously:**
   - Signal computation logs every minute
   - Check for unusual stop_level values or gaps
