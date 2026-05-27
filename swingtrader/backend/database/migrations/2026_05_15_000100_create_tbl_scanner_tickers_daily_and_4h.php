<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::dropIfExists('tbl_scanner_tickers_daily');
        Schema::create('tbl_scanner_tickers_daily', function (Blueprint $table) {
            $table->id();
            $table->string('ticker', 10);
            $table->date('date');
            $table->decimal('open', 12, 4);
            $table->decimal('high', 12, 4);
            $table->decimal('low', 12, 4);
            $table->decimal('close', 12, 4);
            $table->bigInteger('volume');

            $table->decimal('macd_line', 16, 8)->nullable();
            $table->decimal('macd_signal', 16, 8)->nullable();
            $table->decimal('macd_histogram', 16, 8)->nullable();
            $table->boolean('macd_crossover')->default(false);

            $table->decimal('ppo_line', 16, 8)->nullable();
            $table->decimal('ppo_signal', 16, 8)->nullable();
            $table->decimal('ppo_histogram', 16, 8)->nullable();
            $table->boolean('ppo_crossover')->default(false);

            $table->timestamps();

            $table->unique(['ticker', 'date']);
            $table->index('ticker');
            $table->index('date');
            $table->index(['ticker', 'date']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('tbl_scanner_tickers_daily');
    }
};
