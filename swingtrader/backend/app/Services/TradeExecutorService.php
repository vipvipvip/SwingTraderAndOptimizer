<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\LiveTrade;
use App\Models\PositionCache;

class TradeExecutorService
{
    use MarketDataTrait;
    private $alpacaService;
    private $strategyService;
    private $equityService;
    private $dryRun = false;

    public function __construct(AlpacaService $alpaca, StrategyService $strategy, EquityService $equity)
    {
        $this->alpacaService = $alpaca;
        $this->strategyService = $strategy;
        $this->equityService = $equity;
    }

    /**
     * Validate that strategy parameters are in sync with backtest data
     * Ensures executor is always using base_case=1 (locked) parameters
     */
    private function validateStrategySync($symbol)
    {
        $strategy = $this->strategyService->getStrategyForSymbol($symbol);
        if (!$strategy || !$strategy['params']) {
            \Log::warning("$symbol: Strategy validation - NO PARAMETERS FOUND");
            return false;
        }

        $params = $strategy['params'];

        // Verify this is base_case=1
        if (!isset($params['base_case']) || $params['base_case'] != 1) {
            \Log::error("$symbol: CRITICAL - Using non-base-case parameters! base_case=" . ($params['base_case'] ?? 'null'));
            return false;
        }

        // Verify we have the required parameters for Chandelier Exit
        $required = ['chandelier_period', 'chandelier_mult', 'atr_period'];

        foreach ($required as $param) {
            if (!isset($params[$param])) {
                \Log::error("$symbol: CRITICAL - Missing parameter: $param");
                return false;
            }
        }

        \Log::debug("$symbol: Strategy sync validated - base_case=1, chandelier params present");
        return true;
    }

    public function executeForAllTickers($override = false, $dryRun = false)
    {
        $this->dryRun = $dryRun;

        // Reconcile live_trades from Alpaca order history before every cycle
        // This ensures the DB reflects Alpaca's actual positions (self-healing)
        if (!$dryRun) {
            try {
                $this->equityService->syncLiveTradesFromAlpaca($this->alpacaService);
            } catch (\Exception $e) {
                \Log::warning("Reconciliation failed: " . $e->getMessage());
            }
        }

        $account = null;
        $positions = [];
        try {
            $account = $this->alpacaService->getAccount();
            $positions = $this->alpacaService->getPositions();
        } catch (\Exception $e) {
            \Log::warning("Failed to fetch account/positions: " . $e->getMessage());
        }

        $tickers = $this->strategyService->getAllTickers();
        $results = [
            'total' => 0,
            'buys' => [],
            'sells' => [],
            'errors' => []
        ];

        // Determine available cash (buying power or uninvested cash)
        $buyingPower = floatval($account['buying_power'] ?? 0);
        $accountEquity = floatval($account['equity'] ?? 100000);
        $invested = 0;
        if ($positions !== null && is_array($positions)) {
            foreach ($positions as $pos) {
                $invested += floatval($pos['market_value'] ?? 0);
            }
        }
        $availableCash = max(0, $accountEquity - $invested);
        $availableCash = min($availableCash, $buyingPower);

        // Pass 1: process exits and collect buy signals
        $buySignals = [];
        foreach ($tickers as $ticker) {
            if (($ticker['symbol'] ?? '') === 'BLENDED') {
                continue;
            }
            $sym = $ticker['symbol'];
            try {
                $result = $this->executeForTicker($sym, $account, $positions);
                $results['total']++;
                if ($result === 'buy') {
                    $buySignals[] = $sym;
                } elseif ($result === 'sell') {
                    $results['sells'][] = $sym;
                }
            } catch (\Exception $e) {
                \Log::error("Trade execution failed for $sym: " . $e->getMessage());
                $results['errors'][] = ['symbol' => $sym, 'error' => $e->getMessage()];
            }
        }

        // Pass 2: MTF-style rebalance — equal-weight every in-play ticker
        // (held positions + this cycle's buy signals) toward equity/N.
        // Overweight holdings are trimmed to fund new entries, so capital
        // rotates instead of getting stranded in one name.
        if (!empty($buySignals)) {
            $this->rebalanceEqualWeight($accountEquity, $buySignals, $positions, $results);
        }

        // Pass 3 (override only): if cash remains stranded, force-check entry
        // conditions for tickers already in position and deploy idle cash.
        if ($override && $availableCash > 0) {
            $this->executeManualOverride($availableCash, $results);
        }

        return $results;
    }

