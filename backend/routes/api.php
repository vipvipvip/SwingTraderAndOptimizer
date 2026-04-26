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
 *      url="http://localhost:9000",
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

Route::get('/health', fn () => response()->json(['status' => 'ok']));

Route::prefix('v1')->group(function () {
    Route::get('/tickers', [TickerController::class, 'index']);
    Route::post('/tickers', [AdminController::class, 'addTicker']);
    Route::delete('/tickers/{symbol}', [AdminController::class, 'removeTicker']);
    Route::put('/tickers/{symbol}/allocation', [TickerController::class, 'updateAllocation']);

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
    Route::post('/admin/trades/trigger', [AdminController::class, 'triggerTrades']);
    Route::get('/admin/market-status', [AdminController::class, 'getMarketStatus']);
    Route::post('/admin/import-backtest', [AdminController::class, 'importBacktestCsvs']);
});

// OpenAPI/Swagger spec endpoint
Route::get('/v1/openapi.json', function () {
    return response()->json([
        'openapi' => '3.0.0',
        'info' => [
            'title' => 'Swing Trading Dashboard API',
            'description' => 'REST API for swing trading strategy management, backtesting, and live trading execution',
            'version' => '1.0.0',
            'contact' => ['name' => 'Trading Dashboard Team']
        ],
        'servers' => [
            ['url' => 'http://localhost:9000', 'description' => 'Development Server']
        ],
        'tags' => [
            ['name' => 'Tickers', 'description' => 'Manage trading tickers'],
            ['name' => 'Strategies', 'description' => 'Query optimized parameters'],
            ['name' => 'Account', 'description' => 'Account data from Alpaca'],
            ['name' => 'Orders', 'description' => 'Place and manage orders'],
            ['name' => 'Equity & P&L', 'description' => 'Performance metrics'],
            ['name' => 'Admin', 'description' => 'Administrative operations'],
        ],
        'paths' => [
            '/api/v1/health' => [
                'get' => ['summary' => 'Health check', 'tags' => ['Admin']]
            ],
            '/api/v1/tickers' => [
                'get' => ['summary' => 'List all tickers', 'tags' => ['Tickers']],
                'post' => ['summary' => 'Add ticker', 'tags' => ['Tickers']],
            ],
            '/api/v1/tickers/{symbol}' => [
                'delete' => ['summary' => 'Remove ticker', 'tags' => ['Tickers'], 'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true]]],
            ],
            '/api/v1/tickers/{symbol}/allocation' => [
                'put' => ['summary' => 'Update allocation', 'tags' => ['Tickers'], 'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true]]],
            ],
            '/api/v1/strategies' => [
                'get' => ['summary' => 'List strategies', 'tags' => ['Strategies']],
            ],
            '/api/v1/strategies/{symbol}' => [
                'get' => ['summary' => 'Get strategy for ticker', 'tags' => ['Strategies'], 'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true]]],
            ],
            '/api/v1/strategies/{symbol}/history' => [
                'get' => ['summary' => 'Optimization history', 'tags' => ['Strategies'], 'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true]]],
            ],
            '/api/v1/account' => [
                'get' => ['summary' => 'Account info', 'tags' => ['Account']],
            ],
            '/api/v1/account/positions' => [
                'get' => ['summary' => 'Current positions', 'tags' => ['Account']],
            ],
            '/api/v1/orders' => [
                'post' => ['summary' => 'Place order', 'tags' => ['Orders']],
            ],
            '/api/v1/orders/{orderId}' => [
                'delete' => ['summary' => 'Cancel order', 'tags' => ['Orders'], 'parameters' => [['name' => 'orderId', 'in' => 'path', 'required' => true]]],
            ],
            '/api/v1/equity/{symbol}' => [
                'get' => ['summary' => 'Equity curve', 'tags' => ['Equity & P&L'], 'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true]]],
            ],
            '/api/v1/trades/live' => [
                'get' => ['summary' => 'Live trades', 'tags' => ['Equity & P&L']],
            ],
            '/api/v1/trades/backtest' => [
                'get' => ['summary' => 'Backtest trades', 'tags' => ['Equity & P&L']],
            ],
            '/api/v1/trades/pnl' => [
                'get' => ['summary' => 'P&L summary', 'tags' => ['Equity & P&L']],
            ],
            '/api/v1/admin/optimize/trigger' => [
                'post' => ['summary' => 'Trigger optimizer', 'tags' => ['Admin']],
            ],
            '/api/v1/admin/trades/trigger' => [
                'post' => ['summary' => 'Execute trades', 'tags' => ['Admin']],
            ],
            '/api/v1/admin/market-status' => [
                'get' => ['summary' => 'Market status', 'tags' => ['Admin']],
            ],
            '/api/v1/admin/import-backtest' => [
                'post' => ['summary' => 'Import backtest data', 'tags' => ['Admin']],
            ],
        ]
    ]);
});
