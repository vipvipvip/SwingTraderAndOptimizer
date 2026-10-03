<?php

namespace App\Services;

trait MarketDataTrait
{
    /**
     * RETIRED 2026-10-02 — always returns [].
     *
     * This built the CoreEW chandelier entry/stop from 04:00-06:00 ET pre-market
     * hourly bars. tbl_scanner_tickers_1hour was purged, and the newest such bar
     * was already 2026-09-15 (the hourly backfill that fetched them stopped
     * running), so the series has been unusable since mid-September. Callers
     * already treat an empty result as "no ATR" and skip, which is exactly what
     * has been happening in production. strategy_parameters is also empty, so
     * $entryMult is null and the chandelier override is bypassed regardless.
     *
     * Do NOT repoint this at daily bars: chandelier ATR(18) over pre-market
     * hours is a different quantity from atr_stop (ATR 14, regular session), so
     * substituting it would silently change live entry/stop behaviour. Any new
     * CoreEW variant goes in PHP per the backtest/live parity rule.
     */
    private function getOhlcBars($symbol)
    {
        return [];
    }
    private function calculateATR($ohlc, $period)
    {
        $n = count($ohlc);
        if ($n < $period + 1) {
            return null;
        }

        $trValues = [];
        for ($i = 1; $i < $n; $i++) {
            $high = $ohlc[$i]['high'];
            $low = $ohlc[$i]['low'];
            $prevClose = $ohlc[$i - 1]['close'];
            $trValues[] = max(
                $high - $low,
                abs($high - $prevClose),
                abs($low - $prevClose)
            );
        }

        $start = count($trValues) - $period;
        $sum = 0;
        for ($i = $start; $i < count($trValues); $i++) {
            $sum += $trValues[$i];
        }
        return $sum / $period;
    }
}
