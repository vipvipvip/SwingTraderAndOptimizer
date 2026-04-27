<?php

namespace App\Console;

use Illuminate\Console\Scheduling\Schedule;
use Illuminate\Foundation\Console\Kernel as ConsoleKernel;

class Kernel extends ConsoleKernel
{
    protected function schedule(Schedule $schedule)
    {
        // Nightly optimizer is now managed by OS scheduler (Windows Task Scheduler / cron)
        // See scripts/setup-optimizer-wts.ps1 (Windows) or scripts/setup-optimizer-cron.sh (Linux)
        // Manual trigger: php artisan optimize:nightly

        // Price fetching is handled by trade executor (calls fetchLatestPrices internally every 30 min)

        $schedule->command('trades:execute-daily')
            ->everyMinute()
            ->weekdays()
            ->timezone('America/New_York');
            // ->between('09:30', '16:00');

        $schedule->command('equity:snapshot')
            ->dailyAt('16:05')
            ->timezone('America/New_York');

        $schedule->command('positions:sync')
            ->everyFiveMinutes()
            ->between('09:30', '16:05')
            ->timezone('America/New_York');

        // Check logs for errors and alert via email
        // Runs after market close to catch trade execution errors
        $schedule->command('logs:check-and-alert')
            ->dailyAt('16:10')
            ->timezone('America/New_York')
            ->weekdays();

        // Morning check before trading starts
        $schedule->command('logs:check-and-alert')
            ->dailyAt('09:15')
            ->timezone('America/New_York')
            ->weekdays();
    }

    protected function commands()
    {
        $this->load(__DIR__.'/Commands');

        require base_path('routes/console.php');
    }
}
