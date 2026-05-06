<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class BacktestTrade extends Model
{
    protected $fillable = [
        'ticker_id',
        'entry_at',
        'entry_price',
        'exit_at',
        'exit_price',
        'return',
        'pnl_dollar',
        'days_held',
    ];

    protected $casts = [
        'entry_at' => 'datetime',
        'exit_at' => 'datetime',
        'entry_price' => 'decimal:2',
        'exit_price' => 'decimal:2',
        'return' => 'decimal:6',
        'pnl_dollar' => 'decimal:2',
    ];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
