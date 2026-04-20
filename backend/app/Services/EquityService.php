<?php

namespace App\Services;

use App\Models\EquitySnapshot;
use App\Models\Ticker;
use Illuminate\Support\Facades\Storage;

class EquityService
{
    public function getEquityCurveForSymbol($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();

        $backtestCurve = [];
        $liveCurve = [];

        if ($ticker) {
            $backtestCurve = EquitySnapshot::where('ticker_id', $ticker->id)
                ->where('snapshot_type', 'backtest')
                ->orderBy('snapshot_date')
                ->get()
                ->map(function ($snap) {
                    return [
                        'date' => $snap->snapshot_date,
                        'value' => $snap->equity_value,
                    ];
                })
                ->toArray();

            $liveCurve = EquitySnapshot::where('ticker_id', $ticker->id)
                ->where('snapshot_type', 'live')
                ->orderBy('snapshot_date')
                ->get()
                ->map(function ($snap) {
                    return [
                        'date' => $snap->snapshot_date,
                        'value' => $snap->equity_value,
                    ];
                })
                ->toArray();
        }

        return [
            'backtest' => $backtestCurve,
            'live' => $liveCurve,
        ];
    }

    public function importBacktestCsv($symbol, $csvPath)
    {
        $ticker = Ticker::firstOrCreate(['symbol' => $symbol], ['enabled' => 1]);

        if (!file_exists($csvPath)) {
            throw new \Exception("CSV file not found: $csvPath");
        }

        $handle = fopen($csvPath, 'r');
        $header = fgetcsv($handle);

        $equity_index = array_search('equity', $header);
        $date_index = array_search('date', $header);

        if ($equity_index === false || $date_index === false) {
            fclose($handle);
            throw new \Exception("CSV missing 'equity' or 'date' column");
        }

        EquitySnapshot::where('ticker_id', $ticker->id)
            ->where('snapshot_type', 'backtest')
            ->delete();

        while ($row = fgetcsv($handle)) {
            if (count($row) > max($equity_index, $date_index)) {
                EquitySnapshot::create([
                    'ticker_id' => $ticker->id,
                    'snapshot_date' => $row[$date_index],
                    'equity_value' => floatval($row[$equity_index]),
                    'snapshot_type' => 'backtest',
                    'source' => 'backtest_csv',
                ]);
            }
        }

        fclose($handle);
    }

    public function snapshotAccountEquity($alpacaService)
    {
        try {
            $account = $alpacaService->getAccount();
            $equity = floatval($account['equity'] ?? 0);

            EquitySnapshot::create([
                'snapshot_date' => now()->toDateString(),
                'equity_value' => $equity,
                'snapshot_type' => 'account',
                'source' => 'alpaca_api',
            ]);

            return $equity;
        } catch (\Exception $e) {
            \Log::error('Failed to snapshot account equity: ' . $e->getMessage());
            return null;
        }
    }
}
