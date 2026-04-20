<?php

namespace App\Console\Commands;

use App\Models\Ticker;
use App\Models\EquitySnapshot;
use Carbon\Carbon;
use Illuminate\Console\Command;

class ImportBacktestCsv extends Command
{
    protected $signature = 'backtest:import {symbol} {--csv-path=} {--initial-capital=100000}';
    protected $description = 'Import backtest trades CSV and reconstruct daily equity curve';

    public function handle()
    {
        $symbol = $this->argument('symbol');
        $csvPath = $this->option('csv-path');
        $initialCapital = (float) $this->option('initial-capital');

        // Auto-detect CSV if not provided
        if (!$csvPath) {
            $baseDir = 'c:/data/Program Files/Alpaca-API-Trading/backtest_results';
            $csvPath = $this->findLatestCsv($baseDir, $symbol);
        }

        if (!file_exists($csvPath)) {
            $this->error("CSV file not found: $csvPath");
            return 1;
        }

        try {
            $this->info("Importing backtest for $symbol from: $csvPath");
            $this->importTrades($symbol, $csvPath, $initialCapital);
            $this->info("✓ Backtest imported successfully");
            return 0;
        } catch (\Exception $e) {
            $this->error("Import failed: " . $e->getMessage());
            return 1;
        }
    }

    private function findLatestCsv($baseDir, $symbol)
    {
        $pattern = "$baseDir/{$symbol}_trades_*.csv";
        $files = glob($pattern);

        if (empty($files)) {
            return null;
        }

        // Sort by modification time, return most recent
        usort($files, function ($a, $b) {
            return filemtime($b) - filemtime($a);
        });

        return $files[0];
    }

    private function importTrades($symbol, $csvPath, $initialCapital)
    {
        $ticker = Ticker::where('symbol', $symbol)->firstOrFail();

        // Parse CSV
        $trades = $this->parseCsv($csvPath);

        if (empty($trades)) {
            throw new \Exception("No trades found in CSV");
        }

        $this->info("Found " . count($trades) . " trades");

        // Reconstruct equity curve (equity after each trade)
        $equity = $initialCapital;
        $equitySnapshots = [];

        foreach ($trades as $trade) {
            $entryDate = Carbon::parse($trade['entry_date'])->toDateString();
            $exitDate = Carbon::parse($trade['exit_date'])->toDateString();
            $pnlPercent = (float) $trade['return'];

            // Update equity after trade closes
            $equity = $equity * (1 + $pnlPercent);

            // Store snapshot on exit date
            $equitySnapshots[$exitDate] = $equity;
        }

        // Clear old backtest snapshots for this ticker
        EquitySnapshot::where('ticker_id', $ticker->id)
            ->where('snapshot_type', 'backtest')
            ->delete();

        // Insert daily snapshots
        $batch = [];
        ksort($equitySnapshots); // Sort by date

        foreach ($equitySnapshots as $date => $equityValue) {
            $batch[] = [
                'ticker_id' => $ticker->id,
                'snapshot_date' => $date,
                'equity_value' => $equityValue,
                'snapshot_type' => 'backtest',
                'source' => 'csv_import',
                'created_at' => now(),
                'updated_at' => now(),
            ];

            // Batch insert every 100 rows
            if (count($batch) >= 100) {
                EquitySnapshot::insert($batch);
                $batch = [];
            }
        }

        // Insert remaining
        if (!empty($batch)) {
            EquitySnapshot::insert($batch);
        }

        $this->line("  Inserted " . count($equitySnapshots) . " daily equity snapshots");
    }

    private function parseCsv($csvPath)
    {
        $trades = [];
        $handle = fopen($csvPath, 'r');

        if (!$handle) {
            throw new \Exception("Cannot open CSV file");
        }

        // Read header
        $headers = fgetcsv($handle);
        if (!$headers) {
            throw new \Exception("CSV is empty");
        }

        // Parse rows
        while (($row = fgetcsv($handle)) !== false) {
            if (count($row) < 2) continue; // Skip empty rows

            $trade = array_combine($headers, $row);
            if ($trade && isset($trade['entry_date']) && $trade['entry_date']) {
                $trades[] = $trade;
            }
        }

        fclose($handle);
        return $trades;
    }
}
