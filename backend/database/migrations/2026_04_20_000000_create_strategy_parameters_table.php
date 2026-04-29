<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('strategy_parameters', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id')->unique();
            $table->integer('macd_fast');
            $table->integer('macd_slow');
            $table->integer('macd_signal');
            $table->integer('sma_short');
            $table->integer('sma_long');
            $table->integer('bb_period');
            $table->decimal('bb_std', 8, 4);
            $table->decimal('win_rate', 8, 4)->nullable();
            $table->decimal('sharpe_ratio', 10, 4)->nullable();
            $table->decimal('total_return', 10, 4)->nullable();
            $table->integer('total_trades')->nullable();
            $table->timestamps();

            $table->foreign('ticker_id')->references('id')->on('tickers')->onDelete('cascade');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('strategy_parameters');
    }
};
