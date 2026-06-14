<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\BacktestTrade;
use App\Models\EquitySnapshot;
use App\Models\Ticker;

class BacktestTradesController extends Controller
{
    public function index(\Illuminate\Http\Request $request)
    {
        $perPage = min((int) $request->query('per_page', 50), 200);

        $page = $request->query('page', 1);
        $trades = BacktestTrade::with('ticker')
            ->orderByDesc('exit_at')
            ->paginate($perPage, ['*'], 'page', $page);

        $tickerIds = $trades->pluck('ticker_id')->unique();
        $equity = EquitySnapshot::where('snapshot_type', 'backtest')
            ->whereIn('ticker_id', $tickerIds)
            ->get()
            ->keyBy(fn($s) => $s->ticker_id . '|' . $s->snapshot_date->toDateString())
            ->map(fn($s) => (float) $s->equity_value);

        $mapped = $trades->map(fn ($trade) => [
            'id' => 'backtest_' . $trade->id,
            'symbol' => $trade->ticker->symbol,
            'source_symbol' => $trade->source_symbol ?: $trade->ticker->symbol,
            'entry_price' => (float) $trade->entry_price,
            'exit_price' => (float) $trade->exit_price,
            'entry_at' => $trade->entry_at->toDateTimeString(),
            'exit_at' => $trade->exit_at->toDateTimeString(),
            'pnl_dollar' => (float) $trade->pnl_dollar,
            'return' => (float) $trade->return,
            'days_held' => $trade->days_held,
            'allocation_weight' => (float) $trade->allocation_weight,
            'simulated_close' => (bool) $trade->simulated_close,
            'portfolio_value' => $equity[$trade->ticker_id . '|' . $trade->exit_at->toDateString()] ?? null,
            'exit_type' => $trade->exit_type,
        ]);

        return response()->json([
            'data' => $mapped,
            'total' => $trades->total(),
            'per_page' => $trades->perPage(),
            'current_page' => $trades->currentPage(),
            'last_page' => $trades->lastPage(),
        ]);
    }

    public function bySymbol($symbol, \Illuminate\Http\Request $request)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return response()->json([], 404);
        }

        $perPage = min((int) $request->query('per_page', 50), 200);
        $page = $request->query('page', 1);

        $trades = BacktestTrade::where('ticker_id', $ticker->id)
            ->orderByDesc('exit_at')
            ->paginate($perPage, ['*'], 'page', $page);

        $equity = EquitySnapshot::where('snapshot_type', 'backtest')
            ->where('ticker_id', $ticker->id)
            ->get()
            ->keyBy(fn($s) => $s->snapshot_date->toDateString())
            ->map(fn($s) => (float) $s->equity_value);

        $mapped = $trades->map(fn ($trade) => [
            'id' => 'backtest_' . $trade->id,
            'symbol' => $trade->ticker->symbol,
            'source_symbol' => $trade->source_symbol ?: $symbol,
            'entry_price' => (float) $trade->entry_price,
            'exit_price' => (float) $trade->exit_price,
            'entry_at' => $trade->entry_at->toDateTimeString(),
            'exit_at' => $trade->exit_at->toDateTimeString(),
            'pnl_dollar' => (float) $trade->pnl_dollar,
            'return' => (float) $trade->return,
            'days_held' => $trade->days_held,
            'allocation_weight' => (float) $trade->allocation_weight,
            'simulated_close' => (bool) $trade->simulated_close,
            'portfolio_value' => $equity[$trade->exit_at->toDateString()] ?? null,
            'exit_type' => $trade->exit_type,
        ]);

        return response()->json([
            'data' => $mapped,
            'total' => $trades->total(),
            'per_page' => $trades->perPage(),
            'current_page' => $trades->currentPage(),
            'last_page' => $trades->lastPage(),
        ]);
    }
}
