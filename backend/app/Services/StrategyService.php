<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\StrategyParameter;
use App\Models\OptimizationHistory;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Carbon;

class StrategyService
{
    private function timestampsToNy($params)
    {
        if (!$params) return null;
        foreach (['created_at', 'updated_at'] as $field) {
            if (isset($params[$field])) {
                $params[$field] = Carbon::parse($params[$field], 'UTC')
                    ->setTimezone('America/New_York')
                    ->toDateTimeString();
            }
        }
        return $params;
    }

    private function getOhlcBars($symbol)
    {
        try {
            $rows = \DB::table('bars')
                ->join('tickers', 'bars.ticker_id', '=', 'tickers.id')
                ->where('tickers.symbol', $symbol)
                ->orderBy('bars.timestamp', 'asc')
                ->get(['bars.timestamp', 'bars.high', 'bars.low', 'bars.close']);

            if ($rows->isEmpty()) {
                return [];
            }

            $bars = [];
            foreach ($rows as $row) {
                $ts = $row->timestamp;
                if (date('G', strtotime($ts)) == 4 || date('G', strtotime($ts)) == 5) {
                    if (date('i', strtotime($ts)) == 0) {
                        $bars[] = [
                            'timestamp' => $ts,
                            'high' => floatval($row->high),
                            'low' => floatval($row->low),
                            'close' => floatval($row->close),
                        ];
                    }
                }
            }

            return $bars;
        } catch (\Exception $e) {
            \Log::error("$symbol: Error fetching OHLC bars: " . $e->getMessage());
            return [];
        }
    }

    private function calculateATR($ohlc, $period)
    {
        $n = count($ohlc);
        if ($n < $period + 1) {
            return null;
        }

        $trValues = [];
        for ($i = 1; $i < $n; $i++) {
            $high = $ohlc[$i]['high'];
            $low = $ohlc[$i]['low'];
            $prevClose = $ohlc[$i - 1]['close'];
            $trValues[] = max(
                $high - $low,
                abs($high - $prevClose),
                abs($low - $prevClose)
            );
        }

        $start = count($trValues) - $period;
        $sum = 0;
        for ($i = $start; $i < count($trValues); $i++) {
            $sum += $trValues[$i];
        }
        return $sum / $period;
    }

    private function addLiveMetrics(&$entry)
    {
        $symbol = $entry['symbol'];
        $params = $entry['params'] ?? null;
        if (!$params) {
            $entry['price'] = null;
            $entry['high'] = null;
            $entry['stop'] = null;
            $entry['atr'] = null;
            return;
        }

        $period = intval($params['macd_fast'] ?? 18);
        $mult = floatval($params['bb_std'] ?? 3.0);

        $ohlc = $this->getOhlcBars($symbol);
        if (empty($ohlc) || count($ohlc) < $period + 1) {
            $entry['price'] = null;
            $entry['high'] = null;
            $entry['stop'] = null;
            $entry['atr'] = null;
            return;
        }

        $last = $ohlc[count($ohlc) - 1];
        $entry['price'] = round($last['close'], 2);

        $atr = $this->calculateATR($ohlc, $period);
        if ($atr === null) {
            $entry['high'] = round($last['high'], 2);
            $entry['stop'] = null;
            $entry['atr'] = null;
            return;
        }

        $high = $last['high'];
        $stop = $high - $atr * $mult;

        $entry['high'] = round($high, 2);
        $entry['stop'] = round($stop, 2);
        $entry['atr'] = round($atr, 2);
    }

    public function getAllTickers()
    {
        $portfolio = Ticker::where('symbol', 'BLENDED')
            ->with('strategyParameter')
            ->first();

        $portfolioEntry = null;
        if ($portfolio && $portfolio->strategyParameter) {
            $params = $this->timestampsToNy($portfolio->strategyParameter->toArray());
            $params['is_portfolio'] = true;
            $portfolioEntry = [
                'symbol' => 'BLENDED',
                'id' => $portfolio->id,
                'allocation_weight' => 100,
                'params' => $params,
            ];
            $this->addLiveMetrics($portfolioEntry);
        }

        $tickers = Ticker::whereEnabled(1)
            ->where('symbol', '!=', 'BLENDED')
            ->with('strategyParameter')
            ->get()
            ->map(function ($ticker) {
                $entry = [
                    'symbol' => $ticker->symbol,
                    'id' => $ticker->id,
                    'allocation_weight' => (float) $ticker->allocation_weight,
                    'params' => $this->timestampsToNy(
                        $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null
                    ),
                ];
                $this->addLiveMetrics($entry);
                return $entry;
            })->toArray();

        $result = $portfolioEntry ? [$portfolioEntry, ...$tickers] : $tickers;
        return $result;
    }

    public function getStrategyForSymbol($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return null;
        }

        $entry = [
            'symbol' => $symbol,
            'ticker' => $ticker->toArray(),
            'params' => $this->timestampsToNy(
                $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null
            ),
        ];
        $this->addLiveMetrics($entry);

        return $entry;
    }

    public function getOptimizationHistory($symbol, $limit = 10)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return [];
        }

        return OptimizationHistory::where('ticker_id', $ticker->id)
            ->orderBy('run_date', 'desc')
            ->limit($limit)
            ->get()
            ->map(function ($row) {
                if (isset($row['run_date'])) {
                    $row['run_date'] = Carbon::parse($row['run_date'], 'UTC')
                        ->setTimezone('America/New_York')
                        ->toDateTimeString();
                }
                return $row;
            })
            ->toArray();
    }

    public function getSummary()
    {
        // Portfolio return from BLENDED strategy parameters
        $blended = Ticker::where('symbol', 'BLENDED')
            ->with('strategyParameter')
            ->first();
        $portfolioReturn = null;
        if ($blended && $blended->strategyParameter) {
            $portfolioReturn = (float) $blended->strategyParameter->total_return;
        }

        // SPY buy-and-hold return over the backtest period
        $spy = Ticker::where('symbol', 'SPY')->first();
        $sp500Return = null;
        if ($spy) {
            $firstBar = DB::table('bars')
                ->where('ticker_id', $spy->id)
                ->where('source', 'alpaca')
                ->orderBy('timestamp')
                ->first(['timestamp', 'close']);
            $lastBar = DB::table('bars')
                ->where('ticker_id', $spy->id)
                ->where('source', 'alpaca')
                ->orderByDesc('timestamp')
                ->first(['timestamp', 'close']);
            if ($firstBar && $lastBar && (float) $firstBar->close > 0) {
                $sp500Return = ((float) $lastBar->close - (float) $firstBar->close) / (float) $firstBar->close;
            }
        }

        return [
            'portfolio_return' => $portfolioReturn,
            'sp500_return' => $sp500Return,
        ];
    }

    public function getLatestOptimization($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return null;
        }

        return OptimizationHistory::where('ticker_id', $ticker->id)
            ->orderBy('run_date', 'desc')
            ->first();
    }
}
