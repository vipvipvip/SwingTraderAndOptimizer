<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->decimal('chandelier_entry_mult', 8, 4)->nullable()->after('chandelier_mult');
        });
    }

    public function down(): void
    {
        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->dropColumn('chandelier_entry_mult');
        });
    }
};
