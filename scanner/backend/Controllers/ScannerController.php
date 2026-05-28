<?php

namespace Scanner\Backend\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class ScannerController
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

        $results = DB::select("
            WITH cross_dates AS (
                SELECT DISTINCT ON (ticker)
                       ticker,
                       mcd.date AS macd_cross_date,
                       pcd.date AS ppo_cross_date,
                       scd.date AS sma_cross_date,
                       lc.cross_bullish
                FROM {$table} t
                LEFT JOIN LATERAL (
                    SELECT date FROM {$table}
                    WHERE ticker = t.ticker AND macd_crossover = true
                    ORDER BY date DESC LIMIT 1
                ) mcd ON true
                LEFT JOIN LATERAL (
                    SELECT date FROM {$table}
                    WHERE ticker = t.ticker AND ppo_crossover = true
                    ORDER BY date DESC LIMIT 1
                ) pcd ON true
                LEFT JOIN LATERAL (
                    SELECT date FROM {$table}
                    WHERE ticker = t.ticker AND sma_crossover = true
                    ORDER BY date DESC LIMIT 1
                ) scd ON true
                LEFT JOIN LATERAL (
                    SELECT
                        CASE WHEN macd_crossover OR ppo_crossover OR sma_crossover
                             THEN true ELSE false
                        END AS cross_bullish
                    FROM {$table}
                    WHERE ticker = t.ticker
                      AND (macd_crossover OR macd_cross_bearish
                           OR ppo_crossover OR ppo_cross_bearish
                           OR sma_crossover OR sma_cross_bearish)
                    ORDER BY date DESC LIMIT 1
                ) lc ON true
                WHERE mcd.date IS NOT NULL
                  AND pcd.date IS NOT NULL
                  AND scd.date IS NOT NULL
            ),
            latest AS (
                SELECT DISTINCT ON (ticker)
                       ticker, date, close,
                       atr_stop::float8
                FROM {$table}
                WHERE ticker IN (SELECT ticker FROM cross_dates)
                ORDER BY ticker, date DESC
            )
            SELECT l.*,
                   cd.macd_cross_date,
                   cd.ppo_cross_date,
                   cd.sma_cross_date,
                   cd.cross_bullish
            FROM latest l
            JOIN cross_dates cd USING (ticker)
            ORDER BY GREATEST(cd.macd_cross_date, cd.ppo_cross_date, cd.sma_cross_date) DESC
        ");

        $results = collect($results)
            ->filter(fn($r) => $r->cross_bullish && $r->atr_stop !== null)
            ->take(50)
->map(function ($r) {
                $dist = (float)$r->close - (float)$r->atr_stop;
                $r->stop_dist_dollar = round($dist, 2);
                $r->stop_dist_pct = (float)$r->close > 0
                    ? round($dist / (float)$r->close * 100, 2)
                    : null;
                return $r;
            })
            ->sortBy('stop_dist_pct')
            ->values()
            ->all();

        $total_scanned = DB::table($table)
            ->distinct('ticker')
            ->count('ticker');

        $all_tickers = DB::table($table)
            ->distinct('ticker')
            ->orderBy('ticker')
            ->pluck('ticker');

        $latest_run = DB::table($table)
            ->max('updated_at');

        return view('scanner.index', [
            'results' => $results,
            'all_tickers' => $all_tickers,
            'total_scanned' => $total_scanned,
            'total_signals' => count($results),
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
                   macd_crossover, ppo_crossover, sma_crossover,
                   hmm_regime, hmm_bull_prob::float8, hmm_bear_prob::float8,
                   hmm_choppy_prob::float8
            FROM {$table}
            WHERE ticker = ?
            ORDER BY date ASC
        ", [$ticker]);

        if (empty($bars)) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }

        $latest = DB::selectOne("
            SELECT date, close, macd_line::float8, macd_signal::float8, ppo_line::float8,
                   atr_stop::float8
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
