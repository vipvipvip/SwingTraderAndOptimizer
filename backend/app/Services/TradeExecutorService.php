<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\LiveTrade;
use App\Models\PositionCache;

class TradeExecutorService
{
    private $alpacaService;
    private $strategyService;

    public function __construct(AlpacaService $alpaca, StrategyService $strategy)
    {
        $this->alpacaService = $alpaca;
        $this->strategyService = $strategy;
    }

    public function executeForAllTickers()
    {
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
                $buy = $this->alpacaService->placeOrder($symbol, 'buy', $qty);
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

                $sell = $this->alpacaService->placeOrder($symbol, 'sell', $qty);
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

        $timeframe = env('TRADING_TIMEFRAME', '1Hour');
        $end = date('Y-m-d');
        $start = date('Y-m-d', strtotime('-60 days'));
        $bars = $this->alpacaService->getBars($symbol, $timeframe, $start, $end);

        if (empty($bars)) {
            \Log::warning("No bars fetched for $symbol");
            return null;
        }

        $closes = array_column($bars, 'c');
        $signal = $this->computeSignal($closes, $params);

        if ($signal === 0) {
            return null;
        }

        $position = PositionCache::where('symbol', $symbol)->first();
        $currentPrice = end($closes);

        if ($signal === 1 && !$position) {
            $ticker = Ticker::where('symbol', $symbol)->first();
            $account = $this->alpacaService->getAccount();
            $accountEquity = $account['equity'] ?? 100000;
            $allocationWeight = ($ticker?->allocation_weight ?? 33.33) / 100;
            $allocatedCapital = $accountEquity * $allocationWeight;
            $qty = intval($allocatedCapital / $currentPrice);

            $order = $this->alpacaService->placeOrder($symbol, 'buy', $qty);

            LiveTrade::create([
                'ticker_id' => Ticker::where('symbol', $symbol)->first()?->id,
                'symbol' => $symbol,
                'side' => 'BUY',
                'quantity' => $qty,
                'entry_price' => $currentPrice,
                'entry_at' => now(),
                'status' => 'open',
                'alpaca_order_id' => $order['id'] ?? null,
                'strategy_signal' => 'MACD_CROSS_BUY',
            ]);

            \Log::info("BUY signal for $symbol at $currentPrice");
            return 'buy';
        } elseif ($signal === -1 && $position) {
            $qty = $position->qty;
            $order = $this->alpacaService->placeOrder($symbol, 'sell', $qty);

            $pnlDollar = ($currentPrice - $position->avg_entry_price) * $qty;
            $pnlPct = ($currentPrice - $position->avg_entry_price) / $position->avg_entry_price;

            LiveTrade::where('symbol', $symbol)->where('status', 'open')->update([
                'exit_price' => $currentPrice,
                'exit_at' => now(),
                'status' => 'closed',
                'pnl_dollar' => $pnlDollar,
                'pnl_pct' => $pnlPct,
            ]);

            $position->delete();

            \Log::info("SELL signal for $symbol at $currentPrice (PnL: $pnlDollar)");
            return 'sell';
        }

        return null;
    }

    public function computeSignal($closes, $params)
    {
        if (count($closes) < max(
            $params['macd_slow'] ?? 26,
            $params['sma_long'] ?? 200,
            $params['bb_period'] ?? 20
        )) {
            return 0;
        }

        $macdFast = $params['macd_fast'] ?? 12;
        $macdSlow = $params['macd_slow'] ?? 26;
        $macdSignal = $params['macd_signal'] ?? 9;
        $smaShort = $params['sma_short'] ?? 50;
        $smaLong = $params['sma_long'] ?? 200;
        $bbPeriod = $params['bb_period'] ?? 20;
        $bbStd = $params['bb_std'] ?? 2;

        // Calculate EMA for MACD
        $emaFast = $this->calculateEMA($closes, $macdFast);
        $emaSlow = $this->calculateEMA($closes, $macdSlow);

        // MACD line and signal line
        $macdLine = [];
        for ($i = 0; $i < count($emaFast); $i++) {
            if ($emaFast[$i] !== null && $emaSlow[$i] !== null) {
                $macdLine[] = $emaFast[$i] - $emaSlow[$i];
            }
        }

        if (count($macdLine) < $macdSignal) {
            return 0;
        }

        $signalLine = $this->calculateEMA($macdLine, $macdSignal);

        // MACD histogram
        $histogram = [];
        for ($i = 0; $i < count($macdLine); $i++) {
            if (isset($signalLine[$i]) && $signalLine[$i] !== null) {
                $histogram[] = $macdLine[$i] - $signalLine[$i];
            }
        }

        // Check for MACD cross (entry condition)
        if (count($histogram) < 2) {
            return 0;
        }

        $prevHistogram = $histogram[count($histogram) - 2];
        $currHistogram = $histogram[count($histogram) - 1];

        // BUY: histogram crosses above 0
        // SELL: histogram crosses below 0
        $macdCrossAbove = ($prevHistogram <= 0 && $currHistogram > 0);
        $macdCrossBelow = ($prevHistogram >= 0 && $currHistogram < 0);

        // Calculate SMA for uptrend filter
        $smaShortVals = $this->calculateSMA($closes, $smaShort);
        $smaLongVals = $this->calculateSMA($closes, $smaLong);

        $currentPrice = end($closes);
        $currentSmartShort = end($smaShortVals);
        $currentSmaLong = end($smaLongVals);

        // Uptrend filter: price > SMA50 > SMA200
        $inUptrend = ($currentPrice > $currentSmartShort) && ($currentSmartShort > $currentSmaLong);

        // Calculate Bollinger Bands
        $bb = $this->calculateBollingerBands($closes, $bbPeriod, $bbStd);
        $bbLower = end($bb['lower']);

        // Entry: MACD cross above 0 AND price near lower BB AND uptrend
        if ($macdCrossAbove && $currentPrice <= ($bbLower * 1.05) && $inUptrend) {
            return 1; // BUY
        }

        // Exit: MACD cross below 0
        if ($macdCrossBelow) {
            return -1; // SELL
        }

        return 0; // No signal
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