    /**
     * MTF-style rotation for the CHAND trio.
     *
     * In-play tickers (held positions + tickers with a buy signal this cycle)
     * are sized toward equity/N each. Overweight held tickers are trimmed to
     * fund underweight entries, so the account rotates instead of being
     * permanently parked in one symbol.
     */
    private function rebalanceEqualWeight(float $accountEquity, array $buySignals, ?array $positions, array &$results): void
    {
        if ($accountEquity <= 0) {
            return;
        }

        $held = [];
        foreach ($positions ?? [] as $pos) {
            $held[$pos['symbol']] = floatval($pos['market_value'] ?? 0);
        }

        $inPlay = array_values(array_unique(array_merge(array_keys($held), $buySignals)));
        if (count($inPlay) < 1) {
            return;
        }

        $perPosition = $accountEquity / count($inPlay);
        \Log::info("Rebalance: " . count($inPlay) . " in-play tickers (" . implode(',', $inPlay) . "), target \$" . round($perPosition, 2) . " each");

        // 1) Trim overweight held tickers down to the equal-weight target.
        foreach ($inPlay as $sym) {
            $currentValue = $held[$sym] ?? 0;
            if ($currentValue <= $perPosition) {
                continue;
            }
            $excess = $currentValue - $perPosition;
            $price = $this->getCurrentPrice($sym);
            if (!$price) {
                continue;
            }
            $sellQty = intval($excess / $price);
            if ($sellQty < 1) {
                continue;
            }
            if ($this->rebalanceTrim($sym, $sellQty)) {
                $results['sells'][] = "$sym (rebalance trim $sellQty)";
            }
        }

        // 2) Buy underweight in-play tickers that signaled this cycle.
        foreach ($buySignals as $sym) {
            $currentValue = $held[$sym] ?? 0;
            $needed = $perPosition - $currentValue;
            if ($needed <= 0) {
                continue;
            }
            $price = $this->getCurrentPrice($sym);
            if (!$price) {
                continue;
            }
            $buyQty = intval($needed / $price);
            if ($buyQty < 1) {
                continue;
            }
            if ($this->rebalanceBuy($sym, $buyQty, $price)) {
                $results['buys'][] = $sym;
            }
        }
    }

    /**
     * Partial sell for rebalance trims. Reduces the open trade's quantity; a
     * closed SELL trade records the trimmed portion so reconciliation skips it.
     */
    private function rebalanceTrim(string $symbol, int $qty): bool
    {
        $openTrade = LiveTrade::where('symbol', $symbol)->where('status', 'open')->first();
        if (!$openTrade) {
            return false;
        }
        $currentQty = intval($openTrade->quantity ?? 0);
        if ($qty >= $currentQty) {
            $qty = $currentQty;
        }
        if ($qty < 1) {
            return false;
        }

        if ($this->dryRun) {
            \Log::info("DRY RUN REBALANCE TRIM $symbol: qty=$qty, newQty=" . ($currentQty - $qty) . " (no order placed)");
            return true;
        }

        try {
            $price = $this->getCurrentPrice($symbol);
            $order = $this->alpacaService->placeOrder($symbol, $qty, 'sell');
            $fillPrice = floatval($order['filled_avg_price'] ?? $price ?? 0);
            $orderId = $order['id'] ?? null;

            $entryPrice = floatval($openTrade->entry_price ?? 0);
            $pnlDollar = ($fillPrice - $entryPrice) * $qty;
            $pnlPct = $entryPrice > 0 ? (($fillPrice - $entryPrice) / $entryPrice) * 100 : 0;

            $newQty = $currentQty - $qty;
            if ($newQty <= 0) {
                $openTrade->update([
                    'exit_price' => $fillPrice,
                    'exit_at' => now(),
                    'status' => 'closed',
                    'pnl_dollar' => $pnlDollar,
                    'pnl_pct' => $pnlPct,
                    'alpaca_order_id' => $orderId,
                    'strategy_signal' => 'CHANDELIER_REBALANCE_TRIM',
                ]);
            } else {
                $openTrade->update(['quantity' => $newQty]);
                LiveTrade::create([
                    'ticker_id' => $openTrade->ticker_id,
                    'symbol' => $symbol,
                    'side' => 'SELL',
                    'quantity' => $qty,
                    'entry_price' => $entryPrice,
                    'exit_price' => $fillPrice,
                    'entry_at' => $openTrade->entry_at,
                    'exit_at' => now(),
                    'status' => 'closed',
                    'pnl_dollar' => $pnlDollar,
                    'pnl_pct' => $pnlPct,
                    'alpaca_order_id' => $orderId,
                    'strategy_signal' => 'CHANDELIER_REBALANCE_TRIM',
                ]);
            }
            \Log::info("REBALANCE TRIM $symbol: qty=$qty, fill=$fillPrice, newQty=$newQty");
            return true;
        } catch (\Exception $e) {
            \Log::error("Rebalance trim failed for $symbol: " . $e->getMessage());
            return false;
        }
    }

