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
        Schema::table('strategy_parameters', function (Blueprint $table) {
            if (!Schema::hasColumn('strategy_parameters', 'base_case')) {
                $table->boolean('base_case')->default(false)->index();
            }
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            if (Schema::hasColumn('strategy_parameters', 'base_case')) {
                $table->dropColumn('base_case');
            }
        });
    }
};
