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
            $table->unsignedBigInteger('ticker_id');
            $table->string('symbol');
            $table->decimal('entry_price', 10, 2);
            $table->decimal('exit_price', 10, 2)->nullable();
            $table->datetime('entry_at');
            $table->datetime('exit_at')->nullable();
            $table->decimal('pnl_dollar', 12, 2)->nullable();
            $table->decimal('pnl_pct', 8, 4)->nullable();
            $table->string('optimization_run')->nullable();
            $table->timestamps();

            $table->foreign('ticker_id')->references('id')->on('tickers')->onDelete('cascade');
            $table->index('symbol');
            $table->index('optimization_run');
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
