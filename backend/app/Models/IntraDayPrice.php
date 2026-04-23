<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class IntraDayPrice extends Model
{
    protected $fillable = [
        'ticker_id',
        'symbol',
        'price_time',
        'open',
        'high',
        'low',
        'close',
        'volume',
        'source',
        'price_type',
    ];

    protected $casts = [
        'price_time' => 'datetime',
        'open' => 'float',
        'high' => 'float',
        'low' => 'float',
        'close' => 'float',
    ];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class);
    }
}
