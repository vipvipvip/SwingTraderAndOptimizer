<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use GuzzleHttp\Client;

class CheckLogsAndAlert extends Command
{
    protected $signature = 'logs:check-and-alert';
    protected $description = 'Check recent logs for errors and send Slack alert if found';

    public function handle()
    {
        $logFile = storage_path('logs/laravel.log');

        if (!file_exists($logFile)) {
            return Command::SUCCESS;
        }

        $recentErrors = $this->parseRecentErrors($logFile);

        if (count($recentErrors) > 0) {
            $this->sendSlackAlert($recentErrors);
            $this->info('Slack alert sent with ' . count($recentErrors) . ' error(s)');
        } else {
            $this->info('No errors found in recent logs');
        }

        return Command::SUCCESS;
    }

    private function parseRecentErrors($logFile)
    {
        $lines = file($logFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        $errors = [];
        $lookbackHours = 4;
        $cutoffTime = now()->subHours($lookbackHours);

        foreach (array_reverse($lines) as $line) {
            if (preg_match('/\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]/', $line, $matches)) {
                $logTime = \Carbon\Carbon::createFromFormat('Y-m-d H:i:s', $matches[1]);
                if ($logTime < $cutoffTime) {
                    break;
                }
            }

            if (preg_match('/ERROR|CRITICAL|failed|Failed|error|Error/', $line)) {
                // Truncate long lines for Slack readability
                $truncated = strlen($line) > 200 ? substr($line, 0, 200) . '...' : $line;
                array_unshift($errors, $truncated);
            }
        }

        return array_slice($errors, 0, 20);
    }

    private function sendSlackAlert($errors)
    {
        $webhookUrl = env('SLACK_WEBHOOK_URL');

        if (!$webhookUrl) {
            $this->error('SLACK_WEBHOOK_URL not configured in .env');
            return;
        }

        // Simple text format (no blocks to avoid JSON encoding issues)
        $errorList = implode("\n", array_map(fn($e) => "• " . $e, $errors));

        $payload = [
            'text' => ':warning: SwingTrader Alert: ' . count($errors) . ' error(s) in logs',
            'attachments' => [
                [
                    'color' => 'danger',
                    'title' => 'SwingTrader Error Alert',
                    'text' => count($errors) . " error(s) found in last 4 hours",
                    'fields' => [
                        [
                            'title' => 'Errors',
                            'value' => $errorList,
                            'short' => false
                        ]
                    ],
                    'footer' => 'Check logs: backend/storage/logs/laravel.log'
                ]
            ]
        ];

        try {
            $client = new Client();
            $client->post($webhookUrl, [
                'json' => $payload
            ]);
        } catch (\Exception $e) {
            $this->error('Failed to send Slack alert: ' . $e->getMessage());
        }
    }
}
