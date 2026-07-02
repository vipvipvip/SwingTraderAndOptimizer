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
        $undervalued = $request->boolean('undervalued');
        $weeklyCrossover = $request->boolean('weekly_crossover');
        $long = $request->boolean('long');
        $short = $request->boolean('short');

        if ($undervalued) {
            return $this->indexUndervalued($request, $timeframe, $table);
        }

        if ($weeklyCrossover) {
            return $this->indexWeeklyCrossover($request, $timeframe, $table);
        }

        if ($short) {
            return $this->indexShort($request, $timeframe, $table);
        }

        // Default to Long mode
        return $this->indexLong($request, $timeframe, $table);
    }

    private function indexUndervalued(Request $request, string $timeframe, string $table)
    {
        $results = DB::select("
            SELECT st.symbol AS ticker,
                   st.company_name AS db_company_name,
                   sa.db_revenue,
                   sa.db_net_income,
                   sa.db_eps,
                   sa.db_shares_outstanding,
                   sa.db_pe_ratio,
                   sa.db_close,
                   sa.db_valuation_price,
                   ROUND((sa.db_valuation_price - sa.db_close) / sa.db_close * 100, 2) AS upside_pct
            FROM tbl_stock_analyzer sa
            JOIN tbl_stock_tickers st ON st.id = sa.ticker_id
            WHERE sa.db_valuation_price > sa.db_close
              AND sa.db_valuation_price > 0
              AND sa.db_close > 0
            ORDER BY (sa.db_valuation_price - sa.db_close) / sa.db_close DESC
        ");

        $latest_run = DB::table('tbl_stock_analyzer')->max('date');

        $all_tickers = array_map(fn($r) => $r->ticker, $results);
        sort($all_tickers);

        return view('scanner.index', [
            'results' => $results,
            'total_scanned' => count($results),
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => $latest_run,
            'all_tickers' => $all_tickers,
            'undervalued' => true,
            'weekly_crossover' => false,
        ]);
    }

    private function indexWeeklyCrossover(Request $request, string $timeframe, string $table)
    {
        $tickerIds = DB::table($table)
            ->distinct('ticker_id')
            ->pluck('ticker_id');

        if ($tickerIds->isEmpty()) {
            $total_scanned = 0;
            $latest_run = DB::table($table)->max('updated_at');
            return view('scanner.index', [
                'results' => [], 'total_scanned' => 0, 'total_signals' => 0,
                'timeframe' => $timeframe, 'latest_run' => $latest_run,
                'all_tickers' => [], 'weekly_crossover' => true, 'undervalued' => false,
            ]);
        }

        $tickerList = $tickerIds->toArray();

        $barsRaw = DB::table($table)
            ->whereIn('ticker_id', $tickerList)
            ->orderBy('ticker_id')
            ->orderBy('date')
            ->select('ticker_id', 'date', DB::raw('close::float8 as close'))
            ->get();

        $emaByTicker = [];
        $closeByTicker = [];
        $K = 2 / (10 + 1);
        $iterations = 80;

        foreach ($barsRaw as $b) {
            $tid = $b->ticker_id;
            $close = (float)$b->close;
            $closeByTicker[$tid] = $close;
            if (!isset($emaByTicker[$tid])) {
                $emaByTicker[$tid] = $close;
                continue;
            }
            $count = 0;
            $ema = $emaByTicker[$tid];
            foreach ([$close] as $c) {
                $ema = $c * $K + $ema * (1 - $K);
            }
            $emaByTicker[$tid] = $ema;
        }

        $smaRaw = DB::select("
            SELECT DISTINCT ON (t.ticker_id)
                   t.ticker_id,
                   AVG(t.close::float8) OVER (
                       PARTITION BY t.ticker_id
                       ORDER BY t.date
                       ROWS BETWEEN 39 PRECEDING AND CURRENT ROW
                   ) AS sma40
            FROM {$table} t
            ORDER BY t.ticker_id, t.date DESC
        ");

        $smaByTicker = [];
        foreach ($smaRaw as $r) {
            if ($r->sma40 !== null) {
                $smaByTicker[$r->ticker_id] = (float)$r->sma40;
            }
        }

        $crossStatusRaw = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   CASE WHEN ema10_sma40_crossover THEN 'Bullish'
                        WHEN ema10_sma40_cross_bearish THEN 'Bearish'
                        ELSE 'Neutral' END AS cross_status,
                   (SELECT date FROM {$table} t2
                    WHERE t2.ticker_id = t.ticker_id AND t2.ema10_sma40_crossover = true
                    ORDER BY t2.date DESC LIMIT 1) AS last_cross_date,
                   (SELECT date FROM {$table} t2
                    WHERE t2.ticker_id = t.ticker_id AND t2.ema10_sma40_cross_bearish = true
                    ORDER BY t2.date DESC LIMIT 1) AS last_bearish_date
            FROM {$table} t
            WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
            ORDER BY ticker_id, date DESC
        ");

        $crossByTicker = [];
        foreach ($crossStatusRaw as $r) {
            $crossByTicker[$r->ticker_id] = $r;
        }

        $tickerInfo = DB::table('tbl_stock_tickers')
            ->whereIn('id', $tickerList)
            ->select('id', 'symbol', 'company_name')
            ->get()
            ->keyBy('id');

        $indicatorRaw = DB::select("
            SELECT ticker_id, date,
                   macd_histogram::float8,
                   ppo_histogram::float8
            FROM (
                SELECT ticker_id, date,
                       macd_histogram, ppo_histogram,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker_id ORDER BY date DESC
                       ) AS rn
                FROM {$table}
            ) sub
            WHERE rn <= 2
            ORDER BY ticker_id, date DESC
        ");

        $indicatorByTicker = [];
        foreach ($indicatorRaw as $r) {
            $tid = $r->ticker_id;
            if (!isset($indicatorByTicker[$tid])) {
                $indicatorByTicker[$tid] = (object)[
                    'current' => (float)$r->macd_histogram,
                    'prev' => null,
                    'ppo_current' => (float)$r->ppo_histogram,
                    'ppo_prev' => null,
                ];
            } else {
                $indicatorByTicker[$tid]->prev = (float)$r->macd_histogram;
                $indicatorByTicker[$tid]->ppo_prev = (float)$r->ppo_histogram;
            }
        }

        $results = [];
        foreach ($tickerList as $tid) {
            if (!isset($smaByTicker[$tid])) continue;
            $info = $tickerInfo->get($tid);
            if (!$info) continue;

            $close = $closeByTicker[$tid] ?? null;
            $sma40 = $smaByTicker[$tid];
            $ema10 = $emaByTicker[$tid] ?? null;
            $cross = $crossByTicker[$tid] ?? null;
            $ind = $indicatorByTicker[$tid] ?? null;

            if ($close === null || $ema10 === null) continue;

            $gapPct = $sma40 > 0 ? (($close - $sma40) / $sma40) * 100 : 0;
            $spreadClose = abs($close - $sma40);
            $spreadEma = abs($ema10 - $sma40);
            $spreadCloseEma = abs($close - $ema10);
            $maxSpread = max($spreadClose, $spreadEma, $spreadCloseEma);
            $convergencePct = $sma40 > 0 ? ($maxSpread / $sma40) * 100 : PHP_FLOAT_MAX;

            $macdHist = $ind ? $ind->current : 0;
            $ppoHist = $ind ? $ind->ppo_current : 0;
            $macdRising = $ind && $ind->prev !== null && $ind->current > $ind->prev;
            $ppoRising = $ind && $ind->ppo_prev !== null && $ind->ppo_current > $ind->ppo_prev;

            $momentumScore = 0;
            if ($macdRising) $momentumScore += 3;
            if ($ppoRising) $momentumScore += 3;
            if ($macdHist > 0) $momentumScore += 1;
            if ($ppoHist > 0) $momentumScore += 1;

            $obj = (object)[
                'ticker' => $info->symbol,
                'company_name' => $info->company_name,
                'close' => round($close, 2),
                'sma40' => round($sma40, 2),
                'ema10' => round($ema10, 2),
                'gap_pct' => round($gapPct, 2),
                'convergence_pct' => round($convergencePct, 2),
                'macd_hist' => round($macdHist, 4),
                'ppo_hist' => round($ppoHist, 4),
                'momentum_score' => $momentumScore,
                'status' => $cross ? $cross->cross_status : 'Neutral',
                'last_cross_date' => $cross->last_cross_date ?? null,
                'last_bearish_date' => $cross->last_bearish_date ?? null,
            ];
            $results[] = $obj;
        }

        usort($results, function ($a, $b) {
            $ms = $b->momentum_score <=> $a->momentum_score;
            if ($ms !== 0) return $ms;
            return $a->convergence_pct <=> $b->convergence_pct;
        });

        $total_scanned = count($tickerList);
        $all_tickers = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->orderBy('symbol')
            ->pluck('symbol');
        $latest_run = DB::table($table)->max('updated_at');

        return view('scanner.index', [
            'results' => $results,
            'total_scanned' => $total_scanned,
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => $latest_run,
            'all_tickers' => $all_tickers,
            'weekly_crossover' => true,
            'undervalued' => false,
        ]);
    }

    private function indexLong(Request $request, string $timeframe, string $table)
    {
        $rows = DB::select("
            WITH ranked AS (
                SELECT t.ticker_id, t.date,
                       t.close::float8 AS close,
                       t.macd_histogram::float8 AS macd_hist,
                       t.ppo_histogram::float8 AS ppo_hist,
                       t.atr_stop::float8 AS atr_stop,
                       (t.macd_line::float8 - t.macd_signal::float8) AS macd_ms,
                       ROW_NUMBER() OVER (PARTITION BY t.ticker_id ORDER BY t.date DESC) AS rn
                FROM {$table} t
            ),
            curr AS (SELECT * FROM ranked WHERE rn = 1),
            prev AS (SELECT * FROM ranked WHERE rn = 2)
            SELECT c.ticker_id, c.date,
                   c.close, c.macd_hist, c.ppo_hist, c.atr_stop, c.macd_ms,
                   COALESCE(p.macd_hist, 0) AS prev_macd_hist,
                   COALESCE(p.ppo_hist, 0) AS prev_ppo_hist,
                   e.symbol AS ticker, e.company_name
            FROM curr c
            LEFT JOIN prev p ON p.ticker_id = c.ticker_id
            JOIN tbl_stock_tickers e ON e.id = c.ticker_id
            WHERE c.close > c.atr_stop
              AND c.atr_stop IS NOT NULL
              AND c.close > 0
        ");

        $results = [];

        foreach ($rows as $r) {
            $r->stop_dist_pct = round(($r->close - $r->atr_stop) / $r->close * 100, 2);

            // MACD just crossed above zero: histogram went from <=0 to >0
            $macdCross = $r->macd_hist > 0 && $r->prev_macd_hist <= 0;

            // PPO just crossed above zero: histogram went from <=0 to >0
            $ppoCross = $r->ppo_hist > 0 && $r->prev_ppo_hist <= 0;

            if (!$macdCross && !$ppoCross) continue;

            if ($macdCross && $ppoCross) {
                $r->rule = 1; // Both crossed simultaneously — double confirmation
            } elseif ($macdCross) {
                $r->rule = 2; // MACD leading
            } else {
                $r->rule = 3; // PPO leading
            }

            $r->score = ($macdCross ? 5 : 0) + ($ppoCross ? 5 : 0)
                      + min(5, max(0, (int)$r->stop_dist_pct));

            $results[] = $r;
        }

        usort($results, fn($a, $b) =>
            $a->rule <=> $b->rule ?: $b->score <=> $a->score ?: $b->macd_hist <=> $a->macd_hist
        );

        $all_tickers = DB::table('tbl_stock_tickers')
            ->where('enabled', true)->orderBy('symbol')->pluck('symbol');

        return view('scanner.index', [
            'results' => $results,
            'all_tickers' => $all_tickers,
            'total_scanned' => DB::table($table)->distinct('ticker_id')->count('ticker_id'),
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => DB::table($table)->max('updated_at'),
            'long' => true, 'short' => false,
            'undervalued' => false, 'weekly_crossover' => false,
        ]);
    }

    private function indexShort(Request $request, string $timeframe, string $table)
    {
        $rows = DB::select("
            WITH ranked AS (
                SELECT t.ticker_id, t.date,
                       t.close::float8 AS close,
                       t.macd_histogram::float8 AS macd_hist,
                       t.ppo_histogram::float8 AS ppo_hist,
                       t.atr_stop::float8 AS atr_stop,
                       (t.macd_line::float8 - t.macd_signal::float8) AS macd_ms,
                       ROW_NUMBER() OVER (PARTITION BY t.ticker_id ORDER BY t.date DESC) AS rn
                FROM {$table} t
            ),
            curr AS (SELECT * FROM ranked WHERE rn = 1),
            prev AS (SELECT * FROM ranked WHERE rn = 2)
            SELECT c.ticker_id, c.date,
                   c.close, c.macd_hist, c.ppo_hist, c.atr_stop, c.macd_ms,
                   COALESCE(p.macd_hist, 0) AS prev_macd_hist,
                   COALESCE(p.ppo_hist, 0) AS prev_ppo_hist,
                   e.symbol AS ticker, e.company_name
            FROM curr c
            LEFT JOIN prev p ON p.ticker_id = c.ticker_id
            JOIN tbl_stock_tickers e ON e.id = c.ticker_id
            WHERE c.macd_hist > 0
              AND c.ppo_hist <= 0
              AND c.close > 0
        ");

        $results = [];

        foreach ($rows as $r) {
            // Rule 3: Momentum Breaker — MACD still positive but PPO just turned negative or is negative
            $r->stop_dist_pct = $r->atr_stop > 0
                ? round(($r->close - $r->atr_stop) / $r->close * 100, 2)
                : null;

            // Cusp: PPO just turned negative (was positive last week) OR has been barely negative
            $ppeJustBroke = $r->prev_ppo_hist > 0;

            if (!$ppeJustBroke) continue;

            $r->rule = 3;
            $r->score = (int)(abs($r->ppo_hist) * 10) + ($r->macd_ms > 0 ? 3 : 0);

            $results[] = $r;
        }

        usort($results, fn($a, $b) => $b->score <=> $a->score ?: $a->ppo_hist <=> $b->ppo_hist);

        $all_tickers = DB::table('tbl_stock_tickers')
            ->where('enabled', true)->orderBy('symbol')->pluck('symbol');

        return view('scanner.index', [
            'results' => $results,
            'all_tickers' => $all_tickers,
            'total_scanned' => DB::table($table)->distinct('ticker_id')->count('ticker_id'),
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => DB::table($table)->max('updated_at'),
            'long' => false, 'short' => true,
            'undervalued' => false, 'weekly_crossover' => false,
        ]);
    }

    public function updateValuations()
    {
        $script = base_path('../../stock-analyzer/populate_stock_analyzer.py');
        $python = base_path('../../stock-analyzer/.venv/bin/python3');

        $cmd = escapeshellcmd($python) . ' ' . escapeshellarg($script) . ' --valuation 2>&1';

        $output = [];
        $exitCode = 0;
        exec($cmd, $output, $exitCode);

        $outputStr = implode("\n", $output);

        return response()->json([
            'success' => $exitCode === 0,
            'exit_code' => $exitCode,
            'output' => $outputStr,
        ]);
    }

    public function chart($symbol, Request $request)
    {
        $symbol = strtoupper($symbol);
        $timeframe = $request->query('timeframe', 'weekly');
        $table = $this->tableForTimeframe($timeframe);

        $tickerId = DB::table('tbl_stock_tickers')
            ->where('symbol', $symbol)
            ->value('id');

        if (!$tickerId) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }

        $bars = DB::select("
            SELECT date, open, high, low, close, volume
            FROM {$table}
            WHERE ticker_id = ?
            ORDER BY date ASC
        ", [$tickerId]);

        $indicators = DB::select("
            SELECT date, macd_line::float8, macd_signal::float8, macd_histogram::float8,
                   ppo_line::float8, ppo_signal::float8, ppo_histogram::float8,
                   macd_crossover, ppo_crossover, sma_crossover
            FROM {$table}
            WHERE ticker_id = ?
            ORDER BY date ASC
        ", [$tickerId]);

        if (empty($bars)) {
            return response()->json(['error' => 'Ticker not found'], 404);
        }

        $latest = DB::selectOne("
            SELECT date, close, macd_line::float8, macd_signal::float8, ppo_line::float8,
                   atr_stop::float8
            FROM {$table}
            WHERE ticker_id = ?
            ORDER BY date DESC LIMIT 1
        ", [$tickerId]);

        return response()->json([
            'ticker' => $symbol,
            'timeframe' => $timeframe,
            'bars' => $bars,
            'indicators' => $indicators,
            'latest' => $latest,
        ]);
    }
}
