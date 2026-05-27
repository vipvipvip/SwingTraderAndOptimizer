<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class LiveTrade extends Model
{
    protected $fillable = ['ticker_id', 'symbol', 'side', 'quantity', 'entry_price', 'exit_price', 'entry_at', 'exit_at', 'status', 'pnl_dollar', 'pnl_pct', 'alpaca_order_id', 'strategy_signal'];
    protected $casts = ['entry_at' => 'datetime', 'exit_at' => 'datetime'];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
