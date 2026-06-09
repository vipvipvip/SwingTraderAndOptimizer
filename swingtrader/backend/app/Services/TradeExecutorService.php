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

    public function __construct(AlpacaService $alpaca, StrategyService $strategy)
    {
        $this->alpacaService = $alpaca;
        $this->strategyService = $strategy;
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

    public function executeForAllTickers()
    {
        // Fetch account and positions ONCE for all tickers (reduce Alpaca calls)
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

        foreach ($tickers as $ticker) {
            if (($ticker['symbol'] ?? '') === 'BLENDED') {
                continue;
            }
            try {
                $result = $this->executeForTicker($ticker['symbol'], $account, $positions);
                $results['total']++;
                if ($result === 'buy') {
                    $results['buys'][] = $ticker['symbol'];
                } elseif ($result === 'sell') {
                    $results['sells'][] = $ticker['symbol'];
                }
            } catch (\Exception $e) {
                \Log::error("Trade execution failed for {$ticker['symbol']}: " . $e->getMessage());
                $results['errors'][] = [
                    'symbol' => $ticker['symbol'],
                    'error' => $e->getMessage()
                ];
            }
        }

        return $results;
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
        // CRITICAL: Validate strategy is in sync before trading
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

        // Get current price: primary from bars, fallback to intra_day_prices
        $currentPrice = $this->getCurrentPrice($symbol);
        if (!$currentPrice) {
            \Log::warning("No current price available for $symbol, skipping signal");
            return null;
        }

        $signal = $this->computeChandelierSignal($symbol, $params);

        if ($signal === 'buy') {
            return $this->handleBuySignal($symbol, $currentPrice, $account, $positions);
        } elseif ($signal === 'sell') {
            return $this->handleSellSignal($symbol, $currentPrice);
        }

        return null;
    }

    /**
     * Get current price from latest bar in database
     */
    private function getCurrentPrice($symbol)
    {
        try {
            $bar = \DB::table('bars')
                ->join('tbl_etf_tickers', 'bars.ticker_id', '=', 'tbl_etf_tickers.id')
                ->where('tbl_etf_tickers.symbol', $symbol)
                ->orderBy('bars.timestamp', 'desc')
                ->select('bars.close')
                ->first();

            if ($bar) {
                return floatval($bar->close);
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch from bars: " . $e->getMessage());
        }

        return null;
    }

    /**
     * Handle buy signal with position reconciliation
     */
    private function handleBuySignal($symbol, $currentPrice, $account = null, $positions = null)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            \Log::warning("Ticker {$symbol} not found");
            return null;
        }

        // Use passed account data (fetched once in executeForAllTickers with retry logic)
        $accountEquity = $account['equity'] ?? 100000;
        $buyingPower = floatval($account['buying_power'] ?? 0);
        $allocationWeight = ($ticker->allocation_weight ?? 33.33) / 100;
        $allocatedCapital = $accountEquity * $allocationWeight;

        // Find position from passed positions array (should always be provided by executeForAllTickers)
        $alpacaPosition = null;
        if ($positions !== null && is_array($positions)) {
            foreach ($positions as $pos) {
                if ($pos['symbol'] === $symbol) {
                    $alpacaPosition = $pos;
                    break;
                }
            }
        }
        // Note: if positions not provided, alpacaPosition stays null (no fallback fetch)

        $amountInvested = 0;

        if ($alpacaPosition) {
            $amountInvested = floatval($alpacaPosition['market_value']);
            \Log::info("$symbol: Current position value: \${$amountInvested}");
        }

        // Calculate remaining allocation
        $remainingAllocation = $allocatedCapital - $amountInvested;

        if ($remainingAllocation <= 0) {
            \Log::info("$symbol: No remaining allocation (allocated: \${$allocatedCapital}, invested: \${$amountInvested})");
            return null;
        }

        // Calculate quantity to buy with remaining allocation
        $qtyFromAllocation = intval($remainingAllocation / $currentPrice);

        if ($qtyFromAllocation < 1) {
            \Log::info("$symbol: Remaining allocation \${$remainingAllocation} too small for 1 share at \${$currentPrice}");
            return null;
        }

        // Check available cash before placing order
        $costToExecute = $qtyFromAllocation * $currentPrice;
        if ($costToExecute > $buyingPower) {
            \Log::info("$symbol: Insufficient cash (need \${$costToExecute}, have \${$buyingPower})");
            return null;
        }

        try {
            $order = $this->alpacaService->placeOrder($symbol, $qtyFromAllocation, 'buy');

            LiveTrade::create([
                'ticker_id' => $ticker->id,
                'symbol' => $symbol,
                'side' => 'BUY',
                'quantity' => $qtyFromAllocation,
                'entry_price' => $currentPrice,
                'entry_at' => now(),
                'status' => 'open',
                'alpaca_order_id' => $order['id'] ?? null,
                'strategy_signal' => 'CHANDELIER_ENTRY',
            ]);

            \Log::info("BUY signal for $symbol: qty={$qtyFromAllocation}, price=\${$currentPrice}, allocation used=\${$remainingAllocation}");
            return 'buy';
        } catch (\Exception $e) {
            \Log::error("Failed to place buy order for $symbol: " . $e->getMessage());
            return null;
        }
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
    public function computeChandelierSignal($symbol, $params)
    {
        $period = intval($params['chandelier_period'] ?? 18);
        $mult = floatval($params['chandelier_mult'] ?? 3.0);
        $entryMult = isset($params['chandelier_entry_mult']) ? floatval($params['chandelier_entry_mult']) : null;

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
