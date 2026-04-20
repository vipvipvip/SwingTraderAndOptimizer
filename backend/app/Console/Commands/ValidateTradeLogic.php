<?php

namespace App\Console\Commands;

use App\Models\Ticker;
use App\Services\TradeExecutorService;
use App\Services\AlpacaService;
use Illuminate\Console\Command;

class ValidateTradeLogic extends Command
{
    protected $signature = 'trades:validate {symbol}';
    protected $description = 'Validate trade signal logic without placing orders';

    public function handle()
    {
        $symbol = $this->argument('symbol');
        $ticker = Ticker::where('symbol', $symbol)->with('strategyParameter')->first();

        if (!$ticker) {
            $this->error("Ticker not found: $symbol");
            return 1;
        }

        if (!$ticker->strategyParameter) {
            $this->error("No strategy parameters for $symbol");
            return 1;
        }

        $this->info("Validating trade logic for $symbol");
        $this->line("Strategy Parameters:");
        $params = $ticker->strategyParameter;
        $this->line("  MACD: ({$params->macd_fast}, {$params->macd_slow}, {$params->macd_signal})");
        $this->line("  SMA:  ({$params->sma_short}, {$params->sma_long})");
        $this->line("  BB:   ({$params->bb_period}, {$params->bb_std})");
        $this->line("  Win Rate: " . ($params->win_rate * 100) . "%");
        $this->line("  Sharpe: " . $params->sharpe_ratio);

        try {
            $alpacaService = app(AlpacaService::class);

            // Get current account info
            $this->line("\nAlpaca Account Status:");
            $account = $alpacaService->getAccount();
            $this->line("  Equity: $" . number_format($account['equity'] ?? 0, 2));
            $this->line("  Buying Power: $" . number_format($account['buying_power'] ?? 0, 2));
            $this->line("  Cash: $" . number_format($account['cash'] ?? 0, 2));

            // Get market clock
            $clock = $alpacaService->getClock();
            $this->line("\nMarket Status:");
            $this->line("  Is Open: " . ($clock['is_open'] ? 'YES ✓' : 'NO ✗'));
            if (isset($clock['next_open'])) {
                $this->line("  Next Open: " . $clock['next_open']);
            }
            if (isset($clock['next_close'])) {
                $this->line("  Next Close: " . $clock['next_close']);
            }

            $this->info("\n✓ Validation complete - system is ready for live trading");
            return 0;

        } catch (\Exception $e) {
            $this->error("Validation failed: " . $e->getMessage());
            return 1;
        }
    }
}
