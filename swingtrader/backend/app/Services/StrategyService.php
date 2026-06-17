<?php

namespace App\Services;

use App\Models\Ticker;
use App\Models\StrategyParameter;
use App\Models\OptimizationHistory;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Carbon;

class StrategyService
{
    use MarketDataTrait;

    private array $livePrices = [];

    public function prefetchLivePrices(array $symbols): void
    {
        try {
            $alpaca = app(AlpacaService::class);
            // Try positions first (already cached, includes current_price)
            $positions = $alpaca->getPositions();
            foreach ($positions as $pos) {
                if (isset($pos['symbol'], $pos['current_price'])) {
                    $this->livePrices[$pos['symbol']] = floatval($pos['current_price']);
                }
            }
            // Fetch latest trades for any symbols not covered by positions
            $missing = array_diff($symbols, array_keys($this->livePrices));
            if (!empty($missing)) {
                $latest = $alpaca->getLatestPrices($missing);
                foreach ($latest as $sym => $price) {
                    if ($price > 0) $this->livePrices[$sym] = $price;
                }
            }
        } catch (\Exception $e) {
            // Fall back to last bar close silently
        }
    }

    private function timestampsToNy($params)
    {
        if (!$params) return null;
        foreach (['created_at', 'updated_at'] as $field) {
            if (isset($params[$field])) {
                $params[$field] = Carbon::parse($params[$field], 'UTC')
                    ->setTimezone('America/New_York')
                    ->toDateTimeString();
            }
        }
        return $params;
    }

    private function addLiveMetrics(&$entry)
    {
        $symbol = $entry['symbol'];
        $params = $entry['params'] ?? null;
        if (!$params) {
            $entry['price'] = null;
            $entry['high'] = null;
            $entry['stop'] = null;
            $entry['atr'] = null;
            $entry['entry_level'] = null;
            $entry['in_position'] = false;
            return;
        }

        $period = intval($params['chandelier_period'] ?? 18);
        $mult = floatval($params['chandelier_mult'] ?? 3.0);
        $entryMult = isset($params['chandelier_entry_mult']) ? floatval($params['chandelier_entry_mult']) : null;

        // Check if there's an open position
        $openTrade = \App\Models\LiveTrade::where('symbol', $symbol)
            ->where('status', 'open')
            ->first();
        $entry['in_position'] = $openTrade !== null;

        $ohlc = $this->getOhlcBars($symbol);
        if (empty($ohlc) || count($ohlc) < $period + 1) {
            $entry['price'] = $openTrade ? round($openTrade->entry_price, 2) : null;
            $entry['high'] = null;
            $entry['stop'] = null;
            $entry['atr'] = null;
            $entry['entry_level'] = null;
            return;
        }

        $last = $ohlc[count($ohlc) - 1];
        $atr = $this->calculateATR($ohlc, $period);
        $entry['high'] = round($last['high'], 2);
        $entry['atr'] = $atr !== null ? round($atr, 2) : null;
        $entry['current_price'] = isset($this->livePrices[$symbol])
            ? round($this->livePrices[$symbol], 2) : round($last['close'], 2);

        if ($openTrade) {
            // In position — show entry price and trailing stop
            $entry['price'] = round($openTrade->entry_price, 2);
            $entry['pnl_unrealized'] = round(($last['close'] - $openTrade->entry_price) / $openTrade->entry_price * 100, 2);

            // Compute entry trigger level
            if ($entryMult !== null && $atr !== null) {
                $rollingHigh = max(array_column(array_slice($ohlc, -$period), 'high'));
                $entryLevel = $rollingHigh - $atr * $entryMult;
                $entry['entry_level'] = round($entryLevel, 2);
            }

            // Compute trailing stop: highest_high_since_entry - ATR * mult
            $entryDate = $openTrade->entry_at;
            $highestHigh = $last['high'];
            foreach ($ohlc as $bar) {
                if ($bar['timestamp'] >= $entryDate && $bar['high'] > $highestHigh) {
                    $highestHigh = $bar['high'];
                }
            }
            if ($atr !== null) {
                $entry['stop'] = round($highestHigh - $atr * $mult, 2);
            }
        } else {
            // No position — show chandelier entry level or next-bar close
            if ($entryMult !== null && $atr !== null) {
                $rollingHigh = max(array_column(array_slice($ohlc, -$period), 'high'));
                $entryLevel = $rollingHigh - $atr * $entryMult;
                $entry['price'] = round($entryLevel, 2);
                $entry['entry_level'] = round($entryLevel, 2);
            } else {
                $entry['price'] = round($last['close'], 2);
            }

            // No trailing stop when not in position
            if ($atr !== null) {
                $entry['stop'] = round($last['high'] - $atr * $mult, 2);
            }
        }
    }

