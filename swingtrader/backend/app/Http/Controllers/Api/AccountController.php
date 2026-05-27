<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\AlpacaService;

class AccountController extends Controller
{
    private $alpacaService;

    public function __construct(AlpacaService $alpacaService)
    {
        $this->alpacaService = $alpacaService;
    }

    /**
     * @OA\Get(
     *      path="/api/v1/account",
     *      operationId="getAccount",
     *      tags={"Account"},
     *      summary="Get Alpaca account information",
     *      description="Returns account equity, buying power, cash, and other account details from Alpaca",
     *      @OA\Response(
     *          response=200,
     *          description="Account details",
     *          @OA\JsonContent(
     *              type="object",
     *              @OA\Property(property="equity", type="string", example="83830.98"),
     *              @OA\Property(property="buying_power", type="string", example="167661.96"),
     *              @OA\Property(property="cash", type="string", example="83830.98"),
     *              @OA\Property(property="portfolio_value", type="string")
     *          )
     *      ),
     *      @OA\Response(response=500, description="API error")
     * )
     */
    public function show()
    {
        try {
            $account = $this->alpacaService->getAccount();
            return response()->json($account);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }

    /**
     * @OA\Get(
     *      path="/api/v1/account/positions",
     *      operationId="getPositions",
     *      tags={"Account"},
     *      summary="Get open positions",
     *      description="Returns all currently open positions from Alpaca with current price and unrealized P&L",
     *      @OA\Response(
     *          response=200,
     *          description="List of open positions",
     *          @OA\JsonContent(
     *              type="array",
     *              @OA\Items(
     *                  type="object",
     *                  @OA\Property(property="symbol", type="string", example="SPY"),
     *                  @OA\Property(property="qty", type="string", example="10"),
     *                  @OA\Property(property="avg_entry_price", type="string"),
     *                  @OA\Property(property="current_price", type="string"),
     *                  @OA\Property(property="unrealized_pnl", type="string")
     *              )
     *          )
     *      ),
     *      @OA\Response(response=500, description="API error")
     * )
     */
    public function positions()
    {
        try {
            $positions = $this->alpacaService->getPositions();
            return response()->json($positions);
        } catch (\Exception $e) {
            return response()->json(['error' => $e->getMessage()], 500);
        }
    }
}
