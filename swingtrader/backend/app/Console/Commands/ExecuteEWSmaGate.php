<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;

class ExecuteEWSmaGate extends Command
{
    protected $signature = 'trades:execute-EW-sma
        {--override : Force gate evaluation/action now (ignore the flip dedupe)}
        {--dry-run : Preview gate actions without placing orders}
        {--n= : SMA length in trading days (default: COREEW_SMA_N env, 200)}
        {--band= : SMA band in percent (default: COREEW_SMA_BAND env, 3)}
        {--state : Read-only gate state print, no orders, works when market closed}';

    protected $description = 'CoreEW index SMA gate (variant M, QQQ/VTI/VTV) - equal-weight index vs SMA(n) with +/-band hysteresis, all-in or all-cash';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);
        $override = $this->option('override');
        $dryRun = $this->option('dry-run');
        $stateOnly = $this->option('state');

        $n = (int) ($this->option('n') !== null ? $this->option('n') : env('COREEW_SMA_N', 200));
        $band = (float) ($this->option('band') !== null ? $this->option('band') : env('COREEW_SMA_BAND', 3));
        if ($n < 20 || $n > 400) {
            $this->error('--n must be between 20 and 400.');
            return 1;
        }
        if ($band < 0 || $band > 20) {
            $this->error('--band must be between 0 and 20 (percent).');
            return 1;
        }

        try {
            $acct = $alpacaService->getAccount();
            $acctNo = $acct['account_number'] ?? '?';
        } catch (\Exception $e) {
            $acctNo = '?';
        }

        // --- Read-only state print: no clock gate, no orders, no dedupe writes. ---
        if ($stateOnly) {
            $st = $tradeExecutor->indexSmaGateState($n, $band);
            $this->renderState($st, $n, $band);
            return (!empty($st['error'])) ? 1 : 0;
        }

        $this->recordExecutionTime();

        try {
            $clock = $alpacaService->getClock();

            if (!$clock['is_open']) {
                $this->info('Market is closed. No trades executed.');
                return 0;
            }

            // Same 30-min opening warm-up gate as the other CoreEW drivers: never
            // trade in the first 30 min of the session (09:30-10:00 ET).
            if (!$dryRun) {
                $secsSinceOpen = $this->secondsSinceSessionOpen($clock);
                if ($secsSinceOpen !== null && $secsSinceOpen < 1800) {
                    $this->info('Market open but within the 30-min opening warm-up ('
                        . max(0, 1800 - $secsSinceOpen) . 's remain) - no trades.');
                    return 0;
                }
            }

            if ($dryRun) {
                $this->info('DRY-RUN: previewing index SMA gate (no orders placed)...');
            } else {
                $this->info("Market is open. Index SMA gate (SMA$n +/- $band%)...");
            }

            $results = $tradeExecutor->runIndexSmaGate($dryRun, $n, $band, $override);

            $this->renderState($results['state'] ?? [], $n, $band);

            foreach (($results['buys'] ?? []) as $b) {
                $this->line("  BUY  $b");
            }
            foreach (($results['sells'] ?? []) as $s) {
                $this->line("  SELL $s");
            }
            foreach (($results['errors'] ?? []) as $e) {
                $this->error("  ERROR $e");
            }
            if (!empty($results['noop'])) {
                $this->info('  NO-OP: ' . $results['noop']);
            }

            if (count($results['errors'] ?? []) > 0) {
                return 1;
            }

            $equity = $equityService->snapshotAccountEquity($alpacaService);
            $this->info('Trade execution completed');
            if ($equity) {
                $this->info("Account equity: \$" . number_format($equity, 2));
            }

            $this->call('positions:sync');

            // Slack only when the gate actually traded (i.e. flipped state).
            $hasTrades = count($results['buys'] ?? []) > 0 || count($results['sells'] ?? []) > 0;
            if ($hasTrades && !$dryRun) {
                $this->sendSlackReport($results, $equity, $acctNo);
            } elseif ($dryRun) {
                $this->info('DRY-RUN: buys=' . count($results['buys'] ?? [])
                    . ' sells=' . count($results['sells'] ?? [])
                    . (isset($results['noop']) ? ' (' . $results['noop'] . ')' : ''));
            }

            return 0;
        } catch (\Exception $e) {
            $this->error('Trade execution failed: ' . $e->getMessage());
            $this->sendSlackReport(null, null, $acctNo, $e->getMessage());
            return 1;
        }
    }

    private function renderState(array $st, int $n, float $band)
    {
        if (empty($st)) {
            $this->warn('  (no gate state)');
            return;
        }
        if (!empty($st['error'])) {
            $this->error('  gate error: ' . $st['error']);
            return;
        }
        $pct = floatval($st['pct_vs_sma'] ?? 0);
        $this->line(sprintf(
            '  GATE: %s  |  index %.4f  SMA%d %.4f  (%s%.2f%% vs SMA)',
            !empty($st['long']) ? 'LONG (all 3)' : 'CASH',
            floatval($st['index'] ?? 0), $n, floatval($st['sma'] ?? 0),
            $pct >= 0 ? '+' : '', $pct
        ));
        $this->line(sprintf(
            '  last settled bar: %s   flips: %d',
            $st['last_date'] ?? '-', (int) ($st['signal_changes'] ?? 0)
        ));
        $recent = $st['flips_recent'] ?? array_slice($st['flips'] ?? [], -10);
        if (!empty($recent)) {
            $parts = [];
            foreach ($recent as $f) {
                $parts[] = ($f['to'] ? 'ON' : 'OFF') . ' ' . $f['date'];
            }
            $this->line('  recent flips: ' . implode('  <-  ', array_reverse($parts)));
        }
        if (empty($st['warm'])) {
            $this->warn('  SMA' . $n . ' NOT warm on the last settled bar.');
        }
    }

    private function recordExecutionTime()
    {
        try {
            file_put_contents(storage_path('trades_last_run.txt'), now()->format('Y-m-d H:i:s'));
        } catch (\Exception $e) {
            \Log::warning('Could not record execution time: ' . $e->getMessage());
        }
    }

    private function secondsSinceSessionOpen(array $clock): ?float
    {
        $clockTs = $clock['timestamp'] ?? null;
        if (!$clockTs) {
            return null;
        }
        try {
            $now = new \DateTime($clockTs);
            $now->setTimezone(new \DateTimeZone('America/New_York'));
            $open = new \DateTime($now->format('Y-m-d') . ' 09:30:00', new \DateTimeZone('America/New_York'));
            return $now->getTimestamp() - $open->getTimestamp();
        } catch (\Exception $e) {
            \Log::warning('Warm-up gate: could not parse clock timestamp: ' . $e->getMessage());
            return null;
        }
    }

    private function sendSlackReport($results, $equity, $acctNo, $errorMsg = null)
    {
        $webhookUrl = env('SLACK_WEBHOOK_URL');
        if (!$webhookUrl) {
            return;
        }

        if ($errorMsg !== null) {
            $payload = [
                'text' => '[CoreEW-SMA] :x: Index SMA gate FAILED  |  acct #' . $acctNo,
                'attachments' => [[
                    'color' => 'danger',
                    'title' => 'Index SMA Gate Error',
                    'text' => $errorMsg,
                    'footer' => 'Time: ' . now()->format('Y-m-d H:i:s'),
                ]],
            ];
        } else {
            $buys = $results['buys'] ?? [];
            $sells = $results['sells'] ?? [];
            $long = !empty($results['state']['long']);
            $lines = [];
            $lines[] = 'Gate state: ' . ($long ? 'LONG (all 3 ETFs)' : 'CASH (all out)');
            $lines[] = 'Buys: ' . (count($buys) ? implode(', ', $buys) : 'none');
            $lines[] = 'Sells: ' . (count($sells) ? implode(', ', $sells) : 'none');
            $lines[] = sprintf(
                'Index %.4f vs SMA (%s%.2f%%)',
                floatval($results['state']['index'] ?? 0),
                floatval($results['state']['pct_vs_sma'] ?? 0) >= 0 ? '+' : '',
                floatval($results['state']['pct_vs_sma'] ?? 0)
            );

            $payload = [
                'text' => '[CoreEW-SMA] :chart_with_upwards_trend: Index SMA gate '
                    . ($long ? 'ENTERED' : 'EXITED') . '  |  acct #' . $acctNo,
                'attachments' => [[
                    'color' => 'good',
                    'title' => 'Index SMA Gate — state change',
                    'fields' => [
                        ['title' => 'New state', 'value' => $long ? 'LONG (all 3)' : 'CASH', 'short' => true],
                        ['title' => 'Account equity', 'value' => '$' . number_format($equity ?? 0, 2), 'short' => true],
                    ],
                    'text' => implode("\n", $lines),
                    'footer' => 'Time: ' . now()->format('Y-m-d H:i:s'),
                ]],
            ];
        }

        try {
            (new Client())->post($webhookUrl, ['json' => $payload]);
        } catch (\Exception $e) {
            \Log::error('Failed to send Slack report: ' . $e->getMessage());
        }
    }
}
