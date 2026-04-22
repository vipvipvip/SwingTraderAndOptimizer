<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;

class RunNightlyOptimizer extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'optimize:nightly';

    protected $description = 'Run nightly parameter optimization for all tickers';

    public function handle()
    {
        $pythonPath = env('PYTHON_PATH', 'python');
        $scriptPath = env('NIGHTLY_SCRIPT');

        // Resolve relative paths from backend directory
        if (strpos($scriptPath, '..') === 0) {
            $scriptPath = realpath(base_path() . DIRECTORY_SEPARATOR . $scriptPath);
        }

        if (!$scriptPath || !file_exists($scriptPath)) {
            $this->error("Script path not found");
            return 1;
        }

        $this->info('Starting nightly optimization...');

        $process = proc_open(
            "\"$pythonPath\" \"$scriptPath\"",
            [
                0 => STDIN,
                1 => STDOUT,
                2 => STDERR,
            ],
            $pipes
        );

        if (is_resource($process)) {
            $returnCode = proc_close($process);
            if ($returnCode === 0) {
                $this->info('Optimization completed successfully');
                return 0;
            } else {
                $this->error("Optimization failed with code $returnCode");
                return $returnCode;
            }
        }

        $this->error('Failed to start Python process');
        return 1;
    }
}
