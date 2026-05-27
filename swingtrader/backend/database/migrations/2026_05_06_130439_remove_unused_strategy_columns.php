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
            // Remove unused PPO columns (not used in signal logic)
            if (Schema::hasColumn('strategy_parameters', 'ppo_fast')) {
                $table->dropColumn('ppo_fast');
            }
            if (Schema::hasColumn('strategy_parameters', 'ppo_slow')) {
                $table->dropColumn('ppo_slow');
            }

            // Remove old SMA columns (replaced by sma_signal, sma_50, sma_200)
            if (Schema::hasColumn('strategy_parameters', 'sma_short')) {
                $table->dropColumn('sma_short');
            }
            if (Schema::hasColumn('strategy_parameters', 'sma_long')) {
                $table->dropColumn('sma_long');
            }
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->integer('sma_short')->default(40)->nullable();
            $table->integer('sma_long')->default(200)->nullable();
            $table->integer('ppo_fast')->default(12)->nullable();
            $table->integer('ppo_slow')->default(26)->nullable();
        });
    }
};
