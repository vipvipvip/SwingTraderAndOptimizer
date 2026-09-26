<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Drop every legacy indicator column; `atr_stop` is the only one kept.
 *
 * Why: the live strategies all compute EMA10/SMA40 inline (window functions /
 * pandas ewm) because the stored ema10_sma40_* columns were never populated by
 * the pipeline and went stale on 2026-06-25. Several of the remaining columns
 * were misnamed legacy artifacts:
 *   - sma_crossover / sma_cross_bearish were EMA24 vs SMA52, not SMA10/40
 *   - ppo_crossover / ppo_cross_bearish were a 24/52 zero-cross, not 12/26
 *   - macd_crossover / ppo_crossover were written but never read
 *   - ema10_sma40_* were orphaned rows from a deleted script
 *
 * `atr_stop` stays because both live strategies invert it to recover ATR as
 * ATR = (close - atr_stop) / 2 (MTF stock-leg ratchet + CoreEW weekly gate).
 *
 * NOTE: the 1-hour table is deliberately untouched. scanner/services/
 * earnings_screener.py still reads hourly MACD and runs on a live 09:30 timer.
 */
return new class extends Migration
{
    /** Columns to drop, in dependency-free order. */
    private const LEGACY = [
        'macd_line',
        'macd_signal',
        'macd_histogram',
        'macd_crossover',
        'macd_cross_bearish',
        'ppo_line',
        'ppo_signal',
        'ppo_histogram',
        'ppo_crossover',
        'ppo_cross_bearish',
        'sma_crossover',
        'sma_cross_bearish',
        'ema10_sma40_crossover',
        'ema10_sma40_cross_bearish',
    ];

    private const TABLES = [
        'tbl_scanner_tickers',        // weekly
        'tbl_scanner_tickers_daily',  // daily
    ];

    public function up(): void
    {
        foreach (self::TABLES as $table) {
            if (! Schema::hasTable($table)) {
                continue;
            }
            $existing = Schema::getColumnListing($table);
            $drop = array_values(array_intersect(self::LEGACY, $existing));

            if ($drop === []) {
                continue;
            }

            // Postgres allows only one bare column per DROP COLUMN clause,
            // so the keyword has to be repeated for each column.
            $clauses = array_map(fn ($c) => 'DROP COLUMN "' . $c . '"', $drop);
            DB::statement(sprintf(
                'ALTER TABLE %s %s',
                $table,
                implode(', ', $clauses)
            ));
        }
    }

    public function down(): void
    {
        $defs = [
            'macd_line' => 'numeric(16,8)',
            'macd_signal' => 'numeric(16,8)',
            'macd_histogram' => 'numeric(16,8)',
            'macd_crossover' => 'boolean NOT NULL DEFAULT false',
            'macd_cross_bearish' => 'boolean NOT NULL DEFAULT false',
            'ppo_line' => 'numeric(16,8)',
            'ppo_signal' => 'numeric(16,8)',
            'ppo_histogram' => 'numeric(16,8)',
            'ppo_crossover' => 'boolean NOT NULL DEFAULT false',
            'ppo_cross_bearish' => 'boolean NOT NULL DEFAULT false',
            'sma_crossover' => 'boolean NOT NULL DEFAULT false',
            'sma_cross_bearish' => 'boolean NOT NULL DEFAULT false',
            'ema10_sma40_crossover' => 'boolean NOT NULL DEFAULT false',
            'ema10_sma40_cross_bearish' => 'boolean NOT NULL DEFAULT false',
        ];

        foreach (self::TABLES as $table) {
            if (! Schema::hasTable($table)) {
                continue;
            }
            $existing = Schema::getColumnListing($table);
            foreach (self::LEGACY as $col) {
                if (! in_array($col, $existing, true)) {
                    DB::statement(sprintf(
                        'ALTER TABLE %s ADD COLUMN IF NOT EXISTS "%s" %s',
                        $table,
                        $col,
                        $defs[$col]
                    ));
                }
            }
        }
    }
};
