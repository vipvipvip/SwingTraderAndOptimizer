<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->dropColumn([
                'macd_slow',
                'macd_signal',
                'ema_signal',
                'sma_signal',
                'sma_50',
                'sma_200',
                'ppo_fast',
                'ppo_slow',
            ]);
        });
    }

    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->integer('macd_slow')->default(29)->nullable();
            $table->integer('macd_signal')->default(14)->nullable();
            $table->integer('ema_signal')->default(10)->nullable();
            $table->integer('sma_signal')->default(40)->nullable();
            $table->integer('sma_50')->default(50)->nullable();
            $table->integer('sma_200')->default(200)->nullable();
            $table->integer('ppo_fast')->default(12)->nullable();
            $table->integer('ppo_slow')->default(26)->nullable();
        });
    }
};
