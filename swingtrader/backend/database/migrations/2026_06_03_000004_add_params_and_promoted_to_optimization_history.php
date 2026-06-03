<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('optimization_history', function (Blueprint $table) {
            $table->jsonb('params')->nullable()->after('runtime_seconds');
            $table->boolean('promoted')->default(false)->after('params');
        });
    }

    public function down(): void
    {
        Schema::table('optimization_history', function (Blueprint $table) {
            $table->dropColumn(['params', 'promoted']);
        });
    }
};
