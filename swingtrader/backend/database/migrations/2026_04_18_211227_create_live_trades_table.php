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
        Schema::create('live_trades', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id')->nullable();
            $table->string('symbol');
            $table->enum('side', ['BUY', 'SELL']);
            $table->integer('quantity');
            $table->decimal('entry_price', 12, 4);
            $table->decimal('exit_price', 12, 4)->nullable();
            $table->timestamp('entry_at');
            $table->timestamp('exit_at')->nullable();
            $table->enum('status', ['open', 'closed'])->default('open');
            $table->decimal('pnl_dollar', 12, 4)->nullable();
            $table->decimal('pnl_pct', 6, 4)->nullable();
            $table->string('alpaca_order_id')->nullable();
            $table->string('strategy_signal')->nullable();
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('live_trades');
    }
};
