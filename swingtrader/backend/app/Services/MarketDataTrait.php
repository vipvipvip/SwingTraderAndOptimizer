<?php

namespace App\Services;

trait MarketDataTrait
{
    private function getOhlcBars($symbol)
    {
        try {
            $rows = \DB::table('bars')
                ->join('tbl_etf_tickers', 'bars.ticker_id', '=', 'tbl_etf_tickers.id')
                ->where('tbl_etf_tickers.symbol', $symbol)
                ->orderBy('bars.timestamp', 'asc')
                ->get(['bars.timestamp', 'bars.high', 'bars.low', 'bars.close']);

            if ($rows->isEmpty()) {
                return [];
            }

            $bars = [];
            foreach ($rows as $row) {
                $ts = $row->timestamp;
                if (date('G', strtotime($ts)) == 4 || date('G', strtotime($ts)) == 5) {
                    if (date('i', strtotime($ts)) == 0) {
                        $bars[] = [
                            'timestamp' => $ts,
                            'high' => floatval($row->high),
                            'low' => floatval($row->low),
                            'close' => floatval($row->close),
                        ];
                    }
                }
            }

            return $bars;
        } catch (\Exception $e) {
            \Log::error("$symbol: Error fetching OHLC bars: " . $e->getMessage());
            return [];
        }
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
