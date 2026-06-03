<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->renameColumn('macd_fast', 'chandelier_period');
            $table->renameColumn('bb_period', 'atr_period');
            $table->renameColumn('bb_std', 'chandelier_mult');
        });
    }

    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->renameColumn('chandelier_period', 'macd_fast');
            $table->renameColumn('atr_period', 'bb_period');
            $table->renameColumn('chandelier_mult', 'bb_std');
        });
    }
};
