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
        }

        $tickers = Ticker::whereEnabled(1)
            ->where('symbol', '!=', 'BLENDED')
            ->with('strategyParameter')
            ->get()
            ->map(function ($ticker) {
                return [
                    'symbol' => $ticker->symbol,
                    'id' => $ticker->id,
                    'allocation_weight' => (float) $ticker->allocation_weight,
                    'params' => $this->timestampsToNy(
                        $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null
                    ),
                ];
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

        return [
            'ticker' => $ticker->toArray(),
            'params' => $this->timestampsToNy(
                $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null
            ),
        ];
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
