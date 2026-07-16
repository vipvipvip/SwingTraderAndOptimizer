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
        $total = DB::table('tbl_stock_tickers')->where('enabled', true)->count();
        $uptrend = DB::selectOne("
            WITH weekly_bullish AS (
                SELECT DISTINCT ON (ticker_id) ticker_id,
                       CASE WHEN ema10_sma40_crossover THEN true
                            WHEN ema10_sma40_cross_bearish THEN false
                       END AS bullish
                FROM tbl_scanner_tickers
                WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
                ORDER BY ticker_id, date DESC
            ),
            daily_bullish AS (
                SELECT DISTINCT ON (ticker_id) ticker_id,
                       CASE WHEN ema10_sma40_crossover THEN true
                            WHEN ema10_sma40_cross_bearish THEN false
                       END AS bullish
                FROM tbl_scanner_tickers_daily
                WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
                ORDER BY ticker_id, date DESC
            )
            SELECT COUNT(*) AS cnt
            FROM weekly_bullish wb
            JOIN daily_bullish db USING (ticker_id)
            WHERE wb.bullish AND db.bullish
        ");
        $pct = $total > 0 ? (int)round(($uptrend->cnt ?? 0) / $total * 100) : 0;
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
        return ['pct' => $pct, 'regime' => $regime, 'color' => $color];
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
        // Get latest crossover event per ticker for each timeframe
        $latestWeeklyCross = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   CASE WHEN ema10_sma40_crossover THEN 'bullish'
                        WHEN ema10_sma40_cross_bearish THEN 'bearish'
                   END AS cross_type,
                   date AS cross_date
            FROM tbl_scanner_tickers
            WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
            ORDER BY ticker_id, date DESC
        ");

        $latestDailyCross = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   CASE WHEN ema10_sma40_crossover THEN 'bullish'
                        WHEN ema10_sma40_cross_bearish THEN 'bearish'
                   END AS cross_type,
                   date AS cross_date
            FROM tbl_scanner_tickers_daily
            WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
            ORDER BY ticker_id, date DESC
        ");

        // Latest 2 bars of 1-hour per ticker to detect fresh crossover
        $hourlyCross = DB::select("
            WITH ranked AS (
                SELECT ticker_id, date, close::float8 AS close,
                       ema10_sma40_crossover,
                       ema10_sma40_cross_bearish,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
                FROM tbl_scanner_tickers_1hour
            )
            SELECT c.ticker_id, c.date, c.close,
                   c.ema10_sma40_crossover AS curr_cross,
                   p.ema10_sma40_crossover AS prev_cross
            FROM ranked c
            LEFT JOIN ranked p ON p.ticker_id = c.ticker_id AND p.rn = 2
            WHERE c.rn = 1
        ");

        $weeklyById = [];
        foreach ($latestWeeklyCross as $r) {
            $weeklyById[$r->ticker_id] = $r;
        }
        $dailyById = [];
        foreach ($latestDailyCross as $r) {
            $dailyById[$r->ticker_id] = $r;
        }

        $hourlyFresh = [];
        foreach ($hourlyCross as $r) {
            $fresh = $r->curr_cross && !$r->prev_cross;
            $hourlyFresh[$r->ticker_id] = $fresh;
        }

        // Weekly SMA(40) and latest close for gap computation
        $weeklyGap = DB::select("
            SELECT DISTINCT ON (t.ticker_id) t.ticker_id,
                   t.close::float8 AS close,
                   AVG(t.close::float8) OVER (
                       PARTITION BY t.ticker_id
                       ORDER BY t.date
                       ROWS BETWEEN 39 PRECEDING AND CURRENT ROW
                   ) AS sma40
            FROM tbl_scanner_tickers t
            ORDER BY t.ticker_id, t.date DESC
        ");
        $weeklyGapById = [];
        foreach ($weeklyGap as $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $weeklyGapById[$r->ticker_id] = (float)$r->close;
                $weeklySmaById[$r->ticker_id] = (float)$r->sma40;
            }
        }

        // ATR stop from weekly latest bar
        $atrData = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   close::float8 AS close,
                   atr_stop::float8 AS atr_stop
            FROM tbl_scanner_tickers
            ORDER BY ticker_id, date DESC
        ");
        $atrDistById = [];
        foreach ($atrData as $r) {
            if ($r->atr_stop !== null && $r->atr_stop > 0) {
                $dist = ((float)$r->close - (float)$r->atr_stop) / (float)$r->close * 100;
                $atrDistById[$r->ticker_id] = $dist;
            }
        }

        $tickerInfo = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->select('id', 'symbol', 'company_name')
            ->get()
            ->keyBy('id');

        // Days since weekly cross — compute from weekly EMA/SMA via SQL window
        $weeklyAge = DB::select("
            WITH weekly_data AS (
                SELECT ticker_id, date, close::float8 AS close,
                       AVG(close::float8) OVER (
                           PARTITION BY ticker_id ORDER BY date
                           ROWS BETWEEN 39 PRECEDING AND CURRENT ROW
                       ) AS sma40,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
                FROM tbl_scanner_tickers
            ),
            latest AS (
                SELECT ticker_id, close, sma40, date,
                       LAG(close::float8) OVER (PARTITION BY ticker_id ORDER BY date) AS prev_close,
                       LAG(sma40) OVER (PARTITION BY ticker_id ORDER BY date) AS prev_sma40
                FROM weekly_data
                WHERE rn <= 2
            )
            SELECT ticker_id,
                   MAX(CASE WHEN rn_calc = 1 THEN date END) AS latest_date,
                   MAX(CASE WHEN rn_calc = 1 THEN close END) AS close,
                   MAX(CASE WHEN rn_calc = 1 THEN sma40 END) AS sma40
            FROM (
                SELECT ticker_id, date, close, sma40,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn_calc
                FROM weekly_data
                WHERE close > sma40  -- crude bullish filter: close above SMA40
            ) sub
            WHERE rn_calc <= 1
            GROUP BY ticker_id
        ");

        // Compute days since weekly crossover by scanning bar-by-bar in PHP
        // We'll use a simpler approach: approximate via crossover flag date
        $daysSinceWeeklyById = [];
        foreach ($weeklyById as $tid => $w) {
            if ($w->cross_type === 'bullish') {
                $daysSinceWeeklyById[$tid] = (new \DateTime($w->cross_date))->diff(new \DateTime())->days;
            }
        }

        $results = [];
        foreach ($tickerInfo as $tid => $info) {
            $w = $weeklyById[$tid] ?? null;
            $d = $dailyById[$tid] ?? null;
            $freshHourly = $hourlyFresh[$tid] ?? false;

            $weeklyBullish = $w && $w->cross_type === 'bullish';
            $dailyBullish = $d && $d->cross_type === 'bullish';
            $hourlyEntry = $freshHourly && $weeklyBullish && $dailyBullish;
            $newDailyUptrend = $d && $d->cross_type === 'bullish'
                && $d->cross_date === $today;

            if (!$weeklyBullish || !$dailyBullish) {
                continue;
            }

            $daysSinceWeekly = $daysSinceWeeklyById[$tid] ?? 999;
            $isInfancy = $daysSinceWeekly < 60;

            if ($infancyOnly && !$isInfancy) {
                continue;
            }

            // Compute momentum score with freshness bonus
            $weeklyClose = $weeklyGapById[$tid] ?? null;
            $weeklySma = $weeklySmaById[$tid] ?? null;
            $gapW = $weeklyClose && $weeklySma ? (($weeklyClose - $weeklySma) / $weeklySma) * 100 : 0;
            $atrDist = $atrDistById[$tid] ?? 0;

            $score = 0;
            $score += min($gapW / 20, 3);                // weekly gap: 0-3 pts
            $score += min($atrDist / 1.5, 3);             // ATR distance: 0-3 pts
            $score += max(0, 2 - $daysSinceWeekly / 60);  // freshness: 0-2 pts
            $score = round($score, 1);

            $results[] = (object)[
                'ticker' => $info->symbol,
                'company_name' => $info->company_name,
                'close' => $weeklyClose ? round($weeklyClose, 2) : null,
                'weekly_cross_date' => $w ? $w->cross_date : null,
                'daily_cross_date' => $d ? $d->cross_date : null,
                'hourly_entry' => $hourlyEntry,
                'new_daily_uptrend' => $newDailyUptrend,
                'score' => $score,
                'gap_w' => round($gapW, 1),
                'atr_dist' => round($atrDist, 1),
                'infancy' => $isInfancy,
                'days_weekly' => $daysSinceWeekly,
            ];
        }

        // Sort: infancy first, then by score descending, entry signals on top
        usort($results, function ($a, $b) {
            if ($a->infancy !== $b->infancy) return $b->infancy <=> $a->infancy;
            if ($a->hourly_entry !== $b->hourly_entry) return $b->hourly_entry <=> $a->hourly_entry;
            return $b->score <=> $a->score;
        });

        $all_tickers = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->orderBy('symbol')
            ->pluck('symbol');

        return view('scanner.index', array_merge([
            'results' => $results,
            'total_scanned' => $tickerInfo->count(),
            'total_signals' => count($results),
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
        $latestWeeklyCross = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   CASE WHEN ema10_sma40_crossover THEN 'bullish'
                        WHEN ema10_sma40_cross_bearish THEN 'bearish'
                   END AS cross_type,
                   date AS cross_date
            FROM tbl_scanner_tickers
            WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
            ORDER BY ticker_id, date DESC
        ");
        $latestDailyCross = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   CASE WHEN ema10_sma40_crossover THEN 'bullish'
                        WHEN ema10_sma40_cross_bearish THEN 'bearish'
                   END AS cross_type,
                   date AS cross_date
            FROM tbl_scanner_tickers_daily
            WHERE ema10_sma40_crossover OR ema10_sma40_cross_bearish
            ORDER BY ticker_id, date DESC
        ");
        $weeklyById = [];
        foreach ($latestWeeklyCross as $r) {
            $weeklyById[$r->ticker_id] = $r;
        }
        $dailyById = [];
        foreach ($latestDailyCross as $r) {
            $dailyById[$r->ticker_id] = $r;
        }

        $tickerInfo = DB::table('tbl_stock_tickers')
            ->where('enabled', true)
            ->select('id', 'symbol')
            ->get()
            ->keyBy('id');

        $results = [];
        foreach ($tickerInfo as $tid => $info) {
            $w = $weeklyById[$tid] ?? null;
            $d = $dailyById[$tid] ?? null;
            $weeklyBullish = $w && $w->cross_type === 'bullish';
            $dailyBullish = $d && $d->cross_type === 'bullish';
            if (!$weeklyBullish || !$dailyBullish) continue;

            if ($infancyOnly) {
                $daysSinceWeekly = $w->cross_date
                    ? (new \DateTime($w->cross_date))->diff(new \DateTime())->days
                    : 999;
                if ($daysSinceWeekly >= 60) continue;
            }
            $results[] = (object)['ticker' => $info->symbol];
        }
        return $results;
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
