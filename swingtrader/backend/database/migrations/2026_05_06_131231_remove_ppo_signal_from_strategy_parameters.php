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
            if (Schema::hasColumn('strategy_parameters', 'ppo_signal')) {
                $table->dropColumn('ppo_signal');
            }
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            if (!Schema::hasColumn('strategy_parameters', 'ppo_signal')) {
                $table->integer('ppo_signal')->default(9)->nullable();
            }
        });
    }
};
