<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

/**
 * Emits the RESEARCH-ONLY "P{exit}w + {trim}w half trim" decision series as
 * JSON, straight from TradeExecutorService::legEmaTrimTrail() ->
 * replayLegEmaTrimSeries().
 *
 * Same idea as CoreewLegEmaSeries, one dimension wider: every weekly point
 * carries the canonical P{exit}w `long` gate AND a sticky `exposure` of
 * 0.0 / 0.5 / 1.0 (1.0 = full leg, 0.5 = half the leg after a
 * {trim}w close below, 0.0 = full exit). The exit leg is read straight out of
 * the LIVE replayLegEmaSeries() code path, so the overlay cannot drift from
 * what live trades.
 *
 * NOT a live variant: no driver, no timer, no orders. Consumed only by
 * `backtest_trio_ew.py --leg-ema-trim` for A/B signal-quality work.
 *
 * Read-only: no Alpaca calls, no orders, safe to run any time.
 */
class CoreewLegEmaTrimSeries extends Command
{
    protected $signature = 'trades:coreew-leg-ema-trim-series
        {--exit-span= : EMA span in weeks for the full exit (default 20 — the live P20w exit) }
        {--trim-span= : EMA span in weeks that trims to half (default 10)}
        {--symbols= : Comma-separated symbols (default QQQ,VTI,VTV)}
        {--pretty : Pretty-print the JSON}';

    protected $description = 'RESEARCH-ONLY P{exit}w + {trim}w half-trim exposure series as JSON (read-only; exit leg from the live P{exit}w code path)';

    public function handle()
    {
        $exitSpan = (int) ($this->option('exit-span') !== null
            ? $this->option('exit-span')
            : 20);
        $trimSpan = (int) ($this->option('trim-span') !== null
            ? $this->option('trim-span')
            : 10);
        if ($exitSpan < 1 || $trimSpan < 1) {
            $this->error('--exit-span and --trim-span must be >= 1.');
            return 1;
        }
        if ($trimSpan >= $exitSpan) {
            $this->error("--trim-span ($trimSpan) must be < --exit-span ($exitSpan): a trim EMA at or above the exit EMA can never hold a leg between the two.");
            return 1;
        }

        $symbols = $this->option('symbols')
            ? array_map('trim', explode(',', $this->option('symbols')))
            : ['QQQ', 'VTI', 'VTV'];

        $state = app(TradeExecutorService::class)->legEmaTrimTrail($exitSpan, $trimSpan, $symbols);

        $flags = JSON_UNESCAPED_SLASHES;
        if ($this->option('pretty')) {
            $flags |= JSON_PRETTY_PRINT;
        }

        $this->line(json_encode($state, $flags));
        return 0;
    }
}
