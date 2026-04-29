<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\Request;

class BacktestTradesController extends Controller
{
    public function index()
    {
        $trades = \App\Models\BacktestTrade::orderByDesc('exit_at')
            ->get()
            ->map(fn ($trade) => [
                'id' => 'backtest_' . $trade->id,
                'symbol' => $trade->symbol,
                'entry_price' => (float) $trade->entry_price,
                'exit_price' => (float) $trade->exit_price,
                'entry_at' => $trade->entry_at,
                'exit_at' => $trade->exit_at,
                'pnl_dollar' => (float) $trade->pnl_dollar,
                'pnl_pct' => (float) $trade->pnl_pct,
            ]);

        return response()->json($trades);
    }
}
