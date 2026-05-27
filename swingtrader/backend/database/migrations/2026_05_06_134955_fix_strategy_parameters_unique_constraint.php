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
            $table->dropUnique('strategy_parameters_ticker_id_base_case_unique');
        });

        // Create partial unique index: only one base_case=true per ticker
        DB::statement('CREATE UNIQUE INDEX strategy_parameters_ticker_id_base_case_true
                       ON strategy_parameters(ticker_id) WHERE base_case = true');
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        DB::statement('DROP INDEX IF EXISTS strategy_parameters_ticker_id_base_case_true');

        Schema::table('strategy_parameters', function (Blueprint $table) {
            $table->unique(['ticker_id', 'base_case']);
        });
    }
};
