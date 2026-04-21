<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Support\Facades\Mail;
use App\Mail\LogErrorAlert;

class CheckLogsAndAlert extends Command
{
    protected $signature = 'logs:check-and-alert';
    protected $description = 'Check recent logs for errors and send email alert if found';

    public function handle()
    {
        $logFile = storage_path('logs/laravel.log');

        if (!file_exists($logFile)) {
            return Command::SUCCESS;
        }

        $recentErrors = $this->parseRecentErrors($logFile);

        if (count($recentErrors) > 0) {
            $this->sendAlert($recentErrors);
            $this->info('Alert email sent with ' . count($recentErrors) . ' error(s)');
        } else {
            $this->info('No errors found in recent logs');
        }

        return Command::SUCCESS;
    }

    private function parseRecentErrors($logFile)
    {
        $lines = file($logFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        $errors = [];
        $lookbackHours = 4; // Check logs from last 4 hours
        $cutoffTime = now()->subHours($lookbackHours);

        foreach (array_reverse($lines) as $line) {
            // Stop if we've gone past the cutoff time
            if (preg_match('/\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]/', $line, $matches)) {
                $logTime = \Carbon\Carbon::createFromFormat('Y-m-d H:i:s', $matches[1]);
                if ($logTime < $cutoffTime) {
                    break;
                }
            }

            // Capture ERROR, CRITICAL, failed messages
            if (preg_match('/ERROR|CRITICAL|failed|Failed|error|Error/', $line)) {
                array_unshift($errors, $line);
            }
        }

        return array_slice($errors, 0, 20); // Return last 20 errors max
    }

    private function sendAlert($errors)
    {
        $recipient = env('LOG_ALERT_EMAIL', 'dikeshchokshi@gmail.com');

        Mail::send(new LogErrorAlert($errors, $recipient));
    }
}
