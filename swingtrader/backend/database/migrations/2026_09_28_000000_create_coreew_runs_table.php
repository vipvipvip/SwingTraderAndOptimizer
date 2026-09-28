<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * Atomic multi-host dedupe for the CoreEW drivers that must act once per
 * settled week (or flip). A unique (strategy, span, week) index IS the lock:
 * `insertOrIgnore` (Postgres ON CONFLICT DO NOTHING) decides atomically whether
 * this process won the right to act — replace of local-filesystem marker files
 * (storage/coreew_*_last_week.txt), which do not survive a multi-instance
 * deployment. strategy='legema' is live today; 'eg100'/'gate' can migrate here
 * if they ever return to the cron.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('coreew_runs', function (Blueprint $table) {
            $table->id();
            $table->string('strategy', 32);
            $table->unsignedInteger('span');
            $table->date('week');
            $table->timestamp('acted_at')->useCurrent();
            $table->unique(['strategy', 'span', 'week']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('coreew_runs');
    }
};