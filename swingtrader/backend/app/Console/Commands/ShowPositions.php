<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

class ShowPositions extends Command
{
    protected $signature = 'positions:show {--all : Show all trades including closed}';

    protected $description = 'Show current open positions';

    public function handle()
    {
        $query = DB::table('live_trades');

        if (!$this->option('all')) {
            $query = $query->where('status', 'open');
        }

        $trades = $query->orderBy('created_at', 'desc')->get();

        if ($trades->isEmpty()) {
            $this->info('No ' . ($this->option('all') ? '' : 'open ') . 'trades found');
            return 0;
        }

        $this->table(
            ['Symbol', 'Side', 'Qty', 'Entry Price', 'Status', 'Created At'],
            $trades->map(function ($t) {
                return [
                    $t->symbol,
                    $t->side,
                    $t->quantity,
                    $t->entry_price ? '$' . number_format($t->entry_price, 2) : 'N/A',
                    $t->status,
                    $t->created_at,
                ];
            })->toArray()
        );

        $openCount = DB::table('live_trades')->where('status', 'open')->count();
        $this->info("\nOpen positions: {$openCount}");

        return 0;
    }
}
