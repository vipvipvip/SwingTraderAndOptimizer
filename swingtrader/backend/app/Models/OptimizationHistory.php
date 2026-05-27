<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class OptimizationHistory extends Model
{
    public $timestamps = false;
    protected $table = 'optimization_history';
    protected $fillable = ['ticker_id', 'best_sharpe', 'best_win_rate', 'best_return', 'total_combinations', 'runtime_seconds'];

    public function ticker()
    {
        return $this->belongsTo(Ticker::class, 'ticker_id');
    }
}
