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
        Schema::create('backtest_trades', function (Blueprint $table) {
            $table->id();
            $table->foreignId('ticker_id')->constrained('tickers')->onDelete('cascade');
            $table->dateTime('entry_at');
            $table->decimal('entry_price', 10, 2);
            $table->dateTime('exit_at');
            $table->decimal('exit_price', 10, 2);
            $table->decimal('return', 8, 6);
            $table->decimal('pnl_dollar', 12, 2);
            $table->integer('days_held');
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('backtest_trades');
    }
};
