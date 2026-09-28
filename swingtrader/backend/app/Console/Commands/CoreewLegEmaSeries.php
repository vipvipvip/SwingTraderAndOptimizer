<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

/**
 * Emits the CoreEW per-leg EMA(span) weekly crossover's decision series as JSON,
 * straight from the SAME service method that drives live trading
 * (TradeExecutorService::legEmaTrail() -> replayLegEmaSeries()).
 *
 * Mirror of CoreewEgSeries (variant EG) / CoreewGateSeries (variant S): this
 * exists so the backtest never re-implements the signal. backtest_trio_ew.py
 * shells out to this once and only does date alignment + fills, so live and
 * backtest cannot drift apart. The daily-close leg variant (P{d} in the
 * backtest) is research-only and stays out of live, so it is NOT emitted here.
 *
 * Read-only: no Alpaca calls, no orders, safe to run any time.
 */
class CoreewLegEmaSeries extends Command
{
    protected $signature = 'trades:coreew-leg-ema-series
        {--span= : EMA span in weeks (default 20 — the live P20w configuration)}
        {--symbols= : Comma-separated symbols (default QQQ,VTI,VTV)}
        {--pretty : Pretty-print the JSON}';

    protected $description = 'CoreEW per-leg weekly EMA crossover decision series as JSON (read-only; same code path as live trading)';

    public function handle()
    {
        $span = (int) ($this->option('span') !== null
            ? $this->option('span')
            : env('COREEW_LEG_EMA_SPAN', 20));
        if ($span < 1) {
            $this->error('--span must be >= 1.');
            return 1;
        }

        $symbols = $this->option('symbols')
            ? array_map('trim', explode(',', $this->option('symbols')))
            : ['QQQ', 'VTI', 'VTV'];

        $state = app(TradeExecutorService::class)->legEmaTrail($span, $symbols);

        $flags = JSON_UNESCAPED_SLASHES;
        if ($this->option('pretty')) {
            $flags |= JSON_PRETTY_PRINT;
        }

        $this->line(json_encode($state, $flags));
        return 0;
    }
}