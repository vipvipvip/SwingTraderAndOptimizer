<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Ticker extends Model
{
    public $timestamps = false;
    protected $fillable = ['symbol', 'enabled'];

    public function strategyParameter()
    {
        return $this->hasOne(StrategyParameter::class, 'ticker_id');
    }

    public function optimizationHistory()
    {
        return $this->hasMany(OptimizationHistory::class, 'ticker_id');
    }
}
