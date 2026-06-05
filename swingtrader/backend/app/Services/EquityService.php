<?php

namespace App\Services;

use App\Models\EquitySnapshot;
use App\Models\Ticker;
use App\Models\LiveTrade;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Facades\Log;

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

    public function syncLiveTradesFromAlpaca($alpacaService)
    {
        try {
            $orders = $alpacaService->getOrders('all');

            if (!is_array($orders)) {
                $orders = [];
            }

            // Group orders by symbol and side to match buy/sell pairs
            $buyOrders = [];
            $sellOrders = [];

            foreach ($orders as $order) {
                $symbol = $order['symbol'] ?? null;
                $status = strtolower($order['status'] ?? '');
                $side = strtolower($order['side'] ?? '');

                if (!$symbol || $status !== 'filled') continue;

                $ticker = Ticker::where('symbol', $symbol)->first();
                if (!$ticker) continue;

                $qty = intval($order['filled_qty'] ?? $order['qty'] ?? 0);
                // Skip test/force orders (qty=1) — only sync real allocation-based trades
                if ($qty <= 1) continue;
                $price = floatval($order['filled_avg_price'] ?? 0);
                $created_at = $order['created_at'] ?? now()->toDateTimeString();

                $tradeData = [
                    'id' => $order['id'],
                    'ticker_id' => $ticker->id,
                    'symbol' => $symbol,
                    'qty' => $qty,
                    'price' => $price,
                    'created_at' => $created_at,
                ];

                if ($side === 'buy') {
                    $buyOrders[] = $tradeData;
                } else {
                    $sellOrders[] = $tradeData;
                }
            }

            // Process buy orders - create or update live trades
            foreach ($buyOrders as $buyOrder) {
                $existing = LiveTrade::where('alpaca_order_id', $buyOrder['id'])->first();

                if ($existing) {
                    $existing->update([
                        'entry_price' => $buyOrder['price'],
                        'quantity' => $buyOrder['qty'],
                        'status' => 'open',
                    ]);
                } else {
                    LiveTrade::create([
                        'ticker_id' => $buyOrder['ticker_id'],
                        'symbol' => $buyOrder['symbol'],
                        'side' => 'BUY',
                        'quantity' => $buyOrder['qty'],
                        'entry_price' => $buyOrder['price'],
                        'entry_at' => $buyOrder['created_at'],
                        'status' => 'open',
                        'alpaca_order_id' => $buyOrder['id'],
                    ]);
                }
            }

            // Process sell orders - match with open buys and close them
            foreach ($sellOrders as $sellOrder) {
                $sellTime = $sellOrder['created_at'];

                // Only match sell orders to buys that entered before the sell
                $openBuy = LiveTrade::where('ticker_id', $sellOrder['ticker_id'])
                    ->where('status', 'open')
                    ->where('side', 'BUY')
                    ->where('entry_at', '<=', $sellTime)
                    ->orderBy('entry_at')
                    ->first();

                if ($openBuy) {
                    $entry_price = floatval($openBuy->entry_price ?? 0);
                    $exit_price = $sellOrder['price'];
                    $qty = intval($openBuy->quantity ?? $sellOrder['qty']);
                    $pnl_dollar = ($exit_price - $entry_price) * $qty;
                    $pnl_pct = $entry_price > 0 ? (($exit_price - $entry_price) / $entry_price) * 100 : 0;

                    $openBuy->update([
                        'exit_price' => $exit_price,
                        'exit_at' => $sellTime,
                        'status' => 'closed',
                        'pnl_dollar' => $pnl_dollar,
                        'pnl_pct' => $pnl_pct,
                    ]);
                }
            }

            // Reconcile open positions from Alpaca position data (correct avg entry price from multiple fills)
            try {
                $positions = $alpacaService->getPositions();
                if (is_array($positions)) {
                    foreach ($positions as $pos) {
                        $symbol = $pos['symbol'] ?? null;
                        $avgEntry = floatval($pos['avg_entry_price'] ?? 0);
                        $qty = intval($pos['qty'] ?? 0);
                        if (!$symbol || $avgEntry <= 0) continue;

                        $openTrade = LiveTrade::where('symbol', $symbol)
                            ->where('status', 'open')
                            ->latest('entry_at')
                            ->first();

                        if ($openTrade) {
                            $openTrade->update([
                                'entry_price' => $avgEntry,
                                'quantity' => $qty,
                            ]);
                            Log::info("Reconciled $symbol position: qty=$qty avg_entry=$avgEntry");
                        }
                    }
                }
            } catch (\Exception $e) {
                Log::warning('Position reconciliation failed: ' . $e->getMessage());
            }

            return true;
        } catch (\Exception $e) {
            Log::error('Failed to sync live trades: ' . $e->getMessage());
            return false;
        }
    }
}
