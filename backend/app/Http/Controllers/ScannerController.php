<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class ScannerController extends Controller
{
    private function tableForTimeframe(string $timeframe): string
    {
        return match ($timeframe) {
            'daily' => 'tbl_scanner_tickers_daily',
            '1hour' => 'tbl_scanner_tickers_1hour',
            default => 'tbl_scanner_tickers',
        };
    }

    public function index(Request $request)
    {
        $timeframe = $request->query('timeframe', 'weekly');
        $table = $this->tableForTimeframe($timeframe);

        if ($timeframe === '1hour') {
            $lookback = (int) $request->query('hours', 40);
            $interval = "INTERVAL '1 hour' * ?::int";
        } else {
            $lookback = (int) $request->query('weeks', 3);
            $interval = "INTERVAL '1 week' * ?::int";
        }

        $results = DB::select("
            WITH matched AS (
                SELECT ticker
                FROM {$table}
                WHERE date >= CURRENT_DATE - {$interval}
                GROUP BY ticker
                HAVING BOOL_OR(macd_crossover) = true
                   AND BOOL_OR(ppo_crossover) = true
            ),
            latest AS (
                SELECT DISTINCT ON (ticker)
                       ticker, date, close,
                       macd_line::float8, macd_signal::float8,
                       ppo_line::float8
                FROM {$table}
                WHERE ticker IN (SELECT ticker FROM matched)
                ORDER BY ticker, date DESC
            )
            SELECT l.*,
                   mcd.date AS macd_cross_date,
                   pcd.date AS ppo_cross_date
            FROM latest l
            LEFT JOIN LATERAL (
                SELECT date FROM {$table}
                WHERE ticker = l.ticker AND macd_crossover = true
                ORDER BY date DESC LIMIT 1
            ) mcd ON true
            LEFT JOIN LATERAL (
                SELECT date FROM {$table}
                WHERE ticker = l.ticker AND ppo_crossover = true
                ORDER BY date DESC LIMIT 1
            ) pcd ON true
            ORDER BY l.ticker
        ", [$lookback]);

        $total_scanned = DB::table($table)
            ->distinct('ticker')
            ->count('ticker');

        $latest_run = DB::table($table)
            ->max('updated_at');

        return view('scanner.index', [
            'results' => $results,
            'total_scanned' => $total_scanned,
            'total_signals' => count($results),
            'weeks' => $lookback,
            'timeframe' => $timeframe,
            'latest_run' => $latest_run,
        ]);
    }

    public function chart($ticker, Request $request)
    {
        $ticker = strtoupper($ticker);
        $timeframe = $request->query('timeframe', 'weekly');
        $table = $this->tableForTimeframe($timeframe);

        $bars = DB::select("
            SELECT date, open, high, low, close, volume
            FROM {$table}
            WHERE ticker = ?
            ORDER BY date ASC
        ", [$ticker]);

        $indicators = DB::select("
            SELECT date, macd_line::float8, macd_signal::float8, macd_histogram::float8,
                   ppo_line::float8, ppo_signal::float8, ppo_histogram::float8,
                   macd_crossover, ppo_crossover
            FROM {$table}
            WHERE ticker = ?
            ORDER BY date ASC
        ", [$ticker]);

        if (empty($bars)) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }

        $latest = DB::selectOne("
            SELECT date, close, macd_line::float8, macd_signal::float8, ppo_line::float8
            FROM {$table}
            WHERE ticker = ?
            ORDER BY date DESC LIMIT 1
        ", [$ticker]);

        return response()->json([
            'ticker' => $ticker,
            'timeframe' => $timeframe,
            'bars' => $bars,
            'indicators' => $indicators,
            'latest' => $latest,
        ]);
    }
}
