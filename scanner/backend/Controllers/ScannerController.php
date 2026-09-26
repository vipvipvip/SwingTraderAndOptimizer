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
        $multitfUptrend = $request->boolean('multitf_uptrend');
        $infancy = $request->boolean('infancy');

        $breadth = $this->getMarketBreadth();

        if ($undervalued) {
            return $this->indexUndervalued($request, $timeframe, $table, $breadth);
        }

        // The former indexLong/indexShort screens were MACD/PPO histogram
        // zero-cross rules and were deleted 2026-09-26 with those columns.
        // Every screen now falls through to the multi-TF EMA10>SMA40 uptrend
        // screen, which mirrors the live MTF scoring and is lookahead-free.
        return $this->indexMultiTfUptrend($request, $timeframe, $table, $infancy, $breadth);
    }

    private function getMarketBreadth(): array
    {
        // The stored ema10_sma40_* columns were dropped 2026-09-26 (never
        // populated by the pipeline; stale since 2026-06-25), so breadth is
        // computed inline via window functions.
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
     * Latest close + SMA40 + a TRUE EMA10 for every ticker in a bar table.
     *
     * EMA10 is a recursive EMA (k = 2/11, seeded at the oldest bar of a bounded
     * lookback window) — the same definition as mtf/db.py ema(). It previously
     * used `AVG(close) FILTER (rnd <= 10)`, which is an SMA10 mislabelled
     * `ema10`: a different quantity that disagreed with the live MTF scorer.
     * SMA10 is not calculated anywhere.
     *
     * Done in PHP rather than a recursive SQL CTE: the CTE is correct but takes
     * ~49s for both tables, while streaming the window with cursor() and
     * looping takes ~3s. The window is bounded to self::EMA_SEED_BARS; with
     * k = 2/11 the residual seed weight after 120 bars is (1-k)^120 ~= 1e-5, so
     * the EMA is converged and the seed choice is immaterial.
     */
    private const EMA_SEED_BARS = 120;

    /** @return array<int, object> ticker_id => {close, sma40, ema10} */
    private function closeSma40Ema10(string $table): array
    {
        $n = self::EMA_SEED_BARS;
        $k = 2.0 / 11.0;

        $sql = "SELECT ticker_id, close::float8 AS close FROM (
                    SELECT ticker_id, close::float8 AS close,
                           ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS d_desc
                    FROM {$table}
                ) s
                WHERE d_desc <= {$n}
                ORDER BY ticker_id, d_desc DESC";

        $out = [];
        $curId = null;
        $acc = null;      // running EMA10
        $sum = 0.0;       // running sum for SMA40
        $win = [];        // rolling 40-close window
        $lastClose = null;

        $flush = function () use (&$out, &$curId, &$acc, &$sum, &$win, &$lastClose) {
            if ($curId === null) {
                return;
            }
            $out[$curId] = (object) [
                'ticker_id' => $curId,
                'close' => $lastClose,
                'sma40' => count($win) >= 40 ? $sum / 40.0 : null,
                'ema10' => $acc,
            ];
        };

        foreach (DB::connection()->cursor($sql) as $row) {
            $tid = (int) $row->ticker_id;
            $c = (float) $row->close;

            if ($tid !== $curId) {
                $flush();
                $curId = $tid;
                $acc = $c;        // seed at the oldest bar in the window
                $sum = 0.0;
                $win = [];
            } else {
                $acc = $c * $k + $acc * (1 - $k);
            }

            // Rows arrive oldest-first (d_desc DESC), so the last one seen for a
            // ticker is its most recent close.
            $lastClose = $c;

            $sum += $c;
            $win[] = $c;
            if (count($win) > 40) {
                $sum -= array_shift($win);
            }
        }
        $flush();

        return $out;
    }

    /**
     * Score all enabled non-ETF stocks with the production Multi-TF logic
     * (mirrors swingtrader/services/mtf/runner.py _compute_score).
     * EMA10/SMA40 are computed inline — the stored ema10_sma40_* columns were
     * dropped 2026-09-26 (never populated by the pipeline; stale since 2026-06-25).
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

        $weeklyById = [];
        foreach ($this->closeSma40Ema10('tbl_scanner_tickers') as $tid => $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $weeklyById[$tid] = $r;
            }
        }

        $dailyById = [];
        foreach ($this->closeSma40Ema10('tbl_scanner_tickers_daily') as $tid => $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $dailyById[$tid] = $r;
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
        } elseif ($multitfUptrend || !$undervalued) {
            // The former long/short pick lists were MACD/PPO zero-cross rules
            // and were removed 2026-09-26 with those columns. The multi-TF
            // EMA10>SMA40 list is now the default.
            $rows = $this->getMultiTfUptrendTickers($infancy);
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

        // SMA40/EMA10 come from closeSma40Ema10() (true recursive EMA10).
        // The 5-min file cache means this runs at most once per session.
        $weeklyById = [];
        foreach ($this->closeSma40Ema10('tbl_scanner_tickers') as $tid => $r) {
            if ($r->sma40 !== null && $r->sma40 > 0) {
                $weeklyById[$tid] = $r;
            }
        }

        $dailyById = [];
        foreach ($this->closeSma40Ema10('tbl_scanner_tickers_daily') as $tid => $r) {
            $dailyById[$tid] = $r;
        }

        $hourlyData = DB::select("
            SELECT DISTINCT ON (ticker_id) ticker_id,
                   close::float8 AS close,
                   atr_stop::float8 AS atr_stop
            FROM tbl_scanner_tickers_1hour
            WHERE date >= ?
              AND atr_stop IS NOT NULL
              AND atr_stop > 0
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
        $crossDateById = [];
        foreach ($crossDates as $r) {
            $crossDateById[$r->ticker_id] = $r->date;
        }

        // Market breadth: MTF filter (weekly+daily EMA10 > SMA40) matching production.
        $breadthTotal = 0;
        $breadthUp = 0;
        foreach ($tickerInfo as $tid => $info) {
            $w = $weeklyById[$tid] ?? null;
            $d = $dailyById[$tid] ?? null;
            if (!$w || !$d) continue;
            $breadthTotal++;
            if ((float)$w->ema10 > (float)$w->sma40
                && $d->ema10 !== null && $d->sma40 !== null && (float)$d->ema10 > (float)$d->sma40) {
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
            if (!$w || !$h) continue;

            $close_w = (float)$w->close;
            $sma40_w = (float)$w->sma40;
            $ema10_w = (float)$w->ema10;
            $close_h = (float)$h->close;
            $atr_stop = (float)$h->atr_stop;

            // MTF filter: weekly+daily EMA10 > SMA40 + hourly close > ATR stop
            if (!$ema10_w || $ema10_w <= $sma40_w) continue;
            if (!$d || !$d->ema10 || !$d->sma40 || (float)$d->ema10 <= (float)$d->sma40) continue;
            if ($atr_stop <= 0 || $close_h <= $atr_stop) continue;

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

            // CoreEW: close > ATR stop on hourly = bullish (legacy CHAND read)
            $coreew = $close_h > $atr_stop ? 'bull' : 'bear';
            // Daily EMA10 > SMA40 = bullish (true EMA10 from closeSma40Ema10)
            $emac = ($d && $d->ema10 !== null && $d->sma40 !== null && (float)$d->ema10 > (float)$d->sma40)
                ? 'bull' : 'bear';
            // Daily Signal: fresh weekly SMA40 cross within 60 days (infancy)
            $daily_signal = ($daysSince < 60) ? 'bull' : 'bear';
            // Combined: mtf score +2 per bullish daily signal +1 per bullish emac/coreew
            $combined = round($score + ($daily_signal === 'bull' ? 2 : 0)
                + ($emac === 'bull' ? 1 : 0) + ($coreew === 'bull' ? 1 : 0), 1);
            // Early Score: favors fresh all-green stocks that haven't run up yet
            // = signal count (3 max) + fresh_pts - gap_pts
            $signal_count = ($daily_signal === 'bull' ? 1 : 0) + ($emac === 'bull' ? 1 : 0) + ($coreew === 'bull' ? 1 : 0);
            $early = round($signal_count + $fresh_pts - $gap_pts, 1);

            $results[] = [
                'symbol' => $info->symbol,
                'name' => $info->company_name,
                'close' => round($close_w, 2),
                'mtf_score' => $score,
                'daily_signal' => $daily_signal,
                'emac' => $emac,
                'coreew' => $coreew,
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
                SELECT date, atr_stop::float8
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
            SELECT date, close, atr_stop::float8
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
