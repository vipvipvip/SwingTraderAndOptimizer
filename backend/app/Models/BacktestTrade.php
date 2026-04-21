<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class BacktestTrade extends Model
{
    protected $fillable = [
        'ticker_id',
        'symbol',
        'entry_price',
        'exit_price',
        'entry_at',
        'exit_at',
        'pnl_dollar',
        'pnl_pct',
        'optimization_run',
    ];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
