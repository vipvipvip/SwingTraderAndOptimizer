<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\LiveTrade;
use App\Services\EquityService;

class EquityController extends Controller
{
    private $equityService;

    public function __construct(EquityService $equityService)
    {
        $this->equityService = $equityService;
    }

    /**
     * @OA\Get(
     *      path="/api/v1/equity/{symbol}",
     *      operationId="getEquityCurve",
     *      tags={"Equity & P&L"},
     *      summary="Get equity curve for a symbol",
     *      description="Returns backtest and live equity curves showing account value over time",
     *      @OA\Parameter(
     *          name="symbol",
     *          in="path",
     *          required=true,
     *          @OA\Schema(type="string", example="SPY")
     *      ),
     *      @OA\Response(
     *          response=200,
     *          description="Equity curves",
     *          @OA\JsonContent(
     *              type="object",
     *              @OA\Property(property="backtest", type="array", @OA\Items(
     *                  type="object",
     *                  @OA\Property(property="date", type="string", example="2024-01-01"),
     *                  @OA\Property(property="value", type="number", example=100000)
     *              )),
     *              @OA\Property(property="live", type="array", @OA\Items(
     *                  type="object",
     *                  @OA\Property(property="date", type="string"),
     *                  @OA\Property(property="value", type="number")
     *              ))
     *          )
     *      )
     * )
     */
    public function curve($symbol)
    {
        $curve = $this->equityService->getEquityCurveForSymbol($symbol);
        return response()->json($curve);
    }

    /**
     * @OA\Get(
     *      path="/api/v1/trades/live",
     *      operationId="getLiveTrades",
     *      tags={"Equity & P&L"},
     *      summary="Get all executed trades",
     *      description="Returns live trades executed by the trading system with entry/exit prices and P&L",
     *      @OA\Response(
     *          response=200,
     *          description="List of trades",
     *          @OA\JsonContent(
     *              type="array",
     *              @OA\Items(
     *                  type="object",
     *                  @OA\Property(property="id", type="integer"),
     *                  @OA\Property(property="symbol", type="string"),
     *                  @OA\Property(property="side", type="string", enum={"long", "short"}),
     *                  @OA\Property(property="quantity", type="integer"),
     *                  @OA\Property(property="entry_price", type="number"),
     *                  @OA\Property(property="exit_price", type="number"),
     *                  @OA\Property(property="status", type="string", enum={"open", "closed"}),
     *                  @OA\Property(property="pnl_dollar", type="number"),
     *                  @OA\Property(property="entry_at", type="string", format="date-time")
     *              )
     *          )
     *      )
     * )
     */
    public function liveTrades()
    {
        $trades = LiveTrade::orderBy('entry_at', 'desc')->get();
        return response()->json($trades);
    }

    /**
     * @OA\Get(
     *      path="/api/v1/trades/pnl",
     *      operationId="getPnlSummary",
     *      tags={"Equity & P&L"},
     *      summary="Get P&L summary",
     *      description="Returns cumulative P&L, win rate, and trade counts for all closed trades",
     *      @OA\Response(
     *          response=200,
     *          description="P&L summary",
     *          @OA\JsonContent(
     *              type="object",
     *              @OA\Property(property="total_pnl", type="number", example=2105.2),
     *              @OA\Property(property="win_rate", type="number", example=65.5),
     *              @OA\Property(property="closed_trades", type="integer", example=20),
     *              @OA\Property(property="winning_trades", type="integer", example=13)
     *          )
     *      )
     * )
     */
    public function pnlSummary()
    {
        $closedTrades = LiveTrade::where('status', 'closed')->get();
        $totalPnl = $closedTrades->sum('pnl_dollar');
        $winCount = $closedTrades->where('pnl_dollar', '>', 0)->count();
        $winRate = $closedTrades->count() > 0 ? ($winCount / $closedTrades->count()) * 100 : 0;

        return response()->json([
            'total_pnl' => $totalPnl,
            'win_rate' => round($winRate, 2),
            'closed_trades' => $closedTrades->count(),
            'winning_trades' => $winCount,
        ]);
    }
}
