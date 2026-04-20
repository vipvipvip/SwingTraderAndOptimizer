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
                'feed' => 'iex'
            ];
            if ($start) $query['start'] = $start;
            if ($end) $query['end'] = $end;

            // Use data API for historical bars
            $response = $this->client->get(str_replace('/v2', '/v1/data', $this->baseUrl) . "/stocks/bars", [
                'headers' => $this->headers,
                'query' => $query
            ]);
            $data = json_decode($response->getBody(), true);
            return $data['bars'][$symbol] ?? [];
        } catch (Exception $e) {
            throw new Exception('Failed to fetch bars: ' . $e->getMessage());
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
