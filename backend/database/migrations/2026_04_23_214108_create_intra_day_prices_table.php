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
        Schema::create('intra_day_prices', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id')->index();
            $table->string('symbol');
            $table->timestamp('price_time'); // Time when price was captured (EST)
            $table->decimal('open', 12, 4)->nullable();
            $table->decimal('high', 12, 4)->nullable();
            $table->decimal('low', 12, 4)->nullable();
            $table->decimal('close', 12, 4);
            $table->bigInteger('volume')->nullable();
            $table->string('source')->default('alpaca'); // alpaca, google, yahoo, etc
            $table->string('price_type'); // market_open, market_close, hourly_snapshot
            $table->timestamps();

            $table->unique(['ticker_id', 'price_time', 'price_type']);
            $table->foreign('ticker_id')->references('id')->on('tickers')->onDelete('cascade');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('intra_day_prices');
    }
};
