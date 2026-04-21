<?php

/**
 * @OA\Info(
 *      title="Swing Trading Dashboard API",
 *      description="REST API for swing trading strategy management, backtesting, and live trading execution",
 *      version="1.0.0",
 *      contact={
 *          "name": "Trading Dashboard Team"
 *      }
 * )
 *
 * @OA\Server(
 *      url="http://localhost:8000",
 *      description="Development Server"
 * )
 *
 * @OA\Tag(
 *      name="Tickers",
 *      description="Manage trading tickers and their optimized strategy parameters"
 * )
 *
 * @OA\Tag(
 *      name="Strategies",
 *      description="Query optimized strategy parameters and optimization history"
 * )
 *
 * @OA\Tag(
 *      name="Account",
 *      description="Account equity, buying power, and positions from Alpaca"
 * )
 *
 * @OA\Tag(
 *      name="Orders",
 *      description="Place and cancel trading orders"
 * )
 *
 * @OA\Tag(
 *      name="Equity & P&L",
 *      description="Equity curves, trades, and P&L summaries"
 * )
 *
 * @OA\Tag(
 *      name="Admin",
 *      description="Administrative operations (optimizer trigger, backtest imports)"
 * )
 */

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\Api\TickerController;
use App\Http\Controllers\Api\StrategyController;
use App\Http\Controllers\Api\AccountController;
use App\Http\Controllers\Api\OrderController;
use App\Http\Controllers\Api\EquityController;
use App\Http\Controllers\Api\AdminController;
use App\Http\Controllers\Api\BacktestTradesController;

Route::prefix('v1')->group(function () {
    Route::get('/tickers', [TickerController::class, 'index']);
    Route::post('/tickers', [AdminController::class, 'addTicker']);
    Route::delete('/tickers/{symbol}', [AdminController::class, 'removeTicker']);

    Route::get('/strategies', [StrategyController::class, 'index']);
    Route::get('/strategies/{symbol}', [StrategyController::class, 'show']);
    Route::get('/strategies/{symbol}/history', [StrategyController::class, 'optimizationHistory']);

    Route::get('/account', [AccountController::class, 'show']);
    Route::get('/account/positions', [AccountController::class, 'positions']);

    Route::post('/orders', [OrderController::class, 'place']);
    Route::delete('/orders/{orderId}', [OrderController::class, 'cancel']);

    Route::get('/equity/{symbol}', [EquityController::class, 'curve']);
    Route::get('/trades/live', [EquityController::class, 'liveTrades']);
    Route::get('/trades/backtest', [BacktestTradesController::class, 'index']);
    Route::get('/trades/pnl', [EquityController::class, 'pnlSummary']);

    Route::post('/admin/optimize/trigger', [AdminController::class, 'triggerOptimizer']);
    Route::post('/admin/import-backtest', [AdminController::class, 'importBacktestCsvs']);
});
