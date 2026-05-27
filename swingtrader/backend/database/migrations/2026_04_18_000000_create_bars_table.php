<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('bars', function (Blueprint $table) {
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
    }

    public function down(): void
    {
        Schema::dropIfExists('bars');
    }
};
