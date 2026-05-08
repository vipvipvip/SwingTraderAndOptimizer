<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\BacktestTrade;
use App\Models\EquitySnapshot;

class BacktestTradesController extends Controller
{
    public function index()
    {
        $equity = EquitySnapshot::where('snapshot_type', 'backtest')
            ->get()
            ->keyBy(fn($s) => $s->ticker_id . '|' . $s->snapshot_date->toDateString())
            ->map(fn($s) => (float) $s->equity_value);

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
                'portfolio_value' => $equity[$trade->ticker_id . '|' . $trade->exit_at->toDateString()] ?? null,
            ]);

        return response()->json($trades);
    }

    public function bySymbol($symbol)
    {
        $ticker = \App\Models\Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return response()->json([], 404);
        }

        $equity = EquitySnapshot::where('snapshot_type', 'backtest')
            ->where('ticker_id', $ticker->id)
            ->get()
            ->keyBy(fn($s) => $s->snapshot_date->toDateString())
            ->map(fn($s) => (float) $s->equity_value);

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
                'portfolio_value' => $equity[$trade->exit_at->toDateString()] ?? null,
            ]);

        return response()->json($trades);
    }
}
