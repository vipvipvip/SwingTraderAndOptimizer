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
        Schema::create('positions_cache', function (Blueprint $table) {
            $table->id();
            $table->string('symbol')->unique();
            $table->integer('qty');
            $table->decimal('avg_entry_price', 12, 4);
            $table->decimal('current_price', 12, 4);
            $table->decimal('unrealized_pnl', 12, 4)->nullable();
            $table->decimal('market_value', 14, 2);
            $table->enum('side', ['long', 'short']);
            $table->timestamp('last_synced_at')->useCurrent();
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('positions_cache');
    }
};
