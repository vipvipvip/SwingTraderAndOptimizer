<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class AlpacaService
{
    private $apiKey;
    private $secretKey;
    private $baseUrl;
    private $dataUrl;

    public function __construct()
    {
        $this->apiKey = env('ALPACA_API_KEY');
        $this->secretKey = env('ALPACA_SECRET_KEY');
        $this->baseUrl = env('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets');
        $this->dataUrl = 'https://data.alpaca.markets';
    }

    /**
     * Get market clock status
     */
    public function getClock()
    {
        try {
            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->get("{$this->baseUrl}/v2/clock");

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            $data = $response->json();
            return [
                'is_open' => $data['is_open'] ?? false,
                'next_open' => $data['next_open'] ?? null,
                'next_close' => $data['next_close'] ?? null,
                'timestamp' => $data['timestamp'] ?? null,
            ];
        } catch (\Exception $e) {
            Log::error('AlpacaService::getClock error: ' . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Get account information
     */
    public function getAccount()
    {
        try {
            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->get("{$this->baseUrl}/v2/account");

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            $data = $response->json();
            return [
                'equity' => $data['equity'] ?? 0,
                'buying_power' => $data['buying_power'] ?? 0,
                'cash' => $data['cash'] ?? 0,
                'portfolio_value' => $data['portfolio_value'] ?? 0,
            ];
        } catch (\Exception $e) {
            Log::error('AlpacaService::getAccount error: ' . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Get open positions from Alpaca
     */
    public function getPositions()
    {
        try {
            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->get("{$this->baseUrl}/v2/positions");

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            $positions = $response->json();
            if (!is_array($positions)) {
                $positions = [];
            }

            return array_map(function ($pos) {
                $qty = floatval($pos['qty'] ?? 0);
                $entry_price = floatval($pos['avg_entry_price'] ?? 0);
                $current_price = floatval($pos['current_price'] ?? 0);
                $market_value = floatval($pos['market_value'] ?? 0);

                // Calculate unrealized P&L if Alpaca didn't provide it
                $unrealized_pnl = $pos['unrealized_pnl'] ?? (($current_price - $entry_price) * $qty);

                return [
                    'symbol' => $pos['symbol'] ?? null,
                    'qty' => $qty,
                    'avg_entry_price' => $entry_price,
                    'current_price' => $current_price,
                    'market_value' => $market_value,
                    'unrealized_pnl' => $unrealized_pnl,
                    'unrealized_plpc' => $pos['unrealized_plpc'] ?? 0,
                ];
            }, $positions);
        } catch (\Exception $e) {
            Log::error('AlpacaService::getPositions error: ' . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Get bars for a symbol
     */
    public function getBars($symbol, $timeframe = '1Hour', $start = null, $end = null, $limit = 1000)
    {
        try {
            $params = [
                'timeframe' => $timeframe,
                'limit' => $limit,
            ];

            if ($start) {
                $params['start'] = is_string($start) ? $start : $start->toIso8601String();
            }
            if ($end) {
                $params['end'] = is_string($end) ? $end : $end->toIso8601String();
            }

            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->get("{$this->dataUrl}/v2/stocks/{$symbol}/bars", $params);

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            $data = $response->json();
            $bars = $data['bars'] ?? [];

            // Handle pagination
            while (isset($data['next_page_token']) && $data['next_page_token']) {
                $params['page_token'] = $data['next_page_token'];
                $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                    ->get("{$this->dataUrl}/v2/stocks/{$symbol}/bars", $params);

                if ($response->failed()) {
                    break;
                }

                $data = $response->json();
                $bars = array_merge($bars, $data['bars'] ?? []);
            }

            return $bars;
        } catch (\Exception $e) {
            Log::error("AlpacaService::getBars({$symbol}) error: " . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Place an order
     */
    public function placeOrder($symbol, $qty, $side, $type = 'market', $timeInForce = 'day')
    {
        try {
            $payload = [
                'symbol' => $symbol,
                'qty' => $qty,
                'side' => $side,
                'type' => $type,
                'time_in_force' => $timeInForce,
            ];

            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->post("{$this->baseUrl}/v2/orders", $payload);

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            return $response->json();
        } catch (\Exception $e) {
            Log::error("AlpacaService::placeOrder({$symbol}, {$qty}, {$side}) error: " . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Get orders from Alpaca
     */
    public function getOrders($status = 'all', $limit = 500)
    {
        try {
            $params = [
                'status' => $status,
                'limit' => $limit,
            ];

            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->get("{$this->baseUrl}/v2/orders", $params);

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            return $response->json();
        } catch (\Exception $e) {
            Log::error("AlpacaService::getOrders error: " . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Cancel an order
     */
    public function cancelOrder($orderId)
    {
        try {
            $response = Http::withBasicAuth($this->apiKey, $this->secretKey)
                ->delete("{$this->baseUrl}/v2/orders/{$orderId}");

            if ($response->failed()) {
                throw new \Exception("Alpaca API error: " . $response->body());
            }

            return true;
        } catch (\Exception $e) {
            Log::error("AlpacaService::cancelOrder({$orderId}) error: " . $e->getMessage());
            throw $e;
        }
    }

    /**
     * Write bars to CSV file
     */
    public function writeBarsCsv($symbol, $bars)
    {
        try {
            if (empty($bars)) {
                return null;
            }

            $timestamp = now()->format('YmdHis');
            $filename = "data/{$symbol}_1Hour_{$timestamp}.csv";
            $filepath = storage_path("../data/{$symbol}_1Hour_{$timestamp}.csv");

            // Ensure directory exists
            @mkdir(dirname($filepath), 0755, true);

            $file = fopen($filepath, 'w');
            fputcsv($file, ['timestamp', 'open', 'high', 'low', 'close', 'volume']);

            foreach ($bars as $bar) {
                fputcsv($file, [
                    $bar['t'] ?? $bar['timestamp'] ?? '',
                    $bar['o'] ?? $bar['open'] ?? 0,
                    $bar['h'] ?? $bar['high'] ?? 0,
                    $bar['l'] ?? $bar['low'] ?? 0,
                    $bar['c'] ?? $bar['close'] ?? 0,
                    $bar['v'] ?? $bar['volume'] ?? 0,
                ]);
            }

            fclose($file);

            Log::info("Wrote {$symbol} bars to {$filepath}");
            return $filepath;
        } catch (\Exception $e) {
            Log::error("AlpacaService::writeBarsCsv error: " . $e->getMessage());
            throw $e;
        }
    }
}
