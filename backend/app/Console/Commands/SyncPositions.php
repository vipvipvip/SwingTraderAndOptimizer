<?php

namespace App\Console\Commands;

use App\Models\PositionCache;
use App\Services\AlpacaService;
use Illuminate\Console\Command;

class SyncPositions extends Command
{
    protected $signature = 'positions:sync';

    protected $description = 'Sync positions from Alpaca API';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);

        try {
            $positions = $alpacaService->getPositions();

            PositionCache::truncate();

            foreach ($positions as $pos) {
                PositionCache::create([
                    'symbol' => $pos['symbol'],
                    'qty' => intval($pos['qty']),
                    'avg_entry_price' => floatval($pos['avg_entry_price']),
                    'current_price' => floatval($pos['current_price']),
                    'unrealized_pnl' => floatval($pos['unrealized_pl'] ?? 0),
                    'market_value' => floatval($pos['market_value']),
                    'side' => strtolower($pos['side']),
                    'last_synced_at' => now(),
                ]);
            }

            $this->info("Synced " . count($positions) . " positions");
            return 0;
        } catch (\Exception $e) {
            $this->error('Position sync failed: ' . $e->getMessage());
            return 1;
        }
    }
}
