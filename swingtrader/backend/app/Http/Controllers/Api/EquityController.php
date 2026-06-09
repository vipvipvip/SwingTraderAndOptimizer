<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\LiveTrade;
use App\Services\EquityService;
use App\Services\AlpacaService;
use Illuminate\Support\Facades\DB;

class EquityController extends Controller
{
    private $equityService;
    private $alpacaService;

    public function __construct(EquityService $equityService, AlpacaService $alpacaService)
    {
        $this->equityService = $equityService;
        $this->alpacaService = $alpacaService;
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
        $trades = LiveTrade::orderBy('entry_at', 'desc')->paginate(100);
        $mapped = collect($trades->items())->map(function ($trade) {
            $high = $low = null;
            if ($trade->status === 'closed' && $trade->entry_at && $trade->exit_at) {
                $range = DB::table('bars')
                    ->where('ticker_id', $trade->ticker_id)
                    ->whereBetween('timestamp', [$trade->entry_at, $trade->exit_at])
                    ->selectRaw('MAX(high) as high, MIN(low) as low')
                    ->first();
                if ($range) {
                    $high = $range->high !== null ? (float) $range->high : null;
                    $low = $range->low !== null ? (float) $range->low : null;
                }
            } elseif ($trade->status === 'open' && $trade->entry_at) {
                $range = DB::table('bars')
                    ->where('ticker_id', $trade->ticker_id)
                    ->where('timestamp', '>=', $trade->entry_at)
                    ->selectRaw('MAX(high) as high, MIN(low) as low')
                    ->first();
                if ($range) {
                    $high = $range->high !== null ? (float) $range->high : null;
                    $low = $range->low !== null ? (float) $range->low : null;
                }
            }
            return [
                'id' => $trade->id,
                'ticker_id' => $trade->ticker_id,
                'symbol' => $trade->symbol,
                'side' => $trade->side,
                'quantity' => (int) $trade->quantity,
                'entry_price' => (float) $trade->entry_price,
                'exit_price' => $trade->exit_price ? (float) $trade->exit_price : null,
                'high' => $high,
                'low' => $low,
                'entry_at' => $trade->entry_at?->toDateTimeString(),
                'exit_at' => $trade->exit_at?->toDateTimeString(),
                'status' => $trade->status,
                'pnl_dollar' => $trade->pnl_dollar ? (float) $trade->pnl_dollar : null,
                'pnl_pct' => $trade->pnl_pct ? (float) $trade->pnl_pct : null,
                'alpaca_order_id' => $trade->alpaca_order_id,
                'strategy_signal' => $trade->strategy_signal,
            ];
        });
        return response()->json($mapped);
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
        $account = $this->alpacaService->getAccount();
        $positions = $this->alpacaService->getPositions();

        $totalUnrealizedPnl = 0;
        $positionDetails = [];
        foreach ($positions as $pos) {
            $pnl = floatval($pos['unrealized_pnl'] ?? 0);
            $totalUnrealizedPnl += $pnl;
            $positionDetails[] = [
                'symbol' => $pos['symbol'],
                'qty' => $pos['qty'],
                'avg_entry_price' => $pos['avg_entry_price'],
                'current_price' => $pos['current_price'],
                'unrealized_pnl' => round($pnl, 2),
                'is_open' => true,
            ];
        }

        return response()->json([
            'account_equity' => round(floatval($account['equity'] ?? 0), 2),
            'cash' => round(floatval($account['cash'] ?? 0), 2),
            'buying_power' => round(floatval($account['buying_power'] ?? 0), 2),
            'unrealized_pnl' => round($totalUnrealizedPnl, 2),
            'open_positions' => count($positions),
            'positions' => $positionDetails,
            'note' => 'All figures from Alpaca. Trades are open; P&L is unrealized.',
        ]);
    }
}
