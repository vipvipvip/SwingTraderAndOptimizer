<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('tickers', function (Blueprint $table) {
            $table->id();
            $table->string('symbol')->unique();
            $table->boolean('enabled')->default(true);
            $table->decimal('allocation_weight', 8, 4)->default(10.0000);
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('tickers');
    }
};
