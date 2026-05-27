<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::dropIfExists('strategy_configs');
        Schema::dropIfExists('backtest_signals');
        Schema::dropIfExists('intra_day_prices');
    }

    public function down(): void
    {
    }
};
