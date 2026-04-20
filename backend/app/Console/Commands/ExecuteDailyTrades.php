<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;

class ExecuteDailyTrades extends Command
{
    protected $signature = 'trades:execute-daily';

    protected $description = 'Execute daily trades for all enabled tickers';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);

        try {
            $clock = $alpacaService->getClock();

            if (!$clock['is_open']) {
                $this->info('Market is closed. No trades executed.');
                return 0;
            }

            $this->info('Market is open. Executing trades...');
            $tradeExecutor->executeForAllTickers();
            $this->info('Trade execution completed');

            // Snapshot account equity after trades
            $equity = $equityService->snapshotAccountEquity($alpacaService);
            if ($equity) {
                $this->info("Account equity snapshot: \$" . number_format($equity, 2));
            }

            return 0;
        } catch (\Exception $e) {
            $this->error('Trade execution failed: ' . $e->getMessage());
            return 1;
        }
    }
}
