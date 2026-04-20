<?php

/**
 * @OA\Info(
 *      title="Swing Trading Dashboard API",
 *      description="REST API for swing trading strategy management, backtesting, and live trading execution",
 *      version="1.0.0",
 *      contact={
 *          "name": "Trading Dashboard Team",
 *          "url": "http://localhost:5173"
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

namespace App\Http\Controllers\Api;

// This file exists only to hold the main OpenAPI info block
