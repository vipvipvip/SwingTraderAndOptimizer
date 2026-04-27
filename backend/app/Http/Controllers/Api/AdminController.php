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

    /**
     * @OA\Post(
     *      path="/admin/optimize/trigger",
     *      operationId="triggerOptimizer",
     *      tags={"Admin"},
     *      summary="Manually trigger nightly optimizer",
     *      description="Run parameter optimization for all tickers immediately (normally runs at 8:18 AM ET daily)",
     *      @OA\Response(
     *          response=200,
     *          description="Optimizer started successfully",
     *          @OA\JsonContent(
     *              @OA\Property(property="message", type="string", example="Optimizer started in background. Check optimizer/logs/nightly.log for progress")
     *          )
     *      ),
     *      @OA\Response(
     *          response=500,
     *          description="Optimizer failed to start",
     *          @OA\JsonContent(
     *              @OA\Property(property="error", type="string")
     *          )
     *      )
     * )
     */
    public function triggerOptimizer()
    {
        try {
            $phpPath = PHP_BINDIR . DIRECTORY_SEPARATOR . 'php';
            $artisanPath = base_path('artisan');
            $logDir = base_path('../optimizer/logs');
            @mkdir($logDir, 0777, true);
            $logFile = $logDir . DIRECTORY_SEPARATOR . 'nightly.log';

            if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
                $command = "start /B " . escapeshellarg($phpPath) . ' ' . escapeshellarg($artisanPath) . ' optimize:nightly >> ' . escapeshellarg($logFile) . ' 2>&1';
                $output = [];
                exec($command, $output);
            } else {
                $command = escapeshellarg($phpPath) . ' ' . escapeshellarg($artisanPath) . ' optimize:nightly >> ' . escapeshellarg($logFile) . ' 2>&1 &';
                exec($command);
            }

            return response()->json(['message' => 'Optimizer started in background. Check optimizer/logs/nightly.log and backend/data/ for progress']);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }

    /**
     * @OA\Post(
     *      path="/admin/trades/trigger",
     *      operationId="triggerTrades",
     *      tags={"Admin"},
     *      summary="Manually trigger trade execution",
     *      description="Execute trades for all tickers immediately (normally runs every 30 min via cron)",
     *      @OA\Response(
     *          response=200,
     *          description="Trade execution started successfully",
     *          @OA\JsonContent(
     *              @OA\Property(property="message", type="string", example="Trade executor triggered"),
     *              @OA\Property(property="output", type="string", example="Market is open. Executing trades...")
     *          )
     *      ),
     *      @OA\Response(
     *          response=500,
     *          description="Trade execution failed",
     *          @OA\JsonContent(
     *              @OA\Property(property="error", type="string")
     *          )
     *      )
     * )
     */
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

    /**
     * @OA\Get(
     *      path="/admin/market-status",
     *      operationId="getMarketStatus",
     *      tags={"Admin"},
     *      summary="Get market status and account info",
     *      description="Check if market is open/closed and get current account details",
     *      @OA\Response(
     *          response=200,
     *          description="Successfully retrieved market status",
     *          @OA\JsonContent(
     *              @OA\Property(property="success", type="boolean", example=true),
     *              @OA\Property(
     *                  property="market",
     *                  type="object",
     *                  @OA\Property(property="is_open", type="boolean", example=true),
     *                  @OA\Property(property="next_open", type="string", example="2026-04-27T09:30:00Z"),
     *                  @OA\Property(property="next_close", type="string", example="2026-04-24T20:00:00Z")
     *              ),
     *              @OA\Property(
     *                  property="account",
     *                  type="object",
     *                  @OA\Property(property="equity", type="number", example=100001.71),
     *                  @OA\Property(property="buying_power", type="number", example=50000),
     *                  @OA\Property(property="cash", type="number", example=50000),
     *                  @OA\Property(property="portfolio_value", type="number", example=100001.71)
     *              )
     *          )
     *      ),
     *      @OA\Response(response=500, description="Failed to retrieve market status")
     * )
     */
    public function getMarketStatus()
    {
        try {
            $alpacaService = app('App\Services\AlpacaService');
            $clock = $alpacaService->getClock();
            $account = $alpacaService->getAccount();

            return response()->json([
                'success' => true,
                'market' => $clock,
                'account' => $account,
            ], 200);
        } catch (\Exception $e) {
            return response()->json(['success' => false, 'error' => $e->getMessage()], 500);
        }
    }

    public function getLastRuns()
    {
        $dbPath = base_path('../optimizer/optimized_params/strategy_params.db');
        $lastOptimizerRun = null;
        $lastTradesRun = null;

        if (file_exists($dbPath)) {
            try {
                $sqliteConn = new \SQLite3($dbPath);
                $result = $sqliteConn->querySingle(
                    'SELECT MAX(run_date) as latest_run FROM optimization_history',
                    true
                );
                if ($result && $result['latest_run']) {
                    $lastOptimizerRun = $result['latest_run'];
                }
                $sqliteConn->close();
            } catch (\Exception $e) {
                // Silently fail
            }
        }

        // Get last trades execution time from file (updated every command run)
        $statusFile = storage_path('trades_last_run.txt');
        if (file_exists($statusFile)) {
            try {
                $lastTradesRun = trim(file_get_contents($statusFile));
            } catch (\Exception $e) {
                // Silently fail, fall back to DB query
            }
        }

        // Fallback to DB if file not available
        if (!$lastTradesRun) {
            try {
                $lastTrade = \Illuminate\Support\Facades\DB::table('live_trades')
                    ->selectRaw('MAX(entry_at) as latest_entry')
                    ->first();
                if ($lastTrade && $lastTrade->latest_entry) {
                    $lastTradesRun = $lastTrade->latest_entry;
                }
            } catch (\Exception $e) {
                // Silently fail
            }
        }

        return response()->json([
            'last_optimizer_run' => $lastOptimizerRun,
            'last_trades_run' => $lastTradesRun,
        ]);
    }
}
