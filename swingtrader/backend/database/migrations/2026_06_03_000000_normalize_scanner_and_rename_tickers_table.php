<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Facades\DB;

return new class extends Migration
{
    private array $scannerTables = [
        'tbl_scanner_tickers',
        'tbl_scanner_tickers_daily',
        'tbl_scanner_tickers_1hour',
    ];

    public function up(): void
    {
        // 1. Add missing columns to scanner tables (used by compute_indicators.py)
        //    These exist in the actual DB but were never added to migrations.
        foreach ($this->scannerTables as $table) {
            if (Schema::hasTable($table)) {
                Schema::table($table, function (Blueprint $t) use ($table) {
                    if (!Schema::hasColumn($table, 'macd_cross_bearish')) {
                        $t->boolean('macd_cross_bearish')->default(false)->after('macd_crossover');
                    }
                    if (!Schema::hasColumn($table, 'ppo_cross_bearish')) {
                        $t->boolean('ppo_cross_bearish')->default(false)->after('ppo_crossover');
                    }
                    if (!Schema::hasColumn($table, 'sma_crossover')) {
                        $t->boolean('sma_crossover')->default(false)->after('ppo_cross_bearish');
                    }
                    if (!Schema::hasColumn($table, 'sma_cross_bearish')) {
                        $t->boolean('sma_cross_bearish')->default(false)->after('sma_crossover');
                    }
                    if (!Schema::hasColumn($table, 'atr_stop')) {
                        $t->decimal('atr_stop', 16, 8)->nullable()->after('sma_cross_bearish');
                    }
                });
            }
        }

        // 2. Rename tickers → tbl_etf_tickers
        Schema::rename('tickers', 'tbl_etf_tickers');

        // 3. Insert all distinct tickers from scanner tables into tbl_etf_tickers
        //    Use raw UNION to avoid duplicates across the three scanner tables.
        foreach ($this->scannerTables as $table) {
            if (!Schema::hasTable($table)) continue;
            DB::statement("
                INSERT INTO tbl_etf_tickers (symbol, enabled, allocation_weight, created_at, updated_at)
                SELECT DISTINCT ticker, true, 10.0000, NOW(), NOW()
                FROM {$table}
                WHERE ticker NOT IN (SELECT symbol FROM tbl_etf_tickers)
            ");
        }

        // 4. Add ticker_id FK column to each scanner table, populate it, drop old ticker column
        foreach ($this->scannerTables as $table) {
            if (!Schema::hasTable($table)) continue;

            Schema::table($table, function (Blueprint $t) use ($table) {
                $t->unsignedBigInteger('ticker_id')->nullable()->after('id');
            });

            DB::statement("
                UPDATE {$table} s
                SET ticker_id = e.id
                FROM tbl_etf_tickers e
                WHERE e.symbol = s.ticker
            ");

            Schema::table($table, function (Blueprint $t) use ($table) {
                $t->dropUnique("{$table}_ticker_date_unique");
                $t->dropIndex("{$table}_ticker_index");
                $t->dropIndex("{$table}_ticker_date_index");
                $t->dropColumn('ticker');
            });

            Schema::table($table, function (Blueprint $t) use ($table) {
                $t->unsignedBigInteger('ticker_id')->nullable(false)->change();
                $t->foreign('ticker_id')->references('id')->on('tbl_etf_tickers')->onDelete('cascade');
                $t->unique(['ticker_id', 'date']);
                $t->index('ticker_id');
                $t->index(['ticker_id', 'date']);
            });
        }
    }

    public function down(): void
    {
        // Reverse: add ticker column back, drop FK, repopulate ticker string
        foreach ($this->scannerTables as $table) {
            if (!Schema::hasTable($table)) continue;

            Schema::table($table, function (Blueprint $t) use ($table) {
                $t->dropForeign("{$table}_ticker_id_foreign");
                $t->dropUnique("{$table}_ticker_id_date_unique");
                $t->dropIndex("{$table}_ticker_id_index");
                $t->dropIndex("{$table}_ticker_id_date_index");

                $t->string('ticker', 10)->nullable()->after('id');
            });

            DB::statement("
                UPDATE {$table} s
                SET ticker = e.symbol
                FROM tbl_etf_tickers e
                WHERE e.id = s.ticker_id
            ");

            Schema::table($table, function (Blueprint $t) use ($table) {
                $t->dropColumn('ticker_id');
                $t->string('ticker', 10)->nullable(false)->change();
                $t->unique(['ticker', 'date']);
                $t->index('ticker');
                $t->index(['ticker', 'date']);
            });
        }

        Schema::rename('tbl_etf_tickers', 'tickers');
    }
};
