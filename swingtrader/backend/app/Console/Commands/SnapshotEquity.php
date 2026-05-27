<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\EquityService;
use Illuminate\Console\Command;

class SnapshotEquity extends Command
{
    protected $signature = 'equity:snapshot';

    protected $description = 'Snapshot current account equity from Alpaca';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $equityService = app(EquityService::class);

        try {
            $equity = $equityService->snapshotAccountEquity($alpacaService);

            if ($equity === null) {
                $this->error('Failed to retrieve account equity');
                return 1;
            }

            $this->info("Equity snapshot: \$" . number_format($equity, 2));
            return 0;
        } catch (\Exception $e) {
            $this->error('Snapshot failed: ' . $e->getMessage());
            return 1;
        }
    }
}
