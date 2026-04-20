<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\StrategyService;

class StrategyController extends Controller
{
    private $strategyService;

    public function __construct(StrategyService $strategyService)
    {
        $this->strategyService = $strategyService;
    }

    /**
     * @OA\Get(
     *      path="/api/v1/strategies",
     *      operationId="getStrategies",
     *      tags={"Strategies"},
     *      summary="List all strategy parameters",
     *      description="Returns optimized strategy parameters for all tickers from the latest optimization run",
     *      @OA\Response(
     *          response=200,
     *          description="List of strategies with parameters",
     *          @OA\JsonContent(type="array")
     *      )
     * )
     */
    public function index()
    {
        return response()->json($this->strategyService->getAllTickers());
    }

    /**
     * @OA\Get(
     *      path="/api/v1/strategies/{symbol}",
     *      operationId="getStrategy",
     *      tags={"Strategies"},
     *      summary="Get strategy parameters for a symbol",
     *      @OA\Parameter(
     *          name="symbol",
     *          in="path",
     *          required=true,
     *          @OA\Schema(type="string", example="SPY")
     *      ),
     *      @OA\Response(response=200, description="Strategy parameters"),
     *      @OA\Response(response=404, description="Strategy not found")
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

    /**
     * @OA\Get(
     *      path="/api/v1/strategies/{symbol}/history",
     *      operationId="getOptimizationHistory",
     *      tags={"Strategies"},
     *      summary="Get optimization history",
     *      description="Returns last 10 optimization runs for a symbol with performance metrics",
     *      @OA\Parameter(
     *          name="symbol",
     *          in="path",
     *          required=true,
     *          @OA\Schema(type="string", example="SPY")
     *      ),
     *      @OA\Response(
     *          response=200,
     *          description="Optimization history",
     *          @OA\JsonContent(type="array")
     *      )
     * )
     */
    public function optimizationHistory($symbol)
    {
        $history = $this->strategyService->getOptimizationHistory($symbol);
        return response()->json($history);
    }
}
