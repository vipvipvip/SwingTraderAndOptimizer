<?php

namespace App\Services;

use GuzzleHttp\Client;
use Exception;

class AlpacaService
{
    private $client;
    private $baseUrl;
    private $headers;

    public function __construct()
    {
        $this->baseUrl = env('ALPACA_BASE_URL') . '/v2';
        $this->client = new Client();
        $this->headers = [
            'APCA-API-KEY-ID' => env('ALPACA_API_KEY'),
            'APCA-API-SECRET-KEY' => env('ALPACA_SECRET_KEY'),
        ];
    }

    public function getAccount()
    {
        try {
            $response = $this->client->get("{$this->baseUrl}/account", [
                'headers' => $this->headers
            ]);
            return json_decode($response->getBody(), true);
        } catch (Exception $e) {
            throw new Exception('Failed to fetch account: ' . $e->getMessage());
        }
    }

    public function getPositions()
    {
        try {
            $response = $this->client->get("{$this->baseUrl}/positions", [
                'headers' => $this->headers
            ]);
            return json_decode($response->getBody(), true);
        } catch (Exception $e) {
            throw new Exception('Failed to fetch positions: ' . $e->getMessage());
        }
    }

    public function placeOrder($symbol, $side, $qty)
    {
        try {
            $response = $this->client->post("{$this->baseUrl}/orders", [
                'headers' => $this->headers,
                'json' => [
                    'symbol' => $symbol,
                    'qty' => $qty,
                    'side' => $side,
                    'type' => 'market',
                    'time_in_force' => 'day'
                ]
            ]);
            return json_decode($response->getBody(), true);
        } catch (Exception $e) {
            throw new Exception('Failed to place order: ' . $e->getMessage());
        }
    }

    public function cancelOrder($orderId)
    {
        try {
            $this->client->delete("{$this->baseUrl}/orders/{$orderId}", [
                'headers' => $this->headers
            ]);
            return true;
        } catch (Exception $e) {
            throw new Exception('Failed to cancel order: ' . $e->getMessage());
        }
    }

    public function getBars($symbol, $timeframe, $start, $end)
    {
        try {
            $query = [
                'symbols' => $symbol,
                'timeframe' => $timeframe,
                'feed' => 'iex',
                'limit' => 10000,
            ];
            if ($start) $query['start'] = $start;
            if ($end) $query['end'] = $end;

            // Alpaca stock data API: data.alpaca.markets/v2/stocks/bars
            $dataApiUrl = 'https://data.alpaca.markets/v2';
            $bars = [];
            do {
                $response = $this->client->get($dataApiUrl . "/stocks/bars", [
                    'headers' => $this->headers,
                    'query' => $query,
                ]);
                $data = json_decode($response->getBody(), true);
                if (!empty($data['bars'][$symbol])) {
                    $bars = array_merge($bars, $data['bars'][$symbol]);
                }
                $query['page_token'] = $data['next_page_token'] ?? null;
            } while (!empty($query['page_token']));

            $this->writeBarsCsv($symbol, $timeframe, $bars);
            return $bars;
        } catch (Exception $e) {
            throw new Exception('Failed to fetch bars: ' . $e->getMessage());
        }
    }

    private function writeBarsCsv($symbol, $timeframe, $bars)
    {
        try {
            if (empty($bars)) return;
            $dir = base_path('data');
            if (!is_dir($dir)) @mkdir($dir, 0777, true);
            $stamp = date('Ymd_His');
            $file = $dir . DIRECTORY_SEPARATOR . "{$symbol}_{$timeframe}_{$stamp}.csv";
            $fh = fopen($file, 'w');
            if (!$fh) return;
            fputcsv($fh, ['timestamp', 'open', 'high', 'low', 'close', 'volume']);
            foreach ($bars as $b) {
                fputcsv($fh, [$b['t'] ?? '', $b['o'] ?? '', $b['h'] ?? '', $b['l'] ?? '', $b['c'] ?? '', $b['v'] ?? '']);
            }
            fclose($fh);
            \Log::info("Wrote " . count($bars) . " bars for {$symbol} to data/" . basename($file) . ", last=" . (end($bars)['t'] ?? 'n/a'));
        } catch (Exception $e) {
            \Log::warning("Failed to write bars CSV for {$symbol}: " . $e->getMessage());
        }
    }

    public function getClock()
    {
        try {
            $response = $this->client->get("{$this->baseUrl}/clock", [
                'headers' => $this->headers
            ]);
            return json_decode($response->getBody(), true);
        } catch (Exception $e) {
            throw new Exception('Failed to fetch market clock: ' . $e->getMessage());
        }
    }
}
