<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;

class ImportAllBacktests extends Command
{
    protected $signature = 'backtest:import-all {--csv-dir=}';
    protected $description = 'Import all available backtest CSV files';

    public function handle()
    {
        $csvDir = $this->option('csv-dir') ?? 'c:/data/Program Files/Alpaca-API-Trading/backtest_results';

        if (!is_dir($csvDir)) {
            $this->error("Directory not found: $csvDir");
            return 1;
        }

        // Find all trade CSV files
        $files = glob("$csvDir/*_trades_*.csv");

        if (empty($files)) {
            $this->warn("No backtest CSV files found in: $csvDir");
            return 0;
        }

        $this->info("Found " . count($files) . " backtest file(s)\n");

        $successCount = 0;
        foreach ($files as $csvPath) {
            // Extract symbol from filename (e.g., SPY_trades_20260418_160855.csv → SPY)
            if (preg_match('/\/([A-Z]+)_trades_.*\.csv$/', $csvPath, $matches)) {
                $symbol = $matches[1];
                $this->line("→ Importing $symbol...");

                $result = $this->call('backtest:import', [
                    'symbol' => $symbol,
                    '--csv-path' => $csvPath,
                ]);

                if ($result === 0) {
                    $successCount++;
                }
            }
        }

        $this->info("\n✓ Import complete: $successCount/" . count($files) . " successful");
        return 0;
    }
}
