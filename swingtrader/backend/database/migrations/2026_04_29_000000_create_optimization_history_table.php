<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('optimization_history', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id');
            $table->timestamp('run_date')->useCurrent();
            $table->decimal('best_sharpe', 10, 2)->nullable();
            $table->decimal('best_win_rate', 8, 4)->nullable();
            $table->decimal('best_return', 10, 4)->nullable();
            $table->integer('total_combinations')->nullable();
            $table->integer('runtime_seconds')->nullable();

            $table->foreign('ticker_id')->references('id')->on('tickers')->onDelete('cascade');
            $table->index(['ticker_id', 'run_date']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('optimization_history');
    }
};
