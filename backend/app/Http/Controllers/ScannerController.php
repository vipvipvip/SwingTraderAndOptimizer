<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class ScannerController extends Controller
{
    public function index(Request $request)
    {
        $weeks = (int) $request->query('weeks', 3);

        $results = DB::select("
            WITH matched AS (
                SELECT ticker
                FROM tbl_scanner_tickers
                WHERE date >= CURRENT_DATE - INTERVAL '1 week' * ?::int
                GROUP BY ticker
                HAVING BOOL_OR(macd_crossover) = true
                   AND BOOL_OR(ppo_crossover) = true
            ),
            latest AS (
                SELECT DISTINCT ON (ticker)
                       ticker, date, close,
                       macd_line::float8, macd_signal::float8,
                       ppo_line::float8
                FROM tbl_scanner_tickers
                WHERE ticker IN (SELECT ticker FROM matched)
                ORDER BY ticker, date DESC
            )
            SELECT l.*,
                   mcd.date AS macd_cross_date,
                   pcd.date AS ppo_cross_date
            FROM latest l
            LEFT JOIN LATERAL (
                SELECT date FROM tbl_scanner_tickers
                WHERE ticker = l.ticker AND macd_crossover = true
                ORDER BY date DESC LIMIT 1
            ) mcd ON true
            LEFT JOIN LATERAL (
                SELECT date FROM tbl_scanner_tickers
                WHERE ticker = l.ticker AND ppo_crossover = true
                ORDER BY date DESC LIMIT 1
            ) pcd ON true
            ORDER BY l.ticker
        ", [$weeks]);

        $total_scanned = DB::table('tbl_scanner_tickers')
            ->distinct('ticker')
            ->count('ticker');

        $latest_run = DB::table('tbl_scanner_tickers')
            ->max('updated_at');

        return view('scanner.index', [
            'results' => $results,
            'total_scanned' => $total_scanned,
            'total_signals' => count($results),
            'weeks' => $weeks,
            'latest_run' => $latest_run,
        ]);
    }

    public function chart($ticker)
    {
        $ticker = strtoupper($ticker);

        $bars = DB::select("
            SELECT date, open, high, low, close, volume
            FROM tbl_scanner_tickers
            WHERE ticker = ?
            ORDER BY date ASC
        ", [$ticker]);

        $indicators = DB::select("
            SELECT date, macd_line::float8, macd_signal::float8, macd_histogram::float8,
                   ppo_line::float8, ppo_signal::float8, ppo_histogram::float8,
                   macd_crossover, ppo_crossover
            FROM tbl_scanner_tickers
            WHERE ticker = ?
            ORDER BY date ASC
        ", [$ticker]);

        if (empty($bars)) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }

        $latest = DB::selectOne("
            SELECT date, close, macd_line::float8, macd_signal::float8, ppo_line::float8
            FROM tbl_scanner_tickers
            WHERE ticker = ?
            ORDER BY date DESC LIMIT 1
        ", [$ticker]);

        return response()->json([
            'ticker' => $ticker,
            'bars' => $bars,
            'indicators' => $indicators,
            'latest' => $latest,
        ]);
    }
}
