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
        Schema::create('equity_snapshots', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('ticker_id')->nullable();
            $table->date('snapshot_date');
            $table->decimal('equity_value', 14, 2);
            $table->enum('snapshot_type', ['backtest', 'live', 'account']);
            $table->string('source')->nullable();
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('equity_snapshots');
    }
};
