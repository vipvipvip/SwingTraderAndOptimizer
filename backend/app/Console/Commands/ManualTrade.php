<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

class ManualTrade extends Command
{
    protected $signature = 'trade:manual {action : buy|sell} {symbol : Ticker symbol} {--qty= : Quantity (optional)}';

    protected $description = 'Manually place buy or sell orders for testing';

    public function handle()
    {
        $action = $this->argument('action');
        $symbol = strtoupper($this->argument('symbol'));
        $qty = $this->option('qty') ? intval($this->option('qty')) : null;

        $executor = app(TradeExecutorService::class);

        try {
            if ($action === 'buy') {
                $result = $executor->manualBuy($symbol, $qty);
                $this->info("✓ BUY order placed: {$symbol} qty={$result['qty']}");
            } elseif ($action === 'sell') {
                $result = $executor->manualSell($symbol, $qty);
                $this->info("✓ SELL order placed: {$symbol} qty={$result['qty']}");
            } else {
                $this->error("Invalid action. Use 'buy' or 'sell'");
                return 1;
            }

            return 0;
        } catch (\Exception $e) {
            $this->error("Trade failed: " . $e->getMessage());
            return 1;
        }
    }
}
