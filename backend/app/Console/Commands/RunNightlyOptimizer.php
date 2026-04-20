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
        $pythonPath = env('PYTHON_PATH');
        $scriptPath = env('NIGHTLY_SCRIPT');

        // Resolve relative paths from project root (parent of backend/)
        $projectRoot = dirname(base_path());

        // Convert relative paths to absolute
        if (strpos($pythonPath, '..') === 0 || strpos($pythonPath, '.') === 0) {
            $pythonPath = realpath($projectRoot . DIRECTORY_SEPARATOR . $pythonPath);
        }
        if (strpos($scriptPath, '..') === 0 || strpos($scriptPath, '.') === 0) {
            $scriptPath = realpath($projectRoot . DIRECTORY_SEPARATOR . $scriptPath);
        }

        if (!file_exists($pythonPath) || !file_exists($scriptPath)) {
            $this->error("Python or script path not found:\n  Python: {$pythonPath}\n  Script: {$scriptPath}");
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
