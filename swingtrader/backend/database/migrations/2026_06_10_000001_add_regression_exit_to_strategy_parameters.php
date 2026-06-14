<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->integer('reg_slope_window')->nullable()->after('chandelier_entry_mult');
            $table->decimal('reg_slope_threshold', 12, 6)->nullable()->after('reg_slope_window');
            $table->string('reg_slope_type', 20)->nullable()->after('reg_slope_threshold');
        });
    }

    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->dropColumn(['reg_slope_window', 'reg_slope_threshold', 'reg_slope_type']);
        });
    }
};
