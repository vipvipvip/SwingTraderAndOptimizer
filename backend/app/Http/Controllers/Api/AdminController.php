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
            $pythonPath = env('PYTHON_PATH');
            $scriptPath = env('NIGHTLY_SCRIPT');

            if (!file_exists($pythonPath) || !file_exists($scriptPath)) {
                return response()->json(['error' => 'Python or script path invalid'], 500);
            }

            $output = [];
            $returnCode = 0;
            exec("\"$pythonPath\" \"$scriptPath\" 2>&1", $output, $returnCode);

            if ($returnCode !== 0) {
                return response()->json(['error' => 'Optimizer failed', 'output' => implode("\n", $output)], 500);
            }

            return response()->json(['message' => 'Optimizer triggered', 'output' => implode("\n", $output)]);
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
