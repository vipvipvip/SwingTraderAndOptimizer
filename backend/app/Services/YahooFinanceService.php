<?php

namespace App\Services;

use Exception;

class YahooFinanceService
{
    public function getBars($symbol, $timeframe, $start, $end)
    {
        try {
            // Get script path - backend/app/Services -> backend -> parent (SwingTraderAndOptimizer)
            $projectRoot = dirname(dirname(dirname(__DIR__)));
            $scriptPath = $projectRoot . DIRECTORY_SEPARATOR . 'optimizer' . DIRECTORY_SEPARATOR . 'get_bars_alpaca.py';
            $pythonPath = $projectRoot . DIRECTORY_SEPARATOR . 'optimizer' . DIRECTORY_SEPARATOR . 'venv' . DIRECTORY_SEPARATOR . 'Scripts' . DIRECTORY_SEPARATOR . 'python.exe';

            if (!file_exists($scriptPath)) {
                throw new Exception('Script not found at: ' . $scriptPath);
            }

            if (!file_exists($pythonPath)) {
                throw new Exception('Python venv not found at: ' . $pythonPath);
            }

            $interval = $this->getYahooInterval($timeframe);

            // Use full paths with backslashes for Windows shell_exec
            $command = "\"$pythonPath\" \"$scriptPath\" $symbol $interval $start $end 2>&1";

            $output = shell_exec($command);

            if (!$output) {
                throw new Exception('Python script returned no output. Command: ' . $command);
            }

            $result = json_decode($output, true);

            if (!$result || !isset($result['success'])) {
                throw new Exception('Invalid response from Python script: ' . trim($output));
            }

            if (!$result['success']) {
                throw new Exception($result['error'] ?? 'Unknown error from Python script');
            }

            return $result['bars'] ?? [];
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

}
