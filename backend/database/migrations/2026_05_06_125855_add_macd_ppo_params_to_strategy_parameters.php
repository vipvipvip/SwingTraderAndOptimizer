<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            // PPO parameters (new)
            if (!Schema::hasColumn('strategy_parameters', 'ppo_fast')) {
                $table->integer('ppo_fast')->default(12)->nullable();
            }
            if (!Schema::hasColumn('strategy_parameters', 'ppo_slow')) {
                $table->integer('ppo_slow')->default(26)->nullable();
            }

            // EMA/SMA parameters for signal (new)
            if (!Schema::hasColumn('strategy_parameters', 'ema_signal')) {
                $table->integer('ema_signal')->default(10)->nullable();
            }
            if (!Schema::hasColumn('strategy_parameters', 'sma_signal')) {
                $table->integer('sma_signal')->default(40)->nullable();
            }
            if (!Schema::hasColumn('strategy_parameters', 'sma_50')) {
                $table->integer('sma_50')->default(50)->nullable();
            }
            if (!Schema::hasColumn('strategy_parameters', 'sma_200')) {
                $table->integer('sma_200')->default(200)->nullable();
            }

            // Update MACD defaults
            $table->integer('macd_fast')->default(26)->change();
            $table->integer('macd_slow')->default(29)->change();
            $table->integer('macd_signal')->default(14)->change();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->dropColumn([
                'ppo_fast',
                'ppo_slow',
                'ema_signal',
                'sma_signal',
                'sma_50',
                'sma_200',
            ]);
        });
    }
};
