<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\LiveTrade;
use App\Models\PositionCache;
use App\Models\IntraDayPrice;

class TradeExecutorService
{
    private $alpacaService;
    private $strategyService;
    private $priceAcquisitionService;

    public function __construct(AlpacaService $alpaca, StrategyService $strategy, PriceAcquisitionService $priceAcquisition)
    {
        $this->alpacaService = $alpaca;
        $this->strategyService = $strategy;
        $this->priceAcquisitionService = $priceAcquisition;
    }

    public function executeForAllTickers()
    {
        // Fetch fresh prices for all tickers before executing trades
        try {
            $this->priceAcquisitionService->fetchLatestPrices();
            \Log::info("Fetched latest prices for all tickers");
        } catch (\Exception $e) {
            \Log::warning("Failed to fetch latest prices: " . $e->getMessage());
        }

        $tickers = $this->strategyService->getAllTickers();
        $results = [
            'total' => 0,
            'buys' => [],
            'sells' => [],
            'errors' => []
        ];

        foreach ($tickers as $ticker) {
            try {
                $result = $this->executeForTicker($ticker['symbol']);
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

    public function executeForTicker($symbol)
    {
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

        // Build price series: bars + intra_day prices combined
        $closes = $this->getPriceClosesForSignal($symbol);
        if (empty($closes) || count($closes) < 26) {
            // Need at least 26 periods for MACD calculation
            \Log::warning("$symbol: Not enough price data for signal (have " . count($closes) . ", need 26+)");
            return null;
        }

        $signal = $this->computeSignal($closes, $params, $symbol);

        if ($signal === 0) {
            return null;
        }

        if ($signal === 1) {
            return $this->handleBuySignal($symbol, $currentPrice);
        } elseif ($signal === -1) {
            return $this->handleSellSignal($symbol, $currentPrice);
        }

        return null;
    }

    /**
     * Read hourly bars from optimizer's SQLite database
     * Returns array of close prices in chronological order
     */
    private function getBarsFromSQLite($symbol)
    {
        $dbPath = base_path('../optimizer/optimized_params/strategy_params.db');
        if (!file_exists($dbPath)) {
            \Log::debug("SQLite database not found at {$dbPath}");
            return [];
        }

        try {
            $conn = new \SQLite3($dbPath);

            // Get ticker_id from SQLite tickers table
            $stmt = $conn->prepare('SELECT id FROM tickers WHERE symbol = ?');
            $stmt->bindValue(1, $symbol, SQLITE3_TEXT);
            $result = $stmt->execute();
            $ticker = $result->fetchArray(SQLITE3_ASSOC);

            if (!$ticker) {
                \Log::debug("Ticker {$symbol} not found in SQLite");
                $conn->close();
                return [];
            }

            $tickerId = $ticker['id'];

            // Fetch all bars for this ticker, ordered by timestamp
            $stmt = $conn->prepare('SELECT close FROM bars WHERE ticker_id = ? ORDER BY timestamp ASC');
            $stmt->bindValue(1, $tickerId, SQLITE3_INTEGER);
            $result = $stmt->execute();

            $closes = [];
            while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
                $closes[] = floatval($row['close']);
            }

            $conn->close();

            if (!empty($closes)) {
                \Log::debug("{$symbol}: Loaded " . count($closes) . " bars from SQLite");
            }

            return $closes;
        } catch (\Exception $e) {
            \Log::debug("Could not fetch bars from SQLite for {$symbol}: " . $e->getMessage());
            return [];
        }
    }

    /**
     * Get price series from bars + intra_day prices, sorted chronologically
     */
    private function getPriceClosesForSignal($symbol)
    {
        $closes = [];

        // Get bars (historical hourly data)
        try {
            $timeframe = env('TRADING_TIMEFRAME', '1Hour');
            $end = date('Y-m-d');
            $start = date('Y-m-d', strtotime('-60 days'));
            $bars = $this->alpacaService->getBars($symbol, $timeframe, $start, $end);

            if (!empty($bars)) {
                // Sort by timestamp ascending
                usort($bars, function ($a, $b) {
                    return strtotime($a['t'] ?? $a['timestamp'] ?? 0) <=> strtotime($b['t'] ?? $b['timestamp'] ?? 0);
                });

                foreach ($bars as $bar) {
                    $closes[] = floatval($bar['c'] ?? $bar['close'] ?? 0);
                }
                \Log::debug("$symbol: Loaded " . count($bars) . " bars from Alpaca");
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch bars for $symbol: " . $e->getMessage());
        }

        // Add intra_day prices for today (after the last bar)
        try {
            $today = date('Y-m-d');
            $intraDayPrices = IntraDayPrice::where('symbol', $symbol)
                ->whereDate('price_time', $today)
                ->orderBy('price_time', 'asc')
                ->get(['close', 'price_time'])
                ->toArray();

            foreach ($intraDayPrices as $price) {
                $closes[] = floatval($price['close'] ?? 0);
            }

            if (!empty($intraDayPrices)) {
                \Log::debug("$symbol: Added " . count($intraDayPrices) . " intra-day prices for today");
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch intra-day prices for $symbol: " . $e->getMessage());
        }

        return $closes;
    }

    /**
     * Get current price: bars first, then intra_day, then skip
     */
    private function getCurrentPrice($symbol)
    {
        // Try to get from bars data (most recent close) via ticker_id FK
        try {
            $bar = \DB::table('bars')
                ->join('tickers', 'bars.ticker_id', '=', 'tickers.id')
                ->where('tickers.symbol', $symbol)
                ->orderBy('bars.timestamp', 'desc')
                ->select('bars.close')
                ->first();

            if ($bar) {
                return floatval($bar->close);
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch from bars: " . $e->getMessage());
        }

        // Fallback: Get latest intra_day price for today
        try {
            $today = date('Y-m-d');
            $intraday = IntraDayPrice::where('symbol', $symbol)
                ->whereDate('price_time', $today)
                ->orderBy('price_time', 'desc')
                ->first();

            if ($intraday) {
                return floatval($intraday->close);
            }
        } catch (\Exception $e) {
            \Log::debug("Could not fetch from intra_day_prices: " . $e->getMessage());
        }

        return null;
    }

    /**
     * Handle buy signal with position reconciliation
     */
    private function handleBuySignal($symbol, $currentPrice)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            \Log::warning("Ticker {$symbol} not found");
            return null;
        }

        $account = $this->alpacaService->getAccount();
        $accountEquity = $account['equity'] ?? 100000;
        $allocationWeight = ($ticker->allocation_weight ?? 33.33) / 100;
        $allocatedCapital = $accountEquity * $allocationWeight;

        // Get current position from Alpaca
        $alpacaPosition = $this->getPositionForSymbol($symbol);
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
        $qty = intval($remainingAllocation / $currentPrice);

        if ($qty < 1) {
            \Log::info("$symbol: Remaining allocation \${$remainingAllocation} too small for 1 share at \${$currentPrice}");
            return null;
        }

        try {
            $order = $this->alpacaService->placeOrder($symbol, $qty, 'buy');

            LiveTrade::create([
                'ticker_id' => $ticker->id,
                'symbol' => $symbol,
                'side' => 'BUY',
                'quantity' => $qty,
                'entry_price' => $currentPrice,
                'entry_at' => now(),
                'status' => 'open',
                'alpaca_order_id' => $order['id'] ?? null,
                'strategy_signal' => 'MACD_CROSS_BUY',
            ]);

            \Log::info("BUY signal for $symbol: qty={$qty}, price=\${$currentPrice}, allocation used=\${$remainingAllocation}");
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

            $pnlDollar = ($currentPrice - $openTrade->entry_price) * $qty;
            $pnlPct = ($currentPrice - $openTrade->entry_price) / $openTrade->entry_price;

            LiveTrade::where('symbol', $symbol)->where('status', 'open')->update([
                'exit_price' => $currentPrice,
                'exit_at' => now(),
                'status' => 'closed',
                'pnl_dollar' => $pnlDollar,
                'pnl_pct' => $pnlPct,
            ]);

            \Log::info("SELL signal for $symbol: qty={$qty}, price=\${$currentPrice}, PnL=\${$pnlDollar}");
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

    public function computeSignal($closes, $params, $symbol = null)
    {
        if (!$symbol || empty($closes) || count($closes) < 26) {
            return 0; // Not enough data
        }

        if (!$params) {
            \Log::warning("$symbol: No parameters available for signal calculation");
            return 0;
        }

        // Extract nightly-optimized parameters from database
        $macdFast = intval($params['macd_fast'] ?? 12);
        $macdSlow = intval($params['macd_slow'] ?? 26);
        $macdSignal = intval($params['macd_signal'] ?? 9);
        $smaShortPeriod = intval($params['sma_short'] ?? 20);
        $smaLongPeriod = intval($params['sma_long'] ?? 200);
        $bbPeriod = intval($params['bb_period'] ?? 20);
        $bbStdDev = floatval($params['bb_std'] ?? 2);

        // Validate we have enough data for longest period needed
        if (count($closes) < $smaLongPeriod) {
            return 0;
        }

        // Calculate indicators
        $smaShort = $this->calculateSMA($closes, $smaShortPeriod);
        $smaLong = $this->calculateSMA($closes, $smaLongPeriod);
        $macd = $this->calculateMACD($closes, $macdFast, $macdSlow, $macdSignal);
        $bb = $this->calculateBollingerBands($closes, $bbPeriod, $bbStdDev);

        $lastIdx = count($closes) - 1;
        $currentPrice = $closes[$lastIdx];
        $currentSmaShort = $smaShort[$lastIdx];
        $currentSmaLong = $smaLong[$lastIdx];
        $currentMacd = $macd['macd'][$lastIdx];
        $currentSignal = $macd['signal'][$lastIdx];
        $currentBBLower = $bb['lower'][count($bb['lower']) - 1];
        $currentBBUpper = $bb['upper'][count($bb['upper']) - 1];
        $currentBBMiddle = $bb['middle'][$lastIdx];

        // Get previous values for crossover detection
        $prevIdx = $lastIdx - 1;
        $prevMacd = $prevIdx >= 0 ? $macd['macd'][$prevIdx] : $currentMacd;
        $prevSignal = $prevIdx >= 0 ? $macd['signal'][$prevIdx] : $currentSignal;
        $prevPrice = $prevIdx >= 0 ? $closes[$prevIdx] : $currentPrice;

        // Check for MACD bullish crossover
        $macdBullishCross = ($currentMacd > $currentSignal) && ($prevMacd <= $prevSignal);

        // Check for MACD bearish crossover
        $macdBearishCross = ($currentMacd < $currentSignal) && ($prevMacd >= $prevSignal);

        // Check price vs SMAs
        $priceAboveSMAs = ($currentPrice > $currentSmaShort) && ($currentSmaShort > $currentSmaLong);

        // Check if price is near lower Bollinger Band (within 5% of lower band)
        $bbRange = $currentBBUpper - $currentBBLower;
        $priceNearLowerBB = $currentPrice < ($currentBBLower + $bbRange * 0.05);

        // Check if price breaks below lower BB
        $priceBelowBB = $currentPrice < $currentBBLower;
        $prevPriceAboveBB = $prevPrice >= $currentBBLower;
        $bbBreak = $priceBelowBB && $prevPriceAboveBB;

        \Log::debug("$symbol signal calc: params=(MACD:$macdFast/$macdSlow/$macdSignal, SMA:$smaShortPeriod/$smaLongPeriod, BB:$bbPeriod/$bbStdDev), price=$currentPrice, smaShort=$currentSmaShort, smaLong=$currentSmaLong, macd=$currentMacd, signal=$currentSignal, bbLower=$currentBBLower, bbUpper=$currentBBUpper");

        // BUY: MACD bullish + price above SMAs + near lower BB
        if ($macdBullishCross && $priceAboveSMAs && $priceNearLowerBB) {
            \Log::info("$symbol BUY SIGNAL: MACD bullish cross, price above SMAs, near lower BB");
            return 1;
        }

        // SELL: MACD bearish OR price breaks below BB
        if ($macdBearishCross || $bbBreak) {
            $reason = $macdBearishCross ? "MACD bearish cross" : "price breaks below BB";
            \Log::info("$symbol SELL SIGNAL: $reason");
            return -1;
        }

        return 0; // Hold
    }

    /**
     * Calculate MACD (Moving Average Convergence Divergence)
     * Returns array with 'macd' and 'signal' arrays
     */
    private function calculateMACD($data, $fastPeriod = 12, $slowPeriod = 26, $signalPeriod = 9)
    {
        $fastEMA = $this->calculateEMA($data, $fastPeriod);
        $slowEMA = $this->calculateEMA($data, $slowPeriod);

        // MACD line = fast EMA - slow EMA
        $macd = [];
        for ($i = 0; $i < count($data); $i++) {
            if ($fastEMA[$i] !== null && $slowEMA[$i] !== null) {
                $macd[$i] = $fastEMA[$i] - $slowEMA[$i];
            } else {
                $macd[$i] = null;
            }
        }

        // Signal line = EMA of valid MACD values
        // Filter to only values where MACD is calculated
        $validMACD = [];
        $validIndices = [];
        for ($i = 0; $i < count($macd); $i++) {
            if ($macd[$i] !== null) {
                $validMACD[] = $macd[$i];
                $validIndices[] = $i;
            }
        }

        $signalValues = $this->calculateEMA($validMACD, $signalPeriod);

        // Reconstruct signal array with nulls for invalid indices
        $signal = array_fill(0, count($macd), null);
        foreach ($validIndices as $idx => $origIdx) {
            if (isset($signalValues[$idx])) {
                $signal[$origIdx] = $signalValues[$idx];
            }
        }

        return [
            'macd' => $macd,
            'signal' => $signal,
        ];
    }

    private function calculateEMA($data, $period)
    {
        if (count($data) < $period) {
            return array_fill(0, count($data), null);
        }

        $alpha = 2 / ($period + 1);
        $ema = array_fill(0, count($data), null);

        // SMA for first value
        $sum = 0;
        for ($i = 0; $i < $period; $i++) {
            $sum += $data[$i];
        }
        $ema[$period - 1] = $sum / $period;

        // EMA from there
        for ($i = $period; $i < count($data); $i++) {
            $ema[$i] = $data[$i] * $alpha + $ema[$i - 1] * (1 - $alpha);
        }

        return $ema;
    }

    private function calculateSMA($data, $period)
    {
        $sma = array_fill(0, count($data), null);

        for ($i = $period - 1; $i < count($data); $i++) {
            $sum = 0;
            for ($j = $i - $period + 1; $j <= $i; $j++) {
                $sum += $data[$j];
            }
            $sma[$i] = $sum / $period;
        }

        return $sma;
    }

    private function calculateBollingerBands($data, $period, $stdDev)
    {
        $sma = $this->calculateSMA($data, $period);
        $upper = [];
        $lower = [];

        for ($i = $period - 1; $i < count($data); $i++) {
            if ($sma[$i] === null) {
                $upper[] = null;
                $lower[] = null;
                continue;
            }

            // Calculate standard deviation
            $sumSq = 0;
            for ($j = $i - $period + 1; $j <= $i; $j++) {
                $sumSq += pow($data[$j] - $sma[$i], 2);
            }
            $std = sqrt($sumSq / $period);

            $upper[] = $sma[$i] + ($std * $stdDev);
            $lower[] = $sma[$i] - ($std * $stdDev);
        }

        return [
            'upper' => $upper,
            'lower' => $lower,
            'middle' => $sma
        ];
    }
}
