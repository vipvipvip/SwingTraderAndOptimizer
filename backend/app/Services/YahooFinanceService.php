<?php

namespace App\Services;

use GuzzleHttp\Client;
use Exception;

class YahooFinanceService
{
    private $client;

    public function __construct()
    {
        $this->client = new Client();
    }

    public function getBars($symbol, $timeframe, $start, $end)
    {
        try {
            // Convert dates to Unix timestamps
            $startTimestamp = strtotime($start);
            $endTimestamp = strtotime($end) + 86400; // Include end date

            // Fetch CSV from Yahoo Finance
            $url = "https://query1.finance.yahoo.com/v7/finance/download/{$symbol}";
            $response = $this->client->get($url, [
                'query' => [
                    'interval' => $this->getYahooInterval($timeframe),
                    'period1' => $startTimestamp,
                    'period2' => $endTimestamp
                ]
            ]);

            $csv = $response->getBody()->getContents();
            $bars = $this->parseCSV($csv);

            return $bars;
        } catch (Exception $e) {
            throw new Exception('Failed to fetch bars from Yahoo Finance: ' . $e->getMessage());
        }
    }

    private function getYahooInterval($timeframe)
    {
        $timeframe = strtolower($timeframe);

        if (strpos($timeframe, '1hour') !== false || $timeframe === '1h') {
            return '1h';
        } elseif (strpos($timeframe, 'daily') !== false || strpos($timeframe, '1day') !== false) {
            return '1d';
        } elseif (strpos($timeframe, '5min') !== false) {
            return '5m';
        } elseif (strpos($timeframe, '15min') !== false) {
            return '15m';
        } elseif (strpos($timeframe, '30min') !== false) {
            return '30m';
        }

        return '1d'; // Default to daily
    }

    private function parseCSV($csv)
    {
        $lines = array_filter(array_map('trim', explode("\n", $csv)));
        $bars = [];

        foreach ($lines as $index => $line) {
            // Skip header row
            if ($index === 0) {
                continue;
            }

            $parts = str_getcsv($line);
            if (count($parts) < 6) {
                continue;
            }

            $bar = [
                't' => $parts[0], // Date
                'o' => floatval($parts[1]), // Open
                'h' => floatval($parts[2]), // High
                'l' => floatval($parts[3]), // Low
                'c' => floatval($parts[4]), // Close
                'v' => intval($parts[5]),   // Volume
            ];

            // Skip rows with null values (market holidays, etc.)
            if ($bar['c'] > 0) {
                $bars[] = $bar;
            }
        }

        return $bars;
    }
}
