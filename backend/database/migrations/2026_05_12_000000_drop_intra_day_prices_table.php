<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::dropIfExists('intra_day_prices');
    }

    public function down(): void
    {
        Schema::create('intra_day_prices', function ($table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id')->index();
            $table->string('symbol');
            $table->timestamp('price_time');
            $table->decimal('open', 12, 4)->nullable();
            $table->decimal('high', 12, 4)->nullable();
            $table->decimal('low', 12, 4)->nullable();
            $table->decimal('close', 12, 4);
            $table->bigInteger('volume')->nullable();
            $table->string('source')->default('alpaca');
            $table->string('price_type');
            $table->timestamps();
            $table->unique(['ticker_id', 'price_time', 'price_type']);
            $table->foreign('ticker_id')->references('id')->on('tickers')->onDelete('cascade');
        });
    }
};
