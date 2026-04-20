<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Ticker;
use App\Services\StrategyService;
use Illuminate\Http\Request;

class TickerController extends Controller
{
    private $strategyService;

    public function __construct(StrategyService $strategyService)
    {
        $this->strategyService = $strategyService;
    }

    /**
     * @OA\Get(
     *      path="/api/v1/tickers",
     *      operationId="getTickers",
     *      tags={"Tickers"},
     *      summary="List all tickers with optimized parameters",
     *      description="Returns a list of all trading tickers with their latest optimized strategy parameters (Sharpe ratio, win rate, MACD settings, SMA lengths, Bollinger Bands params)",
     *      @OA\Response(
     *          response=200,
     *          description="List of tickers with parameters",
     *          @OA\JsonContent(
     *              type="array",
     *              @OA\Items(
     *                  type="object",
     *                  @OA\Property(property="id", type="integer", example=1),
     *                  @OA\Property(property="symbol", type="string", example="SPY"),
     *                  @OA\Property(property="enabled", type="boolean", example=true),
     *                  @OA\Property(property="params", type="object",
     *                      @OA\Property(property="sharpe_ratio", type="number", example=1.42),
     *                      @OA\Property(property="win_rate", type="number", example=0.65),
     *                      @OA\Property(property="total_return", type="number", example=0.2348),
     *                      @OA\Property(property="macd_fast", type="integer", example=12),
     *                      @OA\Property(property="macd_slow", type="integer", example=26),
     *                      @OA\Property(property="macd_signal", type="integer", example=9),
     *                      @OA\Property(property="sma_short", type="integer", example=50),
     *                      @OA\Property(property="sma_long", type="integer", example=200)
     *                  )
     *              )
     *          )
     *      )
     * )
     */
    public function index()
    {
        return response()->json($this->strategyService->getAllTickers());
    }

    /**
     * @OA\Get(
     *      path="/api/v1/tickers/{symbol}",
     *      operationId="getTicker",
     *      tags={"Tickers"},
     *      summary="Get ticker details with strategy parameters",
     *      @OA\Parameter(
     *          name="symbol",
     *          in="path",
     *          description="Ticker symbol (e.g., SPY, QQQ, IWM)",
     *          required=true,
     *          @OA\Schema(type="string")
     *      ),
     *      @OA\Response(
     *          response=200,
     *          description="Ticker with parameters",
     *          @OA\JsonContent(
     *              type="object",
     *              @OA\Property(property="id", type="integer"),
     *              @OA\Property(property="symbol", type="string"),
     *              @OA\Property(property="params", type="object")
     *          )
     *      ),
     *      @OA\Response(response=404, description="Ticker not found")
     * )
     */
    public function show($symbol)
    {
        $strategy = $this->strategyService->getStrategyForSymbol($symbol);
        if (!$strategy) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }
        return response()->json($strategy);
    }

    public function store(Request $request)
    {
        $validated = $request->validate(['symbol' => 'required|string|max:10']);
        $ticker = Ticker::firstOrCreate($validated, ['enabled' => 1]);
        return response()->json($ticker, 201);
    }

    public function destroy($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }
        $ticker->update(['enabled' => 0]);
        return response()->json(['message' => 'Ticker disabled']);
    }
}
