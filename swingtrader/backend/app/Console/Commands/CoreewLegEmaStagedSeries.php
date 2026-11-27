<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

class CoreewLegEmaStagedSeries extends Command
{
    protected $signature = 'trades:coreew-leg-ema-staged-series
        {--profile=ema : staged profile: ema, close-ema5, or close-ema20}
        {--symbols= : Comma-separated symbols (default QQQ,VTI,VTV)}
        {--pretty : Pretty-print the JSON}';

    protected $description = 'CoreEW research staged EMA5/10 vs EMA20 weekly weight series as JSON (read-only)';

    public function handle()
    {
        $symbols = $this->option('symbols')
            ? array_map('trim', explode(',', $this->option('symbols')))
            : ['QQQ', 'VTI', 'VTV'];

        $state = app(TradeExecutorService::class)->legEmaStagedTrail(
            $symbols, (string) ($this->option('profile') ?? 'ema'));

        $flags = JSON_UNESCAPED_SLASHES;
        if ($this->option('pretty')) {
            $flags |= JSON_PRETTY_PRINT;
        }

        $this->line(json_encode($state, $flags));
        return 0;
    }
}
