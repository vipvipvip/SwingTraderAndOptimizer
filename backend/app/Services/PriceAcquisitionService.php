<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\IntraDayPrice;
use Carbon\Carbon;
use Illuminate\Support\Facades\Log;

class PriceAcquisitionService
{
    private $alpacaService;

    public function __construct(AlpacaService $alpacaService)
    {
        $this->alpacaService = $alpacaService;
    }

    /**
     * Fetch latest prices for all active tickers
     * Returns array of ticker_id => current_price
     */
    public function fetchLatestPrices()
    {
        $tickers = Ticker::where('enabled', 1)->get();
        $prices = [];

        foreach ($tickers as $ticker) {
            try {
                $price = $this->getPriceForTicker($ticker);
                if ($price) {
                    $prices[$ticker->id] = $price;
                    $this->savePriceSnapshot($ticker, $price);
                    Log::info("Fetched {$ticker->symbol}: \${$price}");
                }
            } catch (\Exception $e) {
                Log::warning("Failed to fetch price for {$ticker->symbol}: " . $e->getMessage());
            }
        }

        return $prices;
    }

    /**
     * Get current price for a single ticker
     */
    private function getPriceForTicker(Ticker $ticker)
    {
        try {
            return $this->fetchWSJPrice($ticker->symbol);
        } catch (\Exception $e) {
            Log::warning("getPriceForTicker failed for {$ticker->symbol}: " . $e->getMessage());
            return null;
        }
    }

    /**
     * Fetch current price using multiple free sources (fallback chain)
     */
    private function fetchWSJPrice($symbol)
    {
        // Try IEX API (free tier)
        try {
            return $this->fetchIEXPrice($symbol);
        } catch (\Exception $e) {
            Log::debug("IEX fetch failed: " . $e->getMessage());
        }

        // Fallback: return account equity instead of failing
        throw new \Exception("Could not fetch price from any source");
    }

    /**
     * Fetch from IEX Cloud (free tier available)
     */
    private function fetchIEXPrice($symbol)
    {
        $token = env('IEX_CLOUD_TOKEN', 'pk_test0123456789');
        $url = "https://cloud.iexapis.com/v1/data/core_quote/{$symbol}?token={$token}";

        $response = \Illuminate\Support\Facades\Http::timeout(5)->get($url);

        if ($response->failed()) {
            throw new \Exception("IEX API error: " . $response->status());
        }

        $data = $response->json();
        $price = $data[0]['latestPrice'] ?? $data['latestPrice'] ?? null;

        if (!$price || $price === 0) {
            throw new \Exception("No valid price in IEX response");
        }

        return floatval($price);
    }

    /**
     * Save price snapshot to intra_day_prices table
     */
    private function savePriceSnapshot(Ticker $ticker, $price)
    {
        try {
            $now = Carbon::now(config('app.timezone'));
            $priceType = $this->determinePriceType($now);

            IntraDayPrice::updateOrCreate(
                [
                    'ticker_id' => $ticker->id,
                    'price_time' => $now->toDateTimeString(),
                    'price_type' => $priceType,
                ],
                [
                    'symbol' => $ticker->symbol,
                    'close' => $price,
                    'source' => 'alpaca',
                ]
            );
        } catch (\Exception $e) {
            Log::error("Failed to save price snapshot: " . $e->getMessage());
        }
    }

    /**
     * Determine price type based on time of day (EST)
     */
    private function determinePriceType(Carbon $time)
    {
        $hour = $time->hour;
        $minute = $time->minute;

        // 9:30 AM EST
        if ($hour === 9 && $minute >= 30 && $minute < 31) {
            return 'market_open';
        }

        // 4:00 PM EST
        if ($hour === 16 && $minute >= 0 && $minute < 1) {
            return 'market_close';
        }

        // On the hour (10 AM, 11 AM, 12 PM, 1 PM, 2 PM, 3 PM EST)
        if ($minute >= 0 && $minute < 1 && in_array($hour, [10, 11, 12, 13, 14, 15])) {
            return 'hourly_snapshot';
        }

        return 'intraday_snapshot';
    }

    /**
     * Get last known price for a ticker
     */
    public function getLastKnownPrice($tickerId)
    {
        $lastPrice = IntraDayPrice::where('ticker_id', $tickerId)
            ->orderBy('price_time', 'desc')
            ->first();

        return $lastPrice ? floatval($lastPrice->close) : null;
    }

    /**
     * Check if we should fetch prices (market hours, trading days)
     */
    public function shouldFetchPrices()
    {
        $now = Carbon::now(config('app.timezone'));

        // Only on weekdays
        if ($now->isWeekend()) {
            return false;
        }

        // Market hours: 9:30 AM - 4:00 PM EST
        $hour = $now->hour;
        $minute = $now->minute;

        // Before 9:30 AM
        if ($hour < 9 || ($hour === 9 && $minute < 30)) {
            return false;
        }

        // After 4:00 PM
        if ($hour > 16) {
            return false;
        }

        return true;
    }

    /**
     * Check if it's time to fetch (specific times: 9:30, hourly, 4:00 PM)
     */
    public function isTimeToFetch()
    {
        if (!$this->shouldFetchPrices()) {
            return false;
        }

        $now = Carbon::now(config('app.timezone'));
        $minute = $now->minute;

        // Fetch on minute 0 (9:30, 10:00, 11:00, etc) or minute 30 (9:30 AM)
        return ($minute === 0 && in_array($now->hour, [9, 10, 11, 12, 13, 14, 15, 16]))
            || ($now->hour === 9 && $minute >= 30 && $minute < 31);
    }
}
