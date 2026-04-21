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

        $schedule->command('trades:execute-daily')
            ->everyThirtyMinutes()
            ->weekdays()
            ->between('09:30', '16:00')
            ->timezone('America/New_York');

        $schedule->command('equity:snapshot')
            ->dailyAt('16:05')
            ->timezone('America/New_York');

        $schedule->command('positions:sync')
            ->everyFiveMinutes()
            ->between('09:30', '16:05')
            ->timezone('America/New_York');
    }

    protected function commands()
    {
        $this->load(__DIR__.'/Commands');

        require base_path('routes/console.php');
    }
}
