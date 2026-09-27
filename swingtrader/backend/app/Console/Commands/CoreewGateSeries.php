<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

/**
 * Emits the CoreEW gate's per-week decision series as JSON, straight from the
 * SAME service method the live trade path runs (coreewGateSeries).
 *
 * This exists so the backtest never re-implements the gate. backtest_trio_ew.py
 * shells out to this once and only does date alignment + fills, so live and
 * backtest cannot drift apart.
 *
 * Read-only: no Alpaca calls, no orders, safe to run any time.
 */
class CoreewGateSeries extends Command
{
    protected $signature = 'trades:coreew-gate-series
        {--mult= : Weekly ratchet ATR multiplier (default: COREEW_GATE_MULT env, 2.0)}
        {--symbols= : Comma-separated symbols (default QQQ,VTI,VTV)}
        {--pretty : Pretty-print the JSON}';

    protected $description = 'CoreEW gate per-week decision series as JSON (read-only; same code path as live trading)';

    public function handle()
    {
        $mult = (float) ($this->option('mult') !== null
            ? $this->option('mult')
            : env('COREEW_GATE_MULT', 2.0));
        if ($mult <= 0 || $mult > 10) {
            $this->error('--mult must be > 0 (and reasonably <= 10).');
            return 1;
        }

        $symbols = $this->option('symbols')
            ? array_map('trim', explode(',', $this->option('symbols')))
            : ['QQQ', 'VTI', 'VTV'];

        $series = app(TradeExecutorService::class)->coreewGateSeries($symbols, $mult);

        $payload = [
            'mult' => $mult,
            'cutoff' => $series['cutoff'],
            'last_week' => $series['last_week'],
            'state' => $series['state'],
            'series' => $series['series'],
        ];

        $flags = JSON_UNESCAPED_SLASHES;
        if ($this->option('pretty')) {
            $flags |= JSON_PRETTY_PRINT;
        }

        $this->line(json_encode($payload, $flags));
        return 0;
    }
}
