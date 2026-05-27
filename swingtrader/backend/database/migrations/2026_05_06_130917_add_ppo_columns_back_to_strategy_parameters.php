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
            if (!Schema::hasColumn('strategy_parameters', 'ppo_fast')) {
                $table->integer('ppo_fast')->default(12)->nullable();
            }
            if (!Schema::hasColumn('strategy_parameters', 'ppo_slow')) {
                $table->integer('ppo_slow')->default(26)->nullable();
            }
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->dropColumn(['ppo_fast', 'ppo_slow']);
        });
    }
};
