<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

class CoreewLegEmaAsOfSeries extends Command
{
    protected $signature = 'trades:coreew-leg-ema-asof-series
        {--span=20 : Weekly EMA span frozen from the last settled week}
        {--symbols= : Comma-separated symbols (default QQQ,VTI,VTV)}
        {--pretty : Pretty-print the JSON}';

    protected $description = 'CoreEW research daily-close vs last settled weekly EMA series as JSON (read-only)';

    public function handle()
    {
        $symbols = $this->option('symbols')
            ? array_map('trim', explode(',', $this->option('symbols')))
            : ['QQQ', 'VTI', 'VTV'];

        $state = app(TradeExecutorService::class)->legEmaAsOfTrail(
            $symbols, (int) ($this->option('span') ?? 20));

        $flags = JSON_UNESCAPED_SLASHES;
        if ($this->option('pretty')) {
            $flags |= JSON_PRETTY_PRINT;
        }

        $this->line(json_encode($state, $flags));
        return 0;
    }
}
