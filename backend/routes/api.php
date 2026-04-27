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
    Route::get('/admin/last-runs', [AdminController::class, 'getLastRuns']);
    Route::post('/admin/import-backtest', [AdminController::class, 'importBacktestCsvs']);
});

// OpenAPI/Swagger spec endpoint with proper schemas
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
            '/api/v1/tickers' => [
                'get' => [
                    'summary' => 'List all tickers',
                    'tags' => ['Tickers'],
                    'responses' => [
                        '200' => [
                            'description' => 'List of tickers with optimized parameters',
                            'content' => ['application/json' => []]
                        ]
                    ]
                ],
            ],
            '/api/v1/strategies' => [
                'get' => [
                    'summary' => 'List all strategies',
                    'tags' => ['Strategies'],
                    'responses' => [
                        '200' => ['description' => 'List of strategies']
                    ]
                ],
            ],
            '/api/v1/strategies/{symbol}' => [
                'get' => [
                    'summary' => 'Get strategy for ticker',
                    'tags' => ['Strategies'],
                    'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true, 'schema' => ['type' => 'string']]],
                    'responses' => [
                        '200' => ['description' => 'Strategy parameters for ticker']
                    ]
                ],
            ],
            '/api/v1/strategies/{symbol}/history' => [
                'get' => [
                    'summary' => 'Optimization history',
                    'tags' => ['Strategies'],
                    'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true, 'schema' => ['type' => 'string']]],
                    'responses' => [
                        '200' => ['description' => 'Historical optimization runs']
                    ]
                ],
            ],
            '/api/v1/account' => [
                'get' => [
                    'summary' => 'Get account info from Alpaca',
                    'tags' => ['Account'],
                    'responses' => [
                        '200' => [
                            'description' => 'Account equity, buying power, cash, portfolio value',
                            'content' => [
                                'application/json' => [
                                    'example' => [
                                        'equity' => '100000',
                                        'buying_power' => '200000',
                                        'cash' => '100000',
                                        'portfolio_value' => '100000'
                                    ]
                                ]
                            ]
                        ]
                    ]
                ],
            ],
            '/api/v1/account/positions' => [
                'get' => [
                    'summary' => 'Get open positions',
                    'tags' => ['Account'],
                    'responses' => [
                        '200' => ['description' => 'List of open positions']
                    ]
                ],
            ],
            '/api/v1/equity/{symbol}' => [
                'get' => [
                    'summary' => 'Get equity curve for ticker',
                    'tags' => ['Equity & P&L'],
                    'parameters' => [['name' => 'symbol', 'in' => 'path', 'required' => true, 'schema' => ['type' => 'string']]],
                    'responses' => [
                        '200' => ['description' => 'Equity curve data points']
                    ]
                ],
            ],
            '/api/v1/trades/live' => [
                'get' => [
                    'summary' => 'Get live trades from Alpaca',
                    'tags' => ['Equity & P&L'],
                    'responses' => [
                        '200' => ['description' => 'List of executed trades']
                    ]
                ],
            ],
            '/api/v1/trades/backtest' => [
                'get' => [
                    'summary' => 'Get backtest trades',
                    'tags' => ['Equity & P&L'],
                    'responses' => [
                        '200' => ['description' => 'List of backtest trades']
                    ]
                ],
            ],
            '/api/v1/trades/pnl' => [
                'get' => [
                    'summary' => 'Get P&L summary',
                    'tags' => ['Equity & P&L'],
                    'responses' => [
                        '200' => ['description' => 'Profit/loss summary']
                    ]
                ],
            ],
            '/api/v1/admin/optimize/trigger' => [
                'post' => [
                    'summary' => 'Trigger nightly optimizer',
                    'tags' => ['Admin'],
                    'responses' => [
                        '200' => ['description' => 'Optimizer triggered successfully']
                    ]
                ],
            ],
            '/api/v1/admin/trades/trigger' => [
                'post' => [
                    'summary' => 'Execute trades immediately',
                    'tags' => ['Admin'],
                    'responses' => [
                        '200' => ['description' => 'Trades executed']
                    ]
                ],
            ],
            '/api/v1/admin/market-status' => [
                'get' => [
                    'summary' => 'Get Alpaca market status',
                    'tags' => ['Admin'],
                    'responses' => [
                        '200' => ['description' => 'Current market status']
                    ]
                ],
            ],
            '/api/v1/admin/last-runs' => [
                'get' => [
                    'summary' => 'Get last optimizer and trades run times',
                    'tags' => ['Admin'],
                    'responses' => [
                        '200' => [
                            'description' => 'Last execution times for optimizer and trade executor',
                            'content' => [
                                'application/json' => [
                                    'example' => [
                                        'last_optimizer_run' => '2026-04-27 14:30:00',
                                        'last_trades_run' => '2026-04-27 14:35:00'
                                    ]
                                ]
                            ]
                        ]
                    ]
                ],
            ],
        ]
    ]);
});