    /**
     * New entry for rebalance buys (equal-weight target).
     */
    private function rebalanceBuy(string $symbol, int $qty, float $price): bool
    {
        if ($this->dryRun) {
            \Log::info("DRY RUN REBALANCE BUY $symbol: qty=$qty, ~$price (no order placed)");
            return true;
        }

        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return false;
        }
        try {
            $order = $this->alpacaService->placeOrder($symbol, $qty, 'buy');
            $fillPrice = floatval($order['filled_avg_price'] ?? $price);
            $orderId = $order['id'] ?? null;
            LiveTrade::create([
                'ticker_id' => $ticker->id,
                'symbol' => $symbol,
                'side' => 'BUY',
                'quantity' => $qty,
                'entry_price' => $fillPrice,
                'entry_at' => now(),
                'status' => 'open',
                'alpaca_order_id' => $orderId,
                'strategy_signal' => 'CHANDELIER_REBALANCE_ENTRY',
            ]);
            \Log::info("REBALANCE BUY $symbol: qty=$qty, fill=$fillPrice");
            return true;
        } catch (\Exception $e) {
            \Log::error("Rebalance buy failed for $symbol: " . $e->getMessage());
            return false;
        }
    }

    /**
     * Manual buy for testing
     */
    public function manualBuy($symbol, $qty = null)
    {
        if ($symbol === 'BLENDED') {
            throw new \Exception("Cannot trade BLENDED ticker");
        }
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            throw new \Exception("Ticker {$symbol} not found");
        }

        $account = $this->alpacaService->getAccount();
        $accountEquity = $account['equity'] ?? 100000;

        if (!$qty) {
            // Use allocation weight to calculate qty
            $allocationWeight = ($ticker->allocation_weight ?? 33.33) / 100;
            $allocatedCapital = $accountEquity * $allocationWeight;
            // Use average price estimate
            $qty = max(1, intval($allocatedCapital / 150));
        }

        $order = $this->alpacaService->placeOrder($symbol, $qty, 'buy');

        LiveTrade::create([
            'ticker_id' => $ticker->id,
            'symbol' => $symbol,
            'side' => 'BUY',
            'quantity' => $qty,
            'entry_price' => 0,
            'entry_at' => now(),
            'status' => 'open',
            'alpaca_order_id' => $order['id'] ?? null,
            'strategy_signal' => 'MANUAL_BUY',
        ]);

        \Log::info("MANUAL BUY {$symbol} qty={$qty}");
        return ['success' => true, 'symbol' => $symbol, 'qty' => $qty, 'order_id' => $order['id'] ?? null];
    }

    /**
     * Manual sell for testing
     */
    public function manualSell($symbol, $qty = null)
    {
        if ($symbol === 'BLENDED') {
            throw new \Exception("Cannot trade BLENDED ticker");
        }
        // For manual testing, qty is required or get from open position
        $sellQty = $qty;

        if (!$sellQty) {
            try {
                $position = PositionCache::where('symbol', $symbol)->first();
                if ($position) {
                    $sellQty = $position->qty;
                }
            } catch (\Exception $e) {
                // PositionCache table may not exist
                \Log::debug("PositionCache lookup failed: " . $e->getMessage());
            }
        }

        // Fallback to LiveTrade if PositionCache unavailable
        if (!$sellQty) {
            try {
                $openTrade = LiveTrade::where('symbol', $symbol)
                    ->where('status', 'open')
                    ->first();
                if ($openTrade) {
                    $sellQty = $openTrade->quantity;
                }
            } catch (\Exception $e) {
                \Log::debug("LiveTrade lookup failed: " . $e->getMessage());
            }
        }

        if (!$sellQty) {
            throw new \Exception("No quantity specified and no position found for {$symbol}");
        }

        $order = $this->alpacaService->placeOrder($symbol, $sellQty, 'sell');

        try {
            $position = PositionCache::where('symbol', $symbol)->first();
            if ($position) {
                $position->delete();
            }
        } catch (\Exception $e) {
            \Log::debug("Could not delete position: " . $e->getMessage());
        }

        try {
            LiveTrade::where('symbol', $symbol)
                ->where('status', 'open')
                ->update([
                    'exit_price' => 0,
                    'exit_at' => now(),
                    'status' => 'closed',
                ]);
        } catch (\Exception $e) {
            \Log::debug("Could not update live trades: " . $e->getMessage());
        }

        \Log::info("MANUAL SELL {$symbol} qty={$sellQty}");
        return ['success' => true, 'symbol' => $symbol, 'qty' => $sellQty, 'order_id' => $order['id'] ?? null];
    }

    public function forceTestAllTickers($qty = 1)
    {
        $tickers = $this->strategyService->getAllTickers();
        $results = [
            'total' => 0,
            'buys' => [],
            'sells' => [],
            'errors' => [],
        ];

        foreach ($tickers as $ticker) {
            $symbol = $ticker['symbol'];
            if ($symbol === 'BLENDED') {
                continue;
            }
            $results['total']++;
            try {
                $buy = $this->alpacaService->placeOrder($symbol, $qty, 'buy');
                \Log::info("FORCE-TEST BUY {$symbol} qty={$qty} order=" . ($buy['id'] ?? 'n/a'));
                $results['buys'][] = $symbol;

                LiveTrade::create([
                    'ticker_id' => Ticker::where('symbol', $symbol)->first()?->id,
                    'symbol' => $symbol,
                    'side' => 'BUY',
                    'quantity' => $qty,
                    'entry_price' => 0,
                    'entry_at' => now(),
                    'status' => 'open',
                    'alpaca_order_id' => $buy['id'] ?? null,
                    'strategy_signal' => 'FORCE_TEST',
                ]);

                $sell = $this->alpacaService->placeOrder($symbol, $qty, 'sell');
                \Log::info("FORCE-TEST SELL {$symbol} qty={$qty} order=" . ($sell['id'] ?? 'n/a'));
                $results['sells'][] = $symbol;

                LiveTrade::where('symbol', $symbol)
                    ->where('strategy_signal', 'FORCE_TEST')
                    ->where('status', 'open')
                    ->update([
                        'exit_price' => 0,
                        'exit_at' => now(),
                        'status' => 'closed',
                    ]);
            } catch (\Exception $e) {
                \Log::error("Force-test failed for {$symbol}: " . $e->getMessage());
                $results['errors'][] = ['symbol' => $symbol, 'error' => $e->getMessage()];
            }
        }

        return $results;
    }

    public function executeForTicker($symbol, $account = null, $positions = null)
    {
        if (!$this->validateStrategySync($symbol)) {
            \Log::error("$symbol: TRADE BLOCKED - Strategy validation failed");
            return null;
        }

        $strategy = $this->strategyService->getStrategyForSymbol($symbol);
        if (!$strategy || !$strategy['params']) {
            \Log::warning("No strategy params found for $symbol");
            return null;
        }

        $params = $strategy['params'];

        $currentPrice = $this->getCurrentPrice($symbol);
        if (!$currentPrice) {
            \Log::warning("No current price available for $symbol, skipping signal");
            return null;
        }

        $signal = $this->computeChandelierSignal($symbol, $params);

        if ($signal === 'sell') {
            return $this->handleSellSignal($symbol, $currentPrice);
        } elseif ($signal === 'buy') {
            // Return buy signal — order placement is handled by handlePooledEntries
            return 'buy';
        }

        return null;
    }

    /**
     * Pool cash among tickers with buy signals.
     * Distributes available cash equally among all entering tickers.
     */
    private function handlePooledEntries(array $symbols, float $availableCash, $account = null, $positions = null): array
    {
        $placed = [];
        $perTicker = $availableCash / count($symbols);

        foreach ($symbols as $sym) {
            try {
                $ticker = Ticker::where('symbol', $sym)->first();
                if (!$ticker) {
                    \Log::warning("Pooled entry: ticker $sym not found");
                    continue;
                }

                $currentPrice = $this->getCurrentPrice($sym);
                if (!$currentPrice) {
                    \Log::warning("Pooled entry: no price for $sym");
                    continue;
                }

                $qty = intval($perTicker / $currentPrice);
                if ($qty < 1) {
                    \Log::info("Pooled entry: $perTicker insufficient for 1 share of $sym at $currentPrice");
                    continue;
                }

                $order = $this->alpacaService->placeOrder($sym, $qty, 'buy');
                $fillPrice = floatval($order['filled_avg_price'] ?? $currentPrice);
                $orderId = $order['id'] ?? null;

                // If ticker already has an open position, add to existing qty
                $openTrade = LiveTrade::where('symbol', $sym)->where('status', 'open')->first();
                if ($openTrade) {
                    $oldQty = $openTrade->quantity;
                    $oldPrice = $openTrade->entry_price;
                    $newQty = $oldQty + $qty;
                    // Recalculate entry_price as weighted average of existing + new fill
                    $weightedPrice = ($oldPrice * $oldQty + $fillPrice * $qty) / $newQty;
                    $openTrade->update([
                        'quantity' => $newQty,
                        'entry_price' => round($weightedPrice, 4),
                    ]);
                } else {
                    LiveTrade::create([
                        'ticker_id' => $ticker->id,
                        'symbol' => $sym,
                        'side' => 'BUY',
                        'quantity' => $qty,
                        'entry_price' => $fillPrice,
                        'entry_at' => now(),
                        'status' => 'open',
                        'alpaca_order_id' => $orderId,
                        'strategy_signal' => 'CHANDELIER_ENTRY',
                    ]);
                }

                \Log::info("Pooled BUY $sym: qty=$qty, fillPrice=$fillPrice, allocated=$perTicker");
                $placed[] = $sym;
            } catch (\Exception $e) {
                \Log::error("Pooled entry failed for $sym: " . $e->getMessage());
            }
        }

        return $placed;
    }

    /**
     * Manual override: force-check entry conditions for all tickers (including
     * those already in position) and deploy idle cash into qualifying ones.
     */
    private function executeManualOverride(float $availableCash, array &$results): void
    {
        if ($availableCash <= 0) {
            \Log::info("Override: no cash available ($availableCash), nothing to deploy");
            return;
        }

        $eligible = [];
        $tickers = $this->strategyService->getAllTickers();

        foreach ($tickers as $ticker) {
            $sym = $ticker['symbol'] ?? '';
            if ($sym === 'BLENDED') {
                continue;
            }

            $strategy = $this->strategyService->getStrategyForSymbol($sym);
            if (!$strategy || !$strategy['params']) {
                continue;
            }

            $params = $strategy['params'];
            $ohlc = $this->getOhlcBars($sym);
            $period = intval($params['chandelier_period'] ?? 18);
            if (empty($ohlc) || count($ohlc) < $period + 1) {
                continue;
            }

            $entryMult = $params['chandelier_entry_mult'] ?? null;
            if ($entryMult === null) {
                $eligible[] = $sym;
                continue;
            }

            $atr = $this->calculateATR($ohlc, $period);
            if ($atr === null) {
                continue;
            }

            $rollingHigh = max(array_column(array_slice($ohlc, -$period), 'high'));
            $entryLevel = $rollingHigh - $atr * floatval($entryMult);

            $livePrices = $this->alpacaService->getLatestPrices([$sym]);
            $currentPrice = $livePrices[$sym] ?? $this->getCurrentPrice($sym);
            if ($currentPrice === null) {
                $last = $ohlc[count($ohlc) - 1];
                $currentPrice = $last['close'];
            }

            if ($currentPrice > $entryLevel) {
                $eligible[] = $sym;
                \Log::info("Override: $sym eligible (price=$currentPrice > entry=$entryLevel)");
            } else {
                \Log::debug("Override: $sym not eligible (price=$currentPrice <= entry=$entryLevel)");
            }
        }

        if ($eligible && $availableCash > 0) {
            $bought = $this->handlePooledEntries($eligible, $availableCash);
            $results['buys'] = array_merge($results['buys'], $bought);
            $results['total'] += count($bought);
        }
    }

    /**
     * Get current price from latest bar in database
     */
    private function getCurrentPrice($symbol)
    {
        try {
            $bar = \DB::table('tbl_etf_tickers_1hour')
                ->join('tbl_etf_tickers', 'tbl_etf_tickers_1hour.ticker_id', '=', 'tbl_etf_tickers.id')
                ->where('tbl_etf_tickers.symbol', $symbol)
                ->orderBy('tbl_etf_tickers_1hour.timestamp', 'desc')
                ->select('tbl_etf_tickers_1hour.close')
                ->first();

            if ($bar) {
                return floatval($bar->close);
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch from tbl_etf_tickers_1hour: " . $e->getMessage());
        }

        return null;
    }

    /**
     * Handle sell signal
     */
    private function handleSellSignal($symbol, $currentPrice)
    {
        $openTrade = LiveTrade::where('symbol', $symbol)
            ->where('status', 'open')
            ->first();

        if (!$openTrade) {
            \Log::info("SELL signal for $symbol but no open position");
            return null;
        }

        $qty = $openTrade->quantity;

        if ($this->dryRun) {
            \Log::info("DRY RUN SELL $symbol: qty=$qty, ~$currentPrice (no order placed)");
            return 'sell';
        }

        try {
            $order = $this->alpacaService->placeOrder($symbol, $qty, 'sell');

            $fillPrice = floatval($order['filled_avg_price'] ?? $currentPrice);
            $orderId = $order['id'] ?? null;

            $pnlDollar = ($fillPrice - $openTrade->entry_price) * $qty;
            $pnlPct = $openTrade->entry_price > 0
                ? ($fillPrice - $openTrade->entry_price) / $openTrade->entry_price
                : 0;

            LiveTrade::where('symbol', $symbol)->where('status', 'open')->update([
                'exit_price' => $fillPrice,
                'exit_at' => now(),
                'status' => 'closed',
                'pnl_dollar' => $pnlDollar,
                'pnl_pct' => $pnlPct,
                'alpaca_order_id' => $orderId,
                'strategy_signal' => 'CHANDELIER_EXIT',
            ]);

            \Log::info("SELL signal for $symbol: qty={$qty}, fillPrice=\${$fillPrice}, PnL=\${$pnlDollar}, orderId={$orderId}");
            return 'sell';
        } catch (\Exception $e) {
            \Log::error("Failed to place sell order for $symbol: " . $e->getMessage());
            return null;
        }
    }

    /**
     * Get position for symbol from Alpaca
     */
    private function getPositionForSymbol($symbol)
    {
        try {
            $positions = $this->alpacaService->getPositions();
            foreach ($positions as $pos) {
                if ($pos['symbol'] === $symbol) {
                    return $pos;
                }
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch positions from Alpaca: " . $e->getMessage());
        }
        return null;
    }

    /**
     * Compute Chandelier Exit signal for live trading.
     *
     * - No position → BUY (always re-enter)
     * - In position → check stop: close < (highest_high_since_entry - ATR × mult)
     *
     * Returns 'buy', 'sell', or null (hold).
     */
    /**
     * Compute linear regression slope over last $window bars of close prices
     * using ordinary least squares. Returns slope in $/bar.
     */
    private function linearRegSlope($ohlc, $window)
    {
        $n = count($ohlc);
        if ($n < $window) {
            return null;
        }
        $closes = array_column(array_slice($ohlc, -$window), 'close');
        $x_sum = 0;
        $y_sum = 0;
        $xy_sum = 0;
        $x2_sum = 0;
        $w = $window;
        for ($i = 0; $i < $w; $i++) {
            $x = $i;
            $y = $closes[$i];
            $x_sum += $x;
            $y_sum += $y;
            $xy_sum += $x * $y;
            $x2_sum += $x * $x;
        }
        $denom = $w * $x2_sum - $x_sum * $x_sum;
        if ($denom == 0) {
            return null;
        }
        return ($w * $xy_sum - $x_sum * $y_sum) / $denom;
    }

    public function computeChandelierSignal($symbol, $params)
    {
        $period = intval($params['chandelier_period'] ?? 18);
        $mult = floatval($params['chandelier_mult'] ?? 3.0);
        $entryMult = isset($params['chandelier_entry_mult']) ? floatval($params['chandelier_entry_mult']) : null;
        $regWindow = isset($params['reg_slope_window']) ? intval($params['reg_slope_window']) : null;
        $regThreshold = isset($params['reg_slope_threshold']) ? floatval($params['reg_slope_threshold']) : null;
        $regType = $params['reg_slope_type'] ?? null;

        $ohlc = $this->getOhlcBars($symbol);
        if (empty($ohlc) || count($ohlc) < $period + 1) {
            \Log::warning("$symbol: Not enough OHLC data for Chandelier signal");
            return null;
        }

        // Use live price from Alpaca first, then DB bars, then daily close
        $livePrices = $this->alpacaService->getLatestPrices([$symbol]);
        $currentPrice = $livePrices[$symbol] ?? null;
        if ($currentPrice === null) {
            $currentPrice = $this->getCurrentPrice($symbol);
        }
        if ($currentPrice === null) {
            $last = $ohlc[count($ohlc) - 1];
            $currentPrice = $last['close'];
        }

        $openTrade = LiveTrade::where('symbol', $symbol)
            ->where('status', 'open')
            ->first();

        if ($openTrade) {
            // We have a position — check Chandelier stop
            $entryDate = $openTrade->entry_at;

            // Get bars since entry for highest high
            $barsSinceEntry = [];
            foreach ($ohlc as $bar) {
                if ($bar['timestamp'] >= $entryDate) {
                    $barsSinceEntry[] = $bar;
                }
            }

            if (empty($barsSinceEntry)) {
                \Log::warning("$symbol: No bars since entry date $entryDate");
                return null;
            }

            $highestHigh = max(array_column($barsSinceEntry, 'high'));

            // ATR: need last $period bars
            $atr = $this->calculateATR($ohlc, $period);
            if ($atr === null) {
                return null;
            }

            $stopLevel = $highestHigh - $atr * $mult;

            \Log::debug("$symbol Chandelier check: in position, high=$highestHigh, ATR=$atr, stop=$stopLevel, price=$currentPrice");

            if ($currentPrice < $stopLevel) {
                \Log::info("$symbol SELL SIGNAL (Chandelier stop): price=$currentPrice < stop=$stopLevel");
                return 'sell';
            }

            // Regression exit check: exit when linear regression slope drops below threshold
            if ($regWindow !== null && $regThreshold !== null && $regType !== null) {
                $rawSlope = $this->linearRegSlope($ohlc, $regWindow);
                if ($rawSlope !== null) {
                    $normalized = null;
                    if ($regType === 'slope_atr' && $atr !== null && $atr > 0) {
                        $normalized = $rawSlope / $atr;
                    } elseif ($regType === 'slope_pct' && $currentPrice > 0) {
                        $normalized = ($rawSlope / $currentPrice) * 100;
                    } elseif ($regType === 'slope') {
                        $normalized = $rawSlope;
                    }
                    if ($normalized !== null && $normalized < $regThreshold) {
                        \Log::info("$symbol SELL SIGNAL (regression exit): slope=$rawSlope, normalized=$normalized < threshold=$regThreshold");
                        return 'sell';
                    }
                }
            }

            return null; // Hold
        }

        // No position — check entry conditions
        $lastClosed = LiveTrade::where('symbol', $symbol)
            ->where('status', 'closed')
            ->orderBy('exit_at', 'desc')
            ->first();

        if ($lastClosed && $lastClosed->exit_at && $lastClosed->exit_at->isToday()) {
            \Log::debug("$symbol: Skipping re-entry — exited today at " . $lastClosed->exit_at);
            return null;
        }

        if ($entryMult !== null) {
            // Chandelier entry filter: close > rolling_high - ATR * entry_mult
            $atr = $this->calculateATR($ohlc, $period);
            if ($atr === null) {
                return null;
            }
            $rollingHigh = max(array_column(array_slice($ohlc, -$period), 'high'));
            $entryLevel = $rollingHigh - $atr * $entryMult;
            \Log::debug("$symbol: Chandelier entry check: entryLevel=$entryLevel, price=$currentPrice");
            if ($currentPrice <= $entryLevel) {
                return null; // Price not above entry level
            }
        }

        \Log::info("$symbol BUY SIGNAL (Chandelier re-entry): no open position");
        return 'buy';
    }

}
