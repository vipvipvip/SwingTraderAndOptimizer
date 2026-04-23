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
        // Create new bars_new table with correct schema
        Schema::create('bars_new', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id')->index();
            $table->timestamp('timestamp');
            $table->decimal('open', 12, 4);
            $table->decimal('high', 12, 4);
            $table->decimal('low', 12, 4);
            $table->decimal('close', 12, 4);
            $table->bigInteger('volume');
            $table->string('source')->default('alpaca');
            $table->timestamp('fetched_at')->useCurrent();

            $table->unique(['ticker_id', 'timestamp']);
            $table->index(['ticker_id', 'timestamp'], 'idx_ticker_timestamp');
            $table->foreign('ticker_id')->references('id')->on('tickers')->onDelete('cascade');
        });

        // Copy data from old bars table to new one
        DB::statement('
            INSERT INTO bars_new (id, ticker_id, timestamp, open, high, low, close, volume, source, fetched_at)
            SELECT b.id, t.id, b.timestamp, b.open, b.high, b.low, b.close, b.volume, b.source, b.fetched_at
            FROM bars b
            JOIN tickers t ON b.symbol = t.symbol
        ');

        // Drop old table and rename
        Schema::drop('bars');
        Schema::rename('bars_new', 'bars');
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::create('bars_old', function (Blueprint $table) {
            $table->id();
            $table->string('symbol');
            $table->timestamp('timestamp');
            $table->decimal('open', 12, 4);
            $table->decimal('high', 12, 4);
            $table->decimal('low', 12, 4);
            $table->decimal('close', 12, 4);
            $table->bigInteger('volume');
            $table->string('source')->default('alpaca');
            $table->timestamp('fetched_at')->useCurrent();

            $table->unique(['symbol', 'timestamp']);
            $table->index(['symbol', 'timestamp'], 'idx_symbol_timestamp');
        });

        // Restore data
        DB::statement('
            INSERT INTO bars_old (id, symbol, timestamp, open, high, low, close, volume, source, fetched_at)
            SELECT b.id, t.symbol, b.timestamp, b.open, b.high, b.low, b.close, b.volume, b.source, b.fetched_at
            FROM bars b
            JOIN tickers t ON b.ticker_id = t.id
        ');

        Schema::drop('bars');
        Schema::rename('bars_old', 'bars');
    }
};
