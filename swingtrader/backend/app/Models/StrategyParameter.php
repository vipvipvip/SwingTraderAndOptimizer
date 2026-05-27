<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class StrategyParameter extends Model
{
    public $timestamps = false;
    protected $table = 'strategy_parameters';
    protected $fillable = ['ticker_id', 'macd_fast', 'bb_period', 'bb_std', 'win_rate', 'sharpe_ratio', 'total_return', 'total_trades'];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
