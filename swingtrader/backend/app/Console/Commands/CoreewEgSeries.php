<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

/**
 * Emits the CoreEW EG index-EMA gate's per-day decision series as JSON,
 * straight from the SAME service method that drives live trading
 * (TradeExecutorService::indexEgTrail() -> replayIndexEgGate()).
 *
 * Mirror of CoreewGateSeries (variant S): this exists so the backtest never
 * re-implements the gate. backtest_trio_ew.py shells out to this once and only
 * does date alignment + fills, so live and backtest cannot drift apart.
 *
 * Read-only: no Alpaca calls, no orders, safe to run any time.
 */
class CoreewEgSeries extends Command
{
    protected $signature = 'trades:coreew-eg-series
        {--span= : EMA span (default: COREEW_EG_SPAN env, 100)}
        {--band= : Hysteresis band in percent (default 0 = pure crossover)}
        {--symbols= : Comma-separated symbols (default QQQ,VTI,VTV)}
        {--pretty : Pretty-print the JSON}';

    protected $description = 'CoreEW EG index-EMA gate per-day decision series as JSON (read-only; same code path as live trading)';

    public function handle()
    {
        $span = (int) ($this->option('span') !== null
            ? $this->option('span')
            : env('COREEW_EG_SPAN', 100));
        if ($span < 1) {
            $this->error('--span must be >= 1.');
            return 1;
        }

        $band = (float) ($this->option('band') !== null ? $this->option('band') : 0.0);
        if ($band < 0 || $band > 50) {
            $this->error('--band must be >= 0 (percent).');
            return 1;
        }

        $symbols = $this->option('symbols')
            ? array_map('trim', explode(',', $this->option('symbols')))
            : ['QQQ', 'VTI', 'VTV'];

        $state = app(TradeExecutorService::class)->indexEgTrail($span, $band, $symbols);

        $flags = JSON_UNESCAPED_SLASHES;
        if ($this->option('pretty')) {
            $flags |= JSON_PRETTY_PRINT;
        }

        $this->line(json_encode($state, $flags));
        return 0;
    }
}