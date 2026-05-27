<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->dropColumn('take_profit_mult');
        });
    }

    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->decimal('take_profit_mult', 8, 2)->nullable()->after('bb_std');
        });
    }
};
