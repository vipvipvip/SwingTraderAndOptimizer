<?php

namespace App\Console\Commands;

use App\Services\TradeExecutorService;
use Illuminate\Console\Command;

class ShowEWGateState extends Command
{
    protected $signature = 'trades:EW-gate-state {--mult= : Weekly ratchet ATR multiplier (default: COREEW_GATE_MULT env, 2.0)}';

    protected $description = 'Show current monotone weekly-ratchet gate state (LONG/FLAT, peak, stop) for QQQ/VTI/VTV — read-only, no orders';

    public function handle()
    {
        $mult = (float) ($this->option('mult') !== null
            ? $this->option('mult')
            : env('COREEW_GATE_MULT', 2.0));
        if ($mult <= 0 || $mult > 10) {
            $this->error('--mult must be > 0 (and reasonably <= 10).');
            return 1;
        }

        $executor = app(TradeExecutorService::class);
        $gate = $executor->monotoneGateState($mult);

        $rows = [];
        foreach (($gate['state'] ?? []) as $sym => $st) {
            $rows[] = [
                $sym,
                !empty($st['long']) ? 'LONG' : 'FLAT',
                $st['entries'] ?? 0,
                isset($st['peak']) && $st['peak'] > 0 ? '$' . number_format($st['peak'], 2) : '-',
                isset($st['stop']) && $st['stop'] > 0 ? '$' . number_format($st['stop'], 2) : '-',
                $st['last_week'] ?? '-',
            ];
        }

        if (!$rows) {
            $this->info('No gate state available.');
            return 0;
        }

        $this->table(
            ['Symbol', 'State', 'Entries', 'Peak', 'Ratchet Stop', 'Settled Week'],
            $rows
        );

        $this->info('Stop semantics: exits when a settled weekly close <= stop; re-enters only on a close > old stop (monotone). Stop holds until the next settled week.');

        return 0;
    }
}