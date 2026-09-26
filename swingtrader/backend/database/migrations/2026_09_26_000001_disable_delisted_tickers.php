<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;

/**
 * Disable delisted/acquired tickers and purge the fabricated bars Alpaca emits
 * for them after their final real trade.
 *
 * For a delisted symbol Alpaca keeps returning a *repeated last-price snapshot*
 * for subsequent dates: open = high = low = close = <last trade>, volume = 0.
 * That is not market data. Left in place it makes a dead stock look like it has
 * a live price through today, which poisons the ATR stop and the scanner.
 *
 * The weekly table is already correct for these symbols (it simply stops at the
 * last traded week), so only the daily fabricated tail is removed.
 *
 * Detection is deliberately narrow: a zero-volume flat bar on its own is normal
 * (halts, and genuinely illiquid names like FCAP/WTM emit many of them), so this
 * only deletes the contiguous block of such rows that trails the last real bar,
 * and only for an explicit symbol list.
 *
 * down() re-enables the symbols. Deleted bars are not recreated — restore from
 * /tmp/opencode/etf_bk/bars_pre_etf_backfill.sql if ever needed.
 */
return new class extends Migration
{
    /** Confirmed delisted / acquired: no real trade since the date noted. */
    private const DEAD = [
        'EA'   => '2026-08-04', // delisted
        'AVB'  => '2026-08-14', // acquired, no prints after
        'EQR'  => '2026-08-17', // acquired, no prints after
        'WBS'  => '2026-08-19', // acquired, no prints after
        'APGE' => '2026-09-02', // acquired, no prints after
    ];

    public function up(): void
    {
        DB::table('tbl_stock_tickers')
            ->whereIn('symbol', array_keys(self::DEAD))
            ->update(['enabled' => false, 'updated_at' => now()]);

        foreach (self::DEAD as $symbol => $lastReal) {
            $id = DB::table('tbl_stock_tickers')->where('symbol', $symbol)->value('id');
            if ($id === null) {
                continue;
            }

            $deleted = DB::table('tbl_scanner_tickers_daily')
                ->where('ticker_id', $id)
                ->where('date', '>', $lastReal)
                ->where('volume', 0)
                ->whereRaw('open = high AND high = low AND low = close')
                ->delete();

            if ($deleted > 0) {
                \Illuminate\Support\Facades\Log::info(sprintf(
                    'disabled %s, purged %d fabricated daily bar(s) after %s',
                    $symbol, $deleted, $lastReal
                ));
            }
        }
    }

    public function down(): void
    {
        DB::table('tbl_stock_tickers')
            ->whereIn('symbol', array_keys(self::DEAD))
            ->update(['enabled' => true, 'updated_at' => now()]);
    }
};
