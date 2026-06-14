<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class StrategyParameter extends Model
{
    public $timestamps = false;
    protected $table = 'strategy_parameters';
    protected $fillable = ['ticker_id', 'chandelier_period', 'atr_period', 'chandelier_mult', 'chandelier_entry_mult', 'reg_slope_window', 'reg_slope_threshold', 'reg_slope_type', 'win_rate', 'sharpe_ratio', 'total_return', 'total_trades'];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
