# Testing Strategy (v7.0)

## Signal Logic Testing

### 2-of-4 Level-Checking Entry Signals

Test the signal computation logic in `TradeExecutorService::computeSignal()`:

**Test Case 1: Entry Signal (2 of 4)**
```
Scenario: All 4 signals positive
  MACD > 0 ✓
  PPO > 0 ✓
  EMA10 > SMA40 ✓
  Price ≤ BB_lower × 1.05 ✓
Expected: Return 1 (BUY)
```

**Test Case 2: Borderline Entry (Exactly 2 of 4)**
```
Scenario: Only MACD and PPO positive
  MACD > 0 ✓
  PPO > 0 ✓
  EMA10 < SMA40 ✗
  Price > BB_lower × 1.05 ✗
Expected: Return 1 (BUY) — signal_count = 2 is enough
```

**Test Case 3: No Entry (Only 1 of 4)**
```
Scenario: Only MACD positive
  MACD > 0 ✓
  PPO > 0 ✗
  EMA10 < SMA40 ✗
  Price > BB_lower × 1.05 ✗
Expected: Return 0 (HOLD) — signal_count = 1 is insufficient
```

**Test Case 4: Exit While in Position**
```
Scenario: In position, MACD turns negative
  Previous signal: 1 (BUY)
  Current MACD: -0.5 (< 0) ✓
Expected: Return -1 (SELL)
```

**Test Case 5: Exit via EMA/SMA Cross**
```
Scenario: In position, EMA10 drops below SMA40
  Previous signal: 1 (BUY)
  EMA10 = 690, SMA40 = 695 (EMA < SMA) ✓
Expected: Return -1 (SELL)
```

**Test Case 6: Exit via BB Break**
```
Scenario: In position, price breaks below lower BB
  Previous signal: 1 (BUY)
  Price = 679.5, BB_lower = 680.2 (price < BB) ✓
Expected: Return -1 (SELL)
```

### Manual Signal Testing

Run trade executor manually during market hours to verify signals:

```bash
# Execute trades immediately (normally runs every minute via cron)
cd backend
php artisan trades:execute-daily -v

# Monitor signal output
tail -f storage/logs/laravel.log | grep -i "signal\|ppo\|macd\|ema"

# Example output:
# [2026-05-06 15:45:02] SPY signal calc: MACD:2.20 PPO:0.55 EMA:731.03 SMA40:722.65
# [2026-05-06 15:45:02] SPY BUY SIGNAL (3/4): MACD>0, PPO>0, EMA10>SMA40
```

## Parameter Optimization Testing

### Bollinger Band Grid Search

Test that optimizer correctly evaluates all 9 combinations:

```bash
cd optimizer
source venv/bin/activate

# Run manual optimization
python nightly_optimizer.py --tickers SPY --timeframe 1Hour

# Check logs for all combinations tested
tail -f logs/nightly.log | grep -i "bb_period\|bb_std\|testing"

# Verify results saved
psql -d swingtrader -c "
  SELECT bb_period, bb_std, sharpe_ratio, total_return, total_trades
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

Verify per-ticker allocation is applied correctly in position sizing:

```bash
# Check database allocation weights
psql -d swingtrader -c "
  SELECT symbol, allocation_weight FROM tickers 
  ORDER BY symbol;
"
# Expected: SPY=40, QQQ=45, IWM=15

# Manual test: trigger trade and verify position size
php artisan trades:execute-daily -v

# Check recorded trade used correct allocation
psql -d swingtrader -c "
  SELECT t.symbol, lt.entry_price, lt.qty, 
         (lt.qty * lt.entry_price) as position_value
  FROM live_trades lt
  JOIN tickers t ON lt.ticker_id = t.id
  ORDER BY lt.created_at DESC LIMIT 3;
"

# Calculate expected size:
# position_value should ≈ (account_equity × allocation_weight%) 
# e.g., with $100k account, SPY 40%: ~$40k at current price
```

## Database Integrity Testing

After optimization or trades, verify data consistency:

```bash
# Check candidate cleanup (only latest per ticker)
psql -d swingtrader -c "
  SELECT ticker_id, COUNT(*) as candidate_count
  FROM strategy_parameters
  WHERE base_case = false
  GROUP BY ticker_id;
"
# Expected: 0 or 1 row per ticker (best candidate or none)

# Verify P&L sync (sum of trades = equity change)
psql -d swingtrader -c "
  SELECT t.symbol, 
         COUNT(*) as trades,
         ROUND(SUM(pnl_dollar)::numeric, 2) as total_pnl,
         ROUND(AVG(return)::numeric, 4) as avg_return
  FROM live_trades lt
  JOIN tickers t ON lt.ticker_id = t.id
  GROUP BY t.symbol;
"

# Check equity curve is monotonic (always increasing via closed positions)
psql -d swingtrader -c "
  SELECT snapshot_date, equity_value
  FROM equity_snapshots
  WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = 'SPY')
  AND snapshot_type = 'live'
  ORDER BY snapshot_date DESC LIMIT 10;
"
```

## Key Testing Practices (v7.0)

1. **Test signal logic independently:**
   - Use sample price data with known indicator values
   - Verify 2-of-4 thresholds work correctly
   - Test all exit conditions individually

2. **Test nightly optimizer:**
   - Verify all 9 BB combinations are tested
   - Check best result saved to `strategy_parameters`
   - Verify old candidates are deleted (no bloat)

3. **Test live execution:**
   - Run manually during market hours
   - Verify each ticker evaluated independently
   - Check position size matches allocation weight
   - Confirm trades recorded with all fields

4. **Integration tests:**
   - Run Alpaca API tests before merging API changes
   - These catch upstream API deprecations
   - Mocked tests alone are insufficient

5. **Monitor logs continuously:**
   - Signal computation logs every minute
   - Can identify logic bugs by pattern matching
   - Check for unusual signal counts or missing trades
