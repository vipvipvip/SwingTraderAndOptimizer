<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;

/**
 * CoreEW variant EG100 — portfolio-level all-in / all-out on the EMA(100)
 * crossover of an equal-weight QQQ/VTI/VTV index.
 *
 * This REPLACES the per-leg monotone weekly-ratchet gate (trades:execute-EW-gate,
 * variant S). It is a different algorithm, not a re-tune: the old gate decides
 * weekly, per leg, from a peak-anchored ATR ratchet; this decides daily, for the
 * whole book at once, from the index vs its own EMA.
 *
 * Backtested in backtest_trio_ew.py (--ema-gate 100). Result vs weekly EW
 * rebalance: +73.5%/-8.4% DD (3y) and +96.6%/-16.1% (5.5y); out-of-sample
 * holdout 2016-11->2021-04 +85.6%/-12.1% (64% of the drawdown removed, 70% of
 * the return kept). Selected on the later windows, so treat the return capture
 * as the optimistic end of the range.
 */
class ExecuteEWGate100 extends Command
{
    protected $signature = 'trades:execute-EW-gate100
        {--override : Force gate evaluation/action now (ignore the flip dedupe)}
        {--dry-run : Preview gate actions without placing orders}
        {--span= : EMA length in trading days (default: COREEW_EG_SPAN env, 100)}
        {--state : Read-only gate state print, no orders, works when market closed}
        {--json : Machine-readable state for parity checks against the backtest}';

    protected $description = 'CoreEW index EMA(100) crossover gate (variant EG100, QQQ/VTI/VTV) - all-in or all-cash, daily decision on settled closes';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);
        $override = $this->option('override');
        $dryRun = $this->option('dry-run');
        $stateOnly = $this->option('state');
        $json = $this->option('json');

        $span = (int) ($this->option('span') !== null ? $this->option('span') : env('COREEW_EG_SPAN', 100));
        if ($span < 20 || $span > 400) {
            $this->error('--span must be between 20 and 400.');
            return 1;
        }

        // --- Read-only state print: no clock gate, no orders, no dedupe writes. ---
        if ($stateOnly || $json) {
            $st = $tradeExecutor->indexEgGateState($span, 0.0);
            if ($json) {
                $this->line((string) json_encode([
                    'long' => !empty($st['long']),
                    'last_date' => $st['last_date'] ?? null,
                    'index' => $st['index'] ?? 0,
                    'ema' => $st['ema'] ?? 0,
                    'span' => $span,
                    'bars' => $st['bars'] ?? 0,
                    'pct_vs_ema' => $st['pct_vs_ema'] ?? 0,
                    'signal_changes' => $st['signal_changes'] ?? 0,
                    'last_flip' => $st['last_flip'] ?? null,
                    'flips' => $st['flips'] ?? [],
                    'error' => $st['error'] ?? null,
                ]));
                return (!empty($st['error'])) ? 1 : 0;
            }
            $this->renderState($st, $span);
            return (!empty($st['error'])) ? 1 : 0;
        }

        $this->recordExecutionTime();

        try {
            $acct = $alpacaService->getAccount();
            $acctNo = $acct['account_number'] ?? '?';
        } catch (\Exception $e) {
            $acctNo = '?';
        }

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
                $this->info('DRY-RUN: previewing index EMA gate (no orders placed)...');
            } else {
                $this->info("Market is open. EG100 gate (EMA$span crossover)...");
            }

            $results = $tradeExecutor->runEg100Gate($dryRun, $span, $override);

            $this->renderState($results['state'] ?? [], $span);

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

    private function renderState(array $st, int $span)
    {
        if (empty($st)) {
            $this->warn('  (no gate state)');
            return;
        }
        if (!empty($st['error'])) {
            $this->error('  gate error: ' . $st['error']);
            return;
        }
        $pct = floatval($st['pct_vs_ema'] ?? 0);
        $this->line(sprintf(
            '  GATE: %s  |  index %.4f  EMA%d %.4f  (%s%.2f%% vs EMA)',
            !empty($st['long']) ? 'LONG (all 3)' : 'CASH',
            floatval($st['index'] ?? 0), $span, floatval($st['ema'] ?? 0),
            $pct >= 0 ? '+' : '', $pct
        ));
        $this->line(sprintf(
            '  last settled bar: %s   bars: %d   flips: %d',
            $st['last_date'] ?? '-', (int) ($st['bars'] ?? 0), (int) ($st['signal_changes'] ?? 0)
        ));
        $recent = array_slice($st['flips'] ?? [], -10);
        if (!empty($recent)) {
            $parts = [];
            foreach ($recent as $f) {
                $parts[] = ($f['to'] ? 'ON' : 'OFF') . ' ' . $f['date'];
            }
            $this->line('  recent flips: ' . implode('  <-  ', array_reverse($parts)));
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
                'text' => '[CoreEW-EG100] :x: Index EMA gate FAILED  |  acct #' . $acctNo,
                'attachments' => [[
                    'color' => 'danger',
                    'title' => 'EG100 Gate Error',
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
                'Index %.4f vs EMA%s (%s%.2f%%)',
                floatval($results['state']['index'] ?? 0),
                (int) ($results['state']['span'] ?? 100),
                floatval($results['state']['pct_vs_ema'] ?? 0) >= 0 ? '+' : '',
                floatval($results['state']['pct_vs_ema'] ?? 0)
            );

            $payload = [
                'text' => '[CoreEW-EG100] :chart_with_upwards_trend: Index EMA gate '
                    . ($long ? 'ENTERED' : 'EXITED') . '  |  acct #' . $acctNo,
                'attachments' => [[
                    'color' => 'good',
                    'title' => 'Index EMA Gate — state change',
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