    public function getAllTickers()
    {
        // Prefetch live prices for all enabled tickers in one Alpaca call
        $symbols = Ticker::whereEnabled(1)->where('symbol', '!=', 'BLENDED')->pluck('symbol')->toArray();
        $this->prefetchLivePrices($symbols);

        $portfolio = Ticker::where('symbol', 'BLENDED')
            ->with('strategyParameter')
            ->first();

        $portfolioEntry = null;
        if ($portfolio && $portfolio->strategyParameter) {
            $params = $this->timestampsToNy($portfolio->strategyParameter->toArray());
            $params['is_portfolio'] = true;
            $portfolioEntry = [
                'symbol' => 'BLENDED',
                'id' => $portfolio->id,
                'allocation_weight' => 100,
                'params' => $params,
            ];
            $this->addLiveMetrics($portfolioEntry);
        }

        $tickers = Ticker::whereEnabled(1)
            ->where('symbol', '!=', 'BLENDED')
            ->with('strategyParameter')
            ->get()
            ->map(function ($ticker) {
                $entry = [
                    'symbol' => $ticker->symbol,
                    'id' => $ticker->id,
                    'allocation_weight' => (float) $ticker->allocation_weight,
                    'params' => $this->timestampsToNy(
                        $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null
                    ),
                ];
                $this->addLiveMetrics($entry);
                return $entry;
            })->toArray();

        $result = $portfolioEntry ? [$portfolioEntry, ...$tickers] : $tickers;
        return $result;
    }

    public function getStrategyForSymbol($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return null;
        }

        $entry = [
            'symbol' => $symbol,
            'ticker' => $ticker->toArray(),
            'params' => $this->timestampsToNy(
                $ticker->strategyParameter ? $ticker->strategyParameter->toArray() : null
            ),
        ];
        $this->addLiveMetrics($entry);

        return $entry;
    }

    public function getOptimizationHistory($symbol, $limit = 10)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return [];
        }

        return OptimizationHistory::where('ticker_id', $ticker->id)
            ->orderBy('run_date', 'desc')
            ->limit($limit)
            ->get()
            ->map(function ($row) {
                if (isset($row['run_date'])) {
                    $row['run_date'] = Carbon::parse($row['run_date'], 'UTC')
                        ->setTimezone('America/New_York')
                        ->toDateTimeString();
                }
                return $row;
            })
            ->toArray();
    }

    public function getSummary()
    {
        // Portfolio return from BLENDED strategy parameters
        $blended = Ticker::where('symbol', 'BLENDED')
            ->with('strategyParameter')
            ->first();
        $portfolioReturn = null;
        if ($blended && $blended->strategyParameter) {
            $portfolioReturn = (float) $blended->strategyParameter->total_return;
        }

        // SPY buy-and-hold return over the backtest period
        $spy = Ticker::where('symbol', 'SPY')->first();
        $sp500Return = null;
        if ($spy) {
            $firstBar = DB::table('bars')
                ->where('ticker_id', $spy->id)
                ->where('source', 'alpaca')
                ->orderBy('timestamp')
                ->first(['timestamp', 'close']);
            $lastBar = DB::table('bars')
                ->where('ticker_id', $spy->id)
                ->where('source', 'alpaca')
                ->orderByDesc('timestamp')
                ->first(['timestamp', 'close']);
            if ($firstBar && $lastBar && (float) $firstBar->close > 0) {
                $sp500Return = ((float) $lastBar->close - (float) $firstBar->close) / (float) $firstBar->close;
            }
        }

        return [
            'portfolio_return' => $portfolioReturn,
            'sp500_return' => $sp500Return,
        ];
    }

    public function getLatestOptimization($symbol)
    {
        $ticker = Ticker::where('symbol', $symbol)->first();
        if (!$ticker) {
            return null;
        }

        return OptimizationHistory::where('ticker_id', $ticker->id)
            ->orderBy('run_date', 'desc')
            ->first();
    }
}
