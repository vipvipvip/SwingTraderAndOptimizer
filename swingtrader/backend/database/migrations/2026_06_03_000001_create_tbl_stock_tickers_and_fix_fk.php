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
        $etfs = ['SPY', 'QQQ', 'IWM', 'VTI', 'VTV', 'BLENDED'];

        // 1. Drop existing FK constraints on scanner tables
        foreach ($this->scannerTables as $table) {
            Schema::table($table, function (Blueprint $t) {
                $t->dropForeign(['ticker_id']);
            });
        }

        // 2. Create tbl_stock_tickers and populate with non-ETF symbols
        Schema::create('tbl_stock_tickers', function (Blueprint $table) {
            $table->id();
            $table->string('symbol', 10)->unique();
            $table->boolean('enabled')->default(true);
            $table->timestamps();
        });

        DB::statement("
            INSERT INTO tbl_stock_tickers (symbol, enabled, created_at, updated_at)
            SELECT symbol, enabled, COALESCE(created_at, NOW()), NOW()
            FROM tbl_etf_tickers
            WHERE symbol NOT IN ('" . implode("','", $etfs) . "')
        ");

        // 3. Re-point scanner ticker_id to tbl_stock_tickers.id
        foreach ($this->scannerTables as $table) {
            DB::statement("
                UPDATE {$table} s
                SET ticker_id = st.id
                FROM tbl_stock_tickers st
                WHERE st.symbol = (
                    SELECT e.symbol FROM tbl_etf_tickers e WHERE e.id = s.ticker_id
                )
            ");
        }

        // 4. Add new FK constraints pointing to tbl_stock_tickers
        foreach ($this->scannerTables as $table) {
            Schema::table($table, function (Blueprint $t) {
                $t->foreign('ticker_id')->references('id')->on('tbl_stock_tickers')->onDelete('cascade');
            });
        }

        // 5. Remove stock rows from tbl_etf_tickers (keep only ETFs)
        DB::statement("DELETE FROM tbl_etf_tickers WHERE symbol NOT IN ('" . implode("','", $etfs) . "')");
    }

    public function down(): void
    {
        $etfs = ['SPY', 'QQQ', 'IWM', 'VTI', 'VTV', 'BLENDED'];

        // Reverse: insert stock rows back into tbl_etf_tickers
        DB::statement("
            INSERT INTO tbl_etf_tickers (symbol, enabled, allocation_weight, created_at, updated_at)
            SELECT symbol, enabled, 10.0000, COALESCE(created_at, NOW()), NOW()
            FROM tbl_stock_tickers
            ON CONFLICT (symbol) DO NOTHING
        ");

        // Drop FK and re-point to tbl_etf_tickers
        foreach ($this->scannerTables as $table) {
            Schema::table($table, function (Blueprint $t) {
                $t->dropForeign(['ticker_id']);
            });

            DB::statement("
                UPDATE {$table} s
                SET ticker_id = e.id
                FROM tbl_etf_tickers e
                WHERE e.symbol = (
                    SELECT st.symbol FROM tbl_stock_tickers st WHERE st.id = s.ticker_id
                )
            ");

            Schema::table($table, function (Blueprint $t) {
                $t->foreign('ticker_id')->references('id')->on('tbl_etf_tickers')->onDelete('cascade');
            });
        }

        Schema::dropIfExists('tbl_stock_tickers');
    }
};
