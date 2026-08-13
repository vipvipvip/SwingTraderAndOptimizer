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
        $long = $request->boolean('long');
        $short = $request->boolean('short');
        $multitfUptrend = $request->boolean('multitf_uptrend');
        $infancy = $request->boolean('infancy');

        $breadth = $this->getMarketBreadth();

        if ($undervalued) {
            return $this->indexUndervalued($request, $timeframe, $table, $breadth);
        }

        if ($multitfUptrend) {
            return $this->indexMultiTfUptrend($request, $timeframe, $table, $infancy, $breadth);
        }

        if ($short) {
            return $this->indexShort($request, $timeframe, $table, $breadth);
        }

        // Default to Long mode
        return $this->indexLong($request, $timeframe, $table, $breadth);
    }

    private function getMarketBreadth(): array
    {
        // NOTE: ema10_sma40_crossover / ema10_sma40_cross_bearish columns are never
        // populated by the pipeline — breadth must be computed inline via window functions.
        // ROW_NUMBER + FILTER (last-40 bars only) avoids expensive sliding frames (1.6s cold).
        // Cached in a file so index/explorer loads don't recompute per request.
        $cacheFile = storage_path('framework/cache/breadth.json');
        $cacheTtl = 300; // 5 min
        if (file_exists($cacheFile) && time() - filemtime($cacheFile) < $cacheTtl) {
            return json_decode(file_get_contents($cacheFile), true);
        }

        $row = DB::selectOne("
            WITH wk AS (
                SELECT ticker_id,
                       MAX(CASE WHEN rnd = 1 THEN close END) AS close,
                       AVG(close::float8) FILTER (WHERE rnd <= 40) AS sma40
                FROM (
                    SELECT ticker_id, date, close::float8 AS close,
                           ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                    FROM tbl_scanner_tickers
                ) sub
                WHERE rnd <= 40
                GROUP BY ticker_id
            ),
            dy AS (
                SELECT ticker_id,
                       MAX(CASE WHEN rnd = 1 THEN close END) AS close,
                       AVG(close::float8) FILTER (WHERE rnd <= 40) AS sma40
                FROM (
                    SELECT ticker_id, date, close::float8 AS close,
                           ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                    FROM tbl_scanner_tickers_daily
                ) sub
                WHERE rnd <= 40
                GROUP BY ticker_id
            )
            SELECT COUNT(*) FILTER (WHERE wk.close > wk.sma40 AND dy.close > dy.sma40) AS cnt,
                   COUNT(*) AS total
            FROM wk
            JOIN dy ON dy.ticker_id = wk.ticker_id
            JOIN tbl_stock_tickers s ON s.id = wk.ticker_id
            WHERE s.is_etf = false AND s.enabled = true
        ");
        $total = (int)($row->total ?? 0);
        $uptrend = (int)($row->cnt ?? 0);
        $pct = $total > 0 ? (int)round($uptrend / $total * 100) : 0;
        if ($pct < 35) {
            $regime = 'Risk-off';
            $color = '#f85149';
        } elseif ($pct > 54) {
            $regime = 'Risk-on';
            $color = '#3fb950';
        } else {
            $regime = 'Neutral';
            $color = '#d29922';
        }
        $result = ['pct' => $pct, 'regime' => $regime, 'color' => $color];
        @file_put_contents($cacheFile, json_encode($result));
        return $result;
    }

    private function indexUndervalued(Request $request, string $timeframe, string $table, array $breadth = [])
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

        return view('scanner.index', array_merge([
            'results' => $results,
            'total_scanned' => count($results),
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => $latest_run,
            'all_tickers' => $all_tickers,
            'undervalued' => true,
        ], $breadth));
    }

    private function indexLong(Request $request, string $timeframe, string $table, array $breadth = [])
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

        return view('scanner.index', array_merge([
            'results' => $results,
            'all_tickers' => $all_tickers,
            'total_scanned' => DB::table($table)->distinct('ticker_id')->count('ticker_id'),
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => DB::table($table)->max('updated_at'),
            'long' => true, 'short' => false,
            'undervalued' => false,
        ], $breadth));
    }

    private function indexShort(Request $request, string $timeframe, string $table, array $breadth = [])
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

        return view('scanner.index', array_merge([
            'results' => $results,
            'all_tickers' => $all_tickers,
            'total_scanned' => DB::table($table)->distinct('ticker_id')->count('ticker_id'),
            'total_signals' => count($results),
            'timeframe' => $timeframe,
            'latest_run' => DB::table($table)->max('updated_at'),
            'long' => false, 'short' => true,
            'undervalued' => false,
        ], $breadth));
    }

    private function indexMultiTfUptrend(Request $request, string $timeframe, string $table, bool $infancyOnly = false, array $breadth = [])
    {
        $today = now()->format('Y-m-d');

        // Heavy computation cached 5 min; infancy is a light post-filter so
        // cache the full scored set and filter after.
        $cacheFile = storage_path('framework/cache/multitf_index.json');
        $cacheTtl = 300;
        $results = null;
        if (file_exists($cacheFile) && time() - filemtime($cacheFile) < $cacheTtl) {
            $results = json_decode(file_get_contents($cacheFile), true);
        }
        if ($results === null) {
            $results = $this->computeMultiTfResults();
            @file_put_contents($cacheFile, json_encode($results), LOCK_EX);
        }

        if ($infancyOnly) {
            $results = array_values(array_filter($results, fn($r) => $r['infancy']));
        }

        $resultObjs = array_map(function ($r) use ($today) {
            return (object)[
                'ticker' => $r['ticker'],
                'company_name' => $r['name'],
                'close' => $r['close'],
                'weekly_cross_date' => $r['weekly_cross_date'],
                'daily_cross_date' => $r['daily_cross_date'],
                'hourly_entry' => $r['hourly_entry'],
                'new_daily_uptrend' => $r['new_daily_uptrend'],
                'score' => $r['score'],
                'gap_w' => $r['gap_w'],
                'atr_dist' => $r['atr_dist'],
                'infancy' => $r['infancy'],
                'days_weekly' => $r['days_weekly'],
            ];
        }, $results);

        // Sort: infancy first, then by score descending, entry signals on top
        usort($resultObjs, function ($a, $b) {
            if ($a->infancy !== $b->infancy) return $b->infancy <=> $a->infancy;
            if ($a->hourly_entry !== $b->hourly_entry) return $b->hourly_entry <=> $a->hourly_entry;
            return $b->score <=> $a->score;
        });

        $all_tickers = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->orderBy('symbol')
            ->pluck('symbol');

        return view('scanner.index', array_merge([
            'results' => $resultObjs,
            'total_scanned' => DB::table('tbl_stock_tickers')->where('enabled', true)->where('is_etf', false)->count(),
            'total_signals' => count($resultObjs),
            'timeframe' => $timeframe,
            'latest_run' => now(),
            'all_tickers' => $all_tickers,
            'multitf_uptrend' => true,
            'infancy' => $infancyOnly,
            'undervalued' => false,
            'long' => false,
            'short' => false,
        ], $breadth));
    }

    /**
     * Score all enabled non-ETF stocks with the production Multi-TF logic
     * (mirrors swingtrader/services/mtf/runner.py _compute_score).
     * EMA10/SMA40 are computed inline via ROW_NUMBER + GROUP BY + FILTER —
     * the ema10_sma40_* DB columns are stale (last populated 2026-06-25).
     */
    private function computeMultiTfResults()
    {
        $today = now()->format('Y-m-d');

        $tickerInfo = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->where('is_etf', false)
            ->select('id', 'symbol', 'company_name')
            ->get()
            ->keyBy('id');

        // Weekly latest close, SMA40, EMA10 (SMA10 proxy, same as explorer)
        $weeklyData = DB::select("
            SELECT ticker_id,
                   MAX(CASE WHEN rnd = 1 THEN close END) AS close,
                   AVG(close::float8) FILTER (WHERE rnd <= 40) AS sma40,
                   AVG(close::float8) FILTER (WHERE rnd <= 10) AS ema10
            FROM (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers
            ) sub
            WHERE rnd <= 40
            GROUP BY ticker_id
        ");
        $weeklyById = [];
        foreach ($weeklyData as $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $weeklyById[$r->ticker_id] = $r;
            }
        }

        // Daily latest close, SMA40, EMA10
        $dailyData = DB::select("
            SELECT ticker_id,
                   MAX(CASE WHEN rnd = 1 THEN close END) AS close,
                   AVG(close::float8) FILTER (WHERE rnd <= 40) AS sma40,
                   AVG(close::float8) FILTER (WHERE rnd <= 10) AS ema10
            FROM (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers_daily
            ) sub
            WHERE rnd <= 40
            GROUP BY ticker_id
        ");
        $dailyById = [];
        foreach ($dailyData as $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $dailyById[$r->ticker_id] = $r;
            }
        }

        // Latest + previous hourly bar (close, ATR stop) for the ATR filter
        // and a fresh ATR-break detection.
        $hourlyBars = DB::select("
            WITH ranked AS (
                SELECT ticker_id, date, close::float8 AS close, atr_stop::float8 AS atr_stop,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
                FROM tbl_scanner_tickers_1hour
            )
            SELECT c.ticker_id, c.close AS close, c.atr_stop AS atr_stop,
                   p.close AS prev_close, p.atr_stop AS prev_atr_stop
            FROM ranked c
            LEFT JOIN ranked p ON p.ticker_id = c.ticker_id AND p.rn = 2
            WHERE c.rn = 1
        ");
        $hourlyById = [];
        foreach ($hourlyBars as $r) {
            $hourlyById[$r->ticker_id] = $r;
        }

        // Weekly cross date: close crosses above SMA40 within last 60 bars
        $weeklyCross = DB::select("
            WITH ranked AS (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers
            ),
            sma AS (
                SELECT ticker_id, date, close,
                       AVG(close) OVER (PARTITION BY ticker_id ORDER BY date ASC ROWS BETWEEN 39 PRECEDING AND CURRENT ROW) AS sma40
                FROM ranked WHERE rnd <= 60
            ),
            sma2 AS (
                SELECT ticker_id, date, close, sma40,
                       LAG(close) OVER (PARTITION BY ticker_id ORDER BY date ASC) AS prev_close,
                       LAG(sma40) OVER (PARTITION BY ticker_id ORDER BY date ASC) AS prev_sma40
                FROM sma
            )
            SELECT DISTINCT ON (ticker_id) ticker_id, date
            FROM sma2
            WHERE close > sma40 AND prev_close <= prev_sma40
            ORDER BY ticker_id, date DESC
        ");
        $weeklyCrossDateById = [];
        foreach ($weeklyCross as $r) {
            $weeklyCrossDateById[$r->ticker_id] = $r->date;
        }

        // Daily cross date: close crosses above SMA40 within last 60 bars
        $dailyCross = DB::select("
            WITH ranked AS (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers_daily
            ),
            sma AS (
                SELECT ticker_id, date, close,
                       AVG(close) OVER (PARTITION BY ticker_id ORDER BY date ASC ROWS BETWEEN 39 PRECEDING AND CURRENT ROW) AS sma40
                FROM ranked WHERE rnd <= 60
            ),
            sma2 AS (
                SELECT ticker_id, date, close, sma40,
                       LAG(close) OVER (PARTITION BY ticker_id ORDER BY date ASC) AS prev_close,
                       LAG(sma40) OVER (PARTITION BY ticker_id ORDER BY date ASC) AS prev_sma40
                FROM sma
            )
            SELECT DISTINCT ON (ticker_id) ticker_id, date
            FROM sma2
            WHERE close > sma40 AND prev_close <= prev_sma40
            ORDER BY ticker_id, date DESC
        ");
        $dailyCrossDateById = [];
        foreach ($dailyCross as $r) {
            $dailyCrossDateById[$r->ticker_id] = $r->date;
        }

        $results = [];
        foreach ($tickerInfo as $tid => $info) {
            $w = $weeklyById[$tid] ?? null;
            $d = $dailyById[$tid] ?? null;
            $h = $hourlyById[$tid] ?? null;
            if (!$w || !$d || !$h) continue;

            $ema10w = (float)$w->ema10;
            $sma40w = (float)$w->sma40;
            $ema10d = (float)$d->ema10;
            $sma40d = (float)$d->sma40;
            $closeH = (float)$h->close;
            $atrH = (float)$h->atr_stop;

            // Production filters: weekly EMA10>SMA40, daily EMA10>SMA40,
            // hourly close > hourly ATR stop (runner.py:242-244).
            if (!$ema10w || $ema10w <= $sma40w || !$ema10d || $ema10d <= $sma40d) continue;
            if (!$atrH || $atrH <= 0 || $closeH <= $atrH) continue;

            $weeklyClose = (float)$w->close;
            $gapW = ($weeklyClose - $sma40w) / $sma40w * 100;
            $atrDist = ($closeH - $atrH) / $closeH * 100;

            $weeklyCrossDate = $weeklyCrossDateById[$tid] ?? null;
            $dailyCrossDate = $dailyCrossDateById[$tid] ?? null;
            $daysSinceWeekly = 999;
            if ($weeklyCrossDate) {
                $daysSinceWeekly = (new \DateTime($weeklyCrossDate))->diff(new \DateTime())->days;
            }

            // Fresh hourly ATR break: current close above stop, previous not
            $hourlyEntry = $closeH > $atrH
                && (($h->prev_close ?? 0) <= ($h->prev_atr_stop ?? PHP_FLOAT_MAX));

            $score = 0;
            $score += min($gapW / 20, 3);                // weekly gap: 0-3 pts
            $score += min($atrDist / 1.5, 3);             // ATR distance: 0-3 pts
            $score += max(0, 2 - $daysSinceWeekly / 60);  // freshness: 0-2 pts
            $score = round($score, 1);

            $results[] = [
                'ticker' => $info->symbol,
                'name' => $info->company_name,
                'close' => round($weeklyClose, 2),
                'weekly_cross_date' => $weeklyCrossDate,
                'daily_cross_date' => $dailyCrossDate,
                'hourly_entry' => $hourlyEntry,
                'new_daily_uptrend' => $dailyCrossDate === $today,
                'score' => $score,
                'gap_w' => round($gapW, 1),
                'atr_dist' => round($atrDist, 1),
                'infancy' => $daysSinceWeekly < 60,
                'days_weekly' => $daysSinceWeekly,
            ];
        }

        return $results;
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

    public function copyTickers(Request $request)
    {
        $timeframe = $request->query('timeframe', 'weekly');
        $table = $this->tableForTimeframe($timeframe);
        $undervalued = $request->boolean('undervalued');
        $long = $request->boolean('long');
        $short = $request->boolean('short');
        $multitfUptrend = $request->boolean('multitf_uptrend');
        $infancy = $request->boolean('infancy');

        if ($undervalued) {
            $rows = DB::select("
                SELECT st.symbol AS ticker
                FROM tbl_stock_analyzer sa
                JOIN tbl_stock_tickers st ON st.id = sa.ticker_id
                WHERE sa.db_valuation_price > sa.db_close
                  AND sa.db_valuation_price > 0
                  AND sa.db_close > 0
                ORDER BY (sa.db_valuation_price - sa.db_close) / sa.db_close DESC
            ");
        } elseif ($multitfUptrend) {
            $rows = $this->getMultiTfUptrendTickers($infancy);
        } elseif ($short) {
            $rows = DB::select("
                SELECT e.symbol AS ticker
                FROM (
                    SELECT ticker_id, close, macd_histogram, ppo_histogram,
                           LAG(ppo_histogram) OVER (PARTITION BY ticker_id ORDER BY date) AS prev_ppo
                    FROM {$table}
                ) t
                JOIN tbl_stock_tickers e ON e.id = t.ticker_id
                WHERE t.macd_histogram::float8 > 0
                  AND t.ppo_histogram::float8 <= 0
                  AND t.prev_ppo::float8 > 0
                GROUP BY e.symbol
            ");
        } elseif ($long) {
            $rows = DB::select("
                SELECT e.symbol AS ticker
                FROM (
                    SELECT ticker_id, close, macd_histogram, ppo_histogram, atr_stop,
                           LAG(macd_histogram) OVER (PARTITION BY ticker_id ORDER BY date) AS prev_macd,
                           LAG(ppo_histogram) OVER (PARTITION BY ticker_id ORDER BY date) AS prev_ppo
                    FROM {$table}
                ) t
                JOIN tbl_stock_tickers e ON e.id = t.ticker_id
                WHERE t.atr_stop::float8 IS NOT NULL
                  AND t.close::float8 > t.atr_stop::float8
                  AND t.close::float8 > 0
                  AND (
                      (t.macd_histogram::float8 > 0 AND t.prev_macd::float8 <= 0)
                   OR (t.ppo_histogram::float8 > 0 AND t.prev_ppo::float8 <= 0)
                  )
                GROUP BY e.symbol
            ");
        } else {
            return response()->json(['tickers' => '']);
        }

        $tickers = collect($rows)->pluck('ticker')->implode(',');
        return response()->json(['tickers' => $tickers]);
    }

    private function getMultiTfUptrendTickers(bool $infancyOnly = false)
    {
        $results = $this->computeMultiTfResults();
        $tickers = [];
        foreach ($results as $r) {
            if ($infancyOnly && !$r['infancy']) continue;
            $tickers[] = $r['ticker'];
        }
        sort($tickers);
        return array_map(fn($t) => (object)['ticker' => $t], $tickers);
    }

    public function explorer(Request $request)
    {
        $mode = $request->query('mode', 'stock');
        return view('scanner.explorer', ['mode' => $mode]);
    }

    public function explorerData(Request $request)
    {
        $mode = $request->query('mode', 'stock');
        $isEft = $mode === 'etf';

        // Cache key based on mode — data only changes once per day
        $cacheFile = storage_path("framework/cache/explorer_{$mode}.json");
        $cacheTtl = 300; // 5 min
        if (file_exists($cacheFile) && time() - filemtime($cacheFile) < $cacheTtl) {
            return response()->json(json_decode(file_get_contents($cacheFile), true));
        }

        $tickerInfo = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->where('is_etf', $isEft)
            ->when($isEft, fn($q) => $q->whereIn('symbol', ['QQQ', 'VTI', 'VTV']))
            ->select('id', 'symbol', 'company_name')
            ->get()
            ->keyBy('id');

        $latestWeekly = DB::selectOne("SELECT MAX(date) AS d FROM tbl_scanner_tickers");
        $latestDaily = DB::selectOne("SELECT MAX(date) AS d FROM tbl_scanner_tickers_daily");
        $latestHourlyDate = DB::selectOne("SELECT MAX(date)::date AS d FROM tbl_scanner_tickers_1hour");
        if (!$latestWeekly || !$latestDaily || !$latestHourlyDate) {
            return response()->json(['error' => 'No data'], 500);
        }
        $wkDate = $latestWeekly->d;
        $hrDate = $latestHourlyDate->d;

        // SMA40/EMA10 computed via ROW_NUMBER + GROUP BY + FILTER — avoids expensive
        // window-function frames by reducing to 40 (or 10) rows per ticker before averaging.
        // The 5-min file cache means this runs at most once per session.
        $weeklyData = DB::select("
            SELECT ticker_id,
                   MAX(CASE WHEN rnd = 1 THEN close END) AS close,
                   AVG(close::float8) FILTER (WHERE rnd <= 40) AS sma40,
                   AVG(close::float8) FILTER (WHERE rnd <= 10) AS ema10
            FROM (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers
            ) sub
            WHERE rnd <= 40
            GROUP BY ticker_id
        ");
        $weeklyById = [];
        foreach ($weeklyData as $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $weeklyById[$r->ticker_id] = $r;
            }
        }

        $dailyData = DB::select("
            SELECT ticker_id,
                   MAX(CASE WHEN rnd = 1 THEN close END) AS close,
                   AVG(close::float8) FILTER (WHERE rnd <= 40) AS sma40,
                   AVG(close::float8) FILTER (WHERE rnd <= 10) AS ema10
            FROM (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers_daily
            ) sub
            WHERE rnd <= 40
            GROUP BY ticker_id
        ");
        $dailyById = [];
        $dailyBullishById = [];
        foreach ($dailyData as $r) {
            $dailyById[$r->ticker_id] = $r;
            if ($r->close !== null && $r->sma40 !== null && (float)$r->close > (float)$r->sma40) {
                $dailyBullishById[$r->ticker_id] = true;
            }
        }

        $hourlyData = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   close::float8 AS close,
                   atr_stop::float8 AS atr_stop
            FROM tbl_scanner_tickers_1hour
            WHERE date >= ?
            ORDER BY ticker_id, date DESC
        ", [$hrDate]);
        $hourlyById = [];
        foreach ($hourlyData as $r) {
            if ($r->atr_stop !== null && $r->atr_stop > 0) {
                $hourlyById[$r->ticker_id] = $r;
            }
        }

        // Cross dates: weekly SMA40 cross above within last 60 rows.
        $crossDates = DB::select("
            WITH ranked AS (
                SELECT ticker_id, date, close::float8 AS close,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rnd
                FROM tbl_scanner_tickers
            ),
            sma AS (
                SELECT ticker_id, date, close,
                       AVG(close) OVER (PARTITION BY ticker_id ORDER BY date ASC ROWS BETWEEN 39 PRECEDING AND CURRENT ROW) AS sma40
                FROM ranked WHERE rnd <= 60
            )
            SELECT DISTINCT ON (a.ticker_id) a.ticker_id, a.date
            FROM sma a
            JOIN sma b ON b.ticker_id = a.ticker_id
               AND b.date = (SELECT MAX(c.date) FROM sma c WHERE c.ticker_id = a.ticker_id AND c.date < a.date)
            WHERE a.close > a.sma40 AND b.close <= b.sma40
            ORDER BY a.ticker_id, a.date DESC
        ");
        $crossDateById = [];
        foreach ($crossDates as $r) {
            $crossDateById[$r->ticker_id] = $r->date;
        }

        // Market breadth computed from already-loaded data.
        $breadthTotal = 0;
        $breadthUp = 0;
        foreach ($tickerInfo as $tid => $info) {
            $w = $weeklyById[$tid] ?? null;
            $dBullish = $dailyBullishById[$tid] ?? false;
            if (!$w) continue;
            $breadthTotal++;
            if ((float)$w->close > (float)$w->sma40 && $dBullish) {
                $breadthUp++;
            }
        }
        $breadthPct = $breadthTotal > 0
            ? round($breadthUp / $breadthTotal * 100, 1) : null;

        $results = [];
        foreach ($tickerInfo as $tid => $info) {
            $w = $weeklyById[$tid] ?? null;
            $h = $hourlyById[$tid] ?? null;
            $d = $dailyById[$tid] ?? null;
            $dBullish = $dailyBullishById[$tid] ?? false;
            if (!$w || !$h) continue;

            $close_w = (float)$w->close;
            $sma40_w = (float)$w->sma40;
            $ema10_w = (float)$w->ema10;
            $close_h = (float)$h->close;
            $atr_stop = (float)$h->atr_stop;

            // Weekly filter: close > SMA40 and EMA10 > SMA40; daily close > SMA40
            if ($close_w <= $sma40_w || !$ema10_w || $ema10_w <= $sma40_w || !$dBullish) continue;

            $gap_w = ($close_w - $sma40_w) / $sma40_w * 100;
            $atr_dist = ($close_h - $atr_stop) / $close_h * 100;

            // Freshness: days since weekly cross
            $crossDate = $crossDateById[$tid] ?? null;
            $daysSince = 999;
            if ($crossDate) {
                $daysSince = (new \DateTime($crossDate))->diff(new \DateTime())->days;
            }

            $gap_pts = min($gap_w / 20, 3);
            $atr_pts = min($atr_dist / 1.5, 3);
            $fresh_pts = max(0, 2 - $daysSince / 60);
            $score = round($gap_pts + $atr_pts + $fresh_pts, 1);

            // CHAND: close > ATR stop on hourly = bullish
            $chand = $close_h > $atr_stop ? 'bull' : 'bear';
            // EMAC: daily EMA10 > SMA40 = bullish (SMA10 proxy for EMA10)
            $emac = ($d && $d->ema10 !== null && $d->sma40 !== null && (float)$d->ema10 > (float)$d->sma40)
                ? 'bull' : 'bear';
            // Daily Signal: fresh weekly SMA40 cross within 60 days (infancy)
            $daily_signal = ($daysSince < 60) ? 'bull' : 'bear';
            // Combined: mtf score +2 per bullish daily signal +1 per bullish emac/chand
            $combined = round($score + ($daily_signal === 'bull' ? 2 : 0)
                + ($emac === 'bull' ? 1 : 0) + ($chand === 'bull' ? 1 : 0), 1);
            // Early Score: favors fresh all-green stocks that haven't run up yet
            // = signal count (3 max) + fresh_pts - gap_pts
            $signal_count = ($daily_signal === 'bull' ? 1 : 0) + ($emac === 'bull' ? 1 : 0) + ($chand === 'bull' ? 1 : 0);
            $early = round($signal_count + $fresh_pts - $gap_pts, 1);

            $results[] = [
                'symbol' => $info->symbol,
                'name' => $info->company_name,
                'close' => round($close_w, 2),
                'mtf_score' => $score,
                'daily_signal' => $daily_signal,
                'emac' => $emac,
                'chand' => $chand,
                'mtcs' => null,
                'combined' => $combined,
                'early' => $early,
            ];
        }

        usort($results, fn($a, $b) => $b['combined'] <=> $a['combined']);

        $payload = [
            'picks' => array_slice($results, 0, 50),
            'total' => count($results),
            'breadth' => $breadthPct,
            'mode' => $mode,
            'date' => $wkDate,
        ];

        file_put_contents($cacheFile, json_encode($payload), LOCK_EX);

        return response()->json($payload);
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

        // Limit bars for performance: 500 for 1-hour, 500 for daily, all for weekly
        $limit = $request->query('limit');
        if ($limit === null) {
            $limit = $timeframe === '1hour' ? 500 : ($timeframe === 'daily' ? 500 : 300);
        } else {
            $limit = (int)$limit;
        }

        $bars = DB::select("
            SELECT * FROM (
                SELECT date, open, high, low, close, volume
                FROM {$table}
                WHERE ticker_id = ?
                ORDER BY date DESC
                LIMIT {$limit}
            ) sub
            ORDER BY date ASC
        ", [$tickerId]);

        $indicators = DB::select("
            SELECT * FROM (
                SELECT date, macd_line::float8, macd_signal::float8, macd_histogram::float8,
                       ppo_line::float8, ppo_signal::float8, ppo_histogram::float8,
                       macd_crossover, ppo_crossover, sma_crossover
                FROM {$table}
                WHERE ticker_id = ?
                ORDER BY date DESC
                LIMIT {$limit}
            ) sub
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
