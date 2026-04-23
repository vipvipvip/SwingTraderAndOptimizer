<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Ticker;
use App\Services\EquityService;
use Illuminate\Http\Request;

class AdminController extends Controller
{
    private $equityService;

    public function __construct(EquityService $equityService)
    {
        $this->equityService = $equityService;
    }

    public function addTicker(Request $request)
    {
        $validated = $request->validate(['symbol' => 'required|string|max:10']);
        $ticker = Ticker::firstOrCreate($validated, ['enabled' => 1]);
        return response()->json($ticker, 201);
    }

    public function removeTicker($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }
        $ticker->update(['enabled' => 0]);
        return response()->json(['message' => 'Ticker disabled']);
    }

    public function triggerOptimizer()
    {
        try {
            $phpPath = PHP_BINDIR . DIRECTORY_SEPARATOR . 'php';
            $artisanPath = base_path('artisan');
            $logFile = base_path('storage/logs/optimizer-bg.log');

            if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
                $command = "start /B " . escapeshellarg($phpPath) . ' ' . escapeshellarg($artisanPath) . ' optimize:nightly >> ' . escapeshellarg($logFile) . ' 2>&1';
                $output = [];
                exec($command, $output);
            } else {
                $command = escapeshellarg($phpPath) . ' ' . escapeshellarg($artisanPath) . ' optimize:nightly >> ' . escapeshellarg($logFile) . ' 2>&1 &';
                exec($command);
            }

            return response()->json(['message' => 'Optimizer started in background. Check data/ folder and storage/logs/optimizer-bg.log for progress']);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }

    public function triggerTrades()
    {
        try {
            $output = [];
            $returnCode = 0;
            $phpPath = PHP_BINDIR . DIRECTORY_SEPARATOR . 'php';
            $artisanPath = base_path('artisan');

            // Use escapeshellarg for proper path escaping on Windows/Unix
            $command = escapeshellarg($phpPath) . ' ' . escapeshellarg($artisanPath) . ' trades:execute-daily --force-test 2>&1';
            exec($command, $output, $returnCode);

            // Check if command succeeded by looking for success indicators, not just return code
            // (Xdebug timeouts can cause false failures)
            $outputStr = implode("\n", $output);
            $hasSuccess = strpos($outputStr, 'completed') !== false || strpos($outputStr, 'Trade execution') !== false;

            if (!$hasSuccess && $returnCode !== 0) {
                return response()->json(['error' => 'Trade execution failed', 'output' => $outputStr], 500);
            }

            return response()->json(['message' => 'Trade executor triggered', 'output' => $outputStr]);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }

    public function importBacktestCsvs(Request $request)
    {
        $validated = $request->validate([
            'symbol' => 'required|string',
            'csv_path' => 'required|string',
        ]);

        try {
            $this->equityService->importBacktestCsv($validated['symbol'], $validated['csv_path']);
            return response()->json(['message' => 'Backtest CSV imported']);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }
}
