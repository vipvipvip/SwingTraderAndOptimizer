<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('tbl_sec_research_analysis', function (Blueprint $table) {
            $table->id();
            $table->uuid('run_id')->index();
            $table->string('ticker', 10)->index();
            $table->date('earnings_date')->nullable()->index();
            $table->date('filing_date')->nullable();
            $table->string('filing_type', 10)->nullable();
            $table->integer('score')->nullable();
            $table->integer('rank_in_run')->nullable();
            $table->jsonb('analysis_data')->nullable();
            $table->text('board_comments')->nullable();
            $table->jsonb('sources')->nullable();
            $table->timestamps();

            $table->unique(['run_id', 'ticker']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('tbl_sec_research_analysis');
    }
};
