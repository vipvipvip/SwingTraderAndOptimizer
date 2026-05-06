<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\BacktestTrade;

class BacktestTradesController extends Controller
{
    public function index()
    {
        $trades = BacktestTrade::with('ticker')
            ->orderByDesc('exit_at')
            ->get()
            ->map(fn ($trade) => [
                'id' => 'backtest_' . $trade->id,
                'symbol' => $trade->ticker->symbol,
                'entry_price' => (float) $trade->entry_price,
                'exit_price' => (float) $trade->exit_price,
                'entry_at' => $trade->entry_at->toDateTimeString(),
                'exit_at' => $trade->exit_at->toDateTimeString(),
                'pnl_dollar' => (float) $trade->pnl_dollar,
                'return' => (float) $trade->return,
                'days_held' => $trade->days_held,
            ]);

        return response()->json($trades);
    }

    public function bySymbol($symbol)
    {
        $ticker = \App\Models\Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return response()->json([], 404);
        }

        $trades = BacktestTrade::where('ticker_id', $ticker->id)
            ->orderByDesc('exit_at')
            ->get()
            ->map(fn ($trade) => [
                'id' => 'backtest_' . $trade->id,
                'symbol' => $symbol,
                'entry_price' => (float) $trade->entry_price,
                'exit_price' => (float) $trade->exit_price,
                'entry_at' => $trade->entry_at->toDateTimeString(),
                'exit_at' => $trade->exit_at->toDateTimeString(),
                'pnl_dollar' => (float) $trade->pnl_dollar,
                'return' => (float) $trade->return,
                'days_held' => $trade->days_held,
            ]);

        return response()->json($trades);
    }
}
