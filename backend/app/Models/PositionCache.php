<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class PositionCache extends Model
{
    protected $fillable = ['symbol', 'qty', 'avg_entry_price', 'current_price', 'unrealized_pnl', 'market_value', 'side', 'last_synced_at'];
    protected $casts = ['last_synced_at' => 'datetime'];
}
