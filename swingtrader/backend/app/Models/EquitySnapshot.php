<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class EquitySnapshot extends Model
{
    protected $fillable = ['ticker_id', 'snapshot_date', 'equity_value', 'snapshot_type', 'source'];
    protected $casts = ['snapshot_date' => 'date'];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
