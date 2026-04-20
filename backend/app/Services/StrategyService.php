<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\StrategyParameter;
use App\Models\OptimizationHistory;
use Illuminate\Support\Facades\DB;

class StrategyService
{
    public function getAllTickers()
    {
        return Ticker::whereEnabled(1)
            ->with('strategyParameter')
            ->get()
            ->map(function ($ticker) {
                return [
                    'symbol' => $ticker->symbol,
                    'id' => $ticker->id,
                    'params' => $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null,
                ];
            });
    }

    public function getStrategyForSymbol($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return null;
        }

        return [
            'ticker' => $ticker->toArray(),
            'params' => $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null,
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
            ->toArray();
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
