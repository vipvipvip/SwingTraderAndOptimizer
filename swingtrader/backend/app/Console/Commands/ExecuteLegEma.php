<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;
use Symfony\Component\Process\Process;

/**
 * CoreEW variant P{span}w — per-leg weekly EMA crossover (QQQ/VTI/VTV): each ETF
 * is long while its OWN settled weekly close stays above its EMA(span); OFF legs
 * sit in cash; the ON legs are rebalanced to equal weight each new settled week
 * (variant A's weekly EW trim applied to the currently-long set). Decided on the
 * last settled Friday's weekly close, acted the following week.
 *
 * Backtested in backtest_trio_ew.py (--leg-ema 20, label P20w), and the signal
 * itself is produced by the SAME service method this command runs
 * (TradeExecutorService::legEmaTrail -> replayLegEmaSeries): the backtest shells
 * out to trades:coreew-leg-ema-series, so live == backtest by construction.
 *
 * Weekly dedupe (storage/coreew_leg_ema_last_week.txt): acts once per NEW settled
 * week, so a 5-min cron cadence costs nothing between Mondays. Same 30-min
 * opening warm-up gate and fill discipline as the other CoreEW drivers.
 *
 * A data-readiness gate (dataReadinessGate(), added 2026-10-20) runs after the
 * warm-up and before runLegEma: it refuses to act (no claim, no orders, red
 * Slack) when the weekly/daily scanner series are stale, using the SAME
 * canonical gate as MTF + DailySignal (scanner/services/scripts/data_readiness.py).
 */
class ExecuteLegEma extends Command
{
    protected $signature = 'trades:execute-leg-ema
        {--override : Force action now (ignore the weekly dedupe)}
        {--dry-run : Preview actions without placing orders}
        {--span= : EMA length in weeks (default: COREEW_LEG_EMA_SPAN env, 20)}
        {--state : Read-only state print, no orders, works when market closed}
        {--json : Machine-readable state for parity checks against the backtest}';

    protected $description = 'CoreEW per-leg weekly EMA crossover (variant P20w, QQQ/VTI/VTV) - long each ETF above its EMA, EW-rebalance the ON legs weekly';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);
        $override = $this->option('override');
        $dryRun = $this->option('dry-run');
        $stateOnly = $this->option('state');
        $json = $this->option('json');

        $span = (int) ($this->option('span') !== null ? $this->option('span') : env('COREEW_LEG_EMA_SPAN', 20));
        if ($span < 2 || $span > 200) {
            $this->error('--span must be between 2 and 200 weeks.');
            return 1;
        }

        // --- Read-only state print: no clock gate, no orders, no dedupe writes. ---
        if ($stateOnly || $json) {
            $st = $tradeExecutor->legEmaState($span);
            if ($json) {
                $this->line((string) json_encode([
                    'span' => $span,
                    'bars' => $st['bars'] ?? 0,
                    'last_week' => $st['last_week'] ?? null,
                    'state' => $st['state'] ?? [],
                    'symbols' => $st['symbols'] ?? [],
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

            // Same 30-min opening warm-up gate as the other CoreEW drivers.
            if (!$dryRun) {
                $secsSinceOpen = $this->secondsSinceSessionOpen($clock);
                if ($secsSinceOpen !== null && $secsSinceOpen < 1800) {
                    $this->info('Market open but within the 30-min opening warm-up ('
                        . max(0, 1800 - $secsSinceOpen) . 's remain) - no trades.');
                    return 0;
                }
            }

            // Data-readiness gate: never compute/act on a stale weekly series
            // (same canonical gate as MTF + DailySignal). Live uses --ensure
            // (verify -> repair -> re-verify); --dry-run checks only, no writes.
            // Fails closed: no claim, no orders; red Slack on the live path.
            $gateErr = $this->dataReadinessGate($dryRun);
            if ($gateErr !== null) {
                $this->error($gateErr);
                if (!$dryRun) {
                    $this->sendSlackReport(null, null, $acctNo, $span, $gateErr);
                }
                return 1;
            }

            if ($dryRun) {
                $this->info("DRY-RUN: previewing per-leg EMA$span gate (no orders placed)...");
            } else {
                $this->info("Market is open. LegEMA (per-leg EMA$span weekly)...");
            }

            $results = $tradeExecutor->runLegEma($dryRun, $span, $override);

            $this->renderState($results['state'] ?? [], $span, $results['last_week'] ?? null);

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

            // Slack only when the gate actually traded (a real weekly action).
            $hasTrades = count($results['buys'] ?? []) > 0 || count($results['sells'] ?? []) > 0;
            if ($hasTrades && !$dryRun) {
                $this->sendSlackReport($results, $equity, $acctNo, $span);
            } elseif ($dryRun) {
                $this->info('DRY-RUN: buys=' . count($results['buys'] ?? [])
                    . ' sells=' . count($results['sells'] ?? [])
                    . (isset($results['noop']) ? ' (' . $results['noop'] . ')' : ''));
            }

            return 0;
        } catch (\Exception $e) {
            $this->error('Trade execution failed: ' . $e->getMessage());
            $this->sendSlackReport(null, null, $acctNo, $span, $e->getMessage());
            return 1;
        }
    }

    private function renderState(array $st, int $span, ?string $lastWeek = null)
    {
        if (empty($st) && $lastWeek === null) {
            $this->warn('  (no gate state)');
            return;
        }
        if (!empty($st['error'])) {
            $this->error('  gate error: ' . $st['error']);
            return;
        }
        // Accept both the full legEmaTrail payload (state nested under 'state')
        // and the flat per-symbol long map (runLegEma pass-through).
        $map = isset($st['state']) && is_array($st['state']) ? $st['state'] : $st;
        if (is_array($map) && (array_key_exists('QQQ', $map) || array_key_exists('VTI', $map) || array_key_exists('VTV', $map))) {
            $parts = [];
            foreach (['QQQ', 'VTI', 'VTV'] as $sym) {
                if (array_key_exists($sym, $map)) {
                    $parts[] = $sym . ($map[$sym] ? '=LONG' : '=CASH');
                }
            }
            $this->line('  LegEMA' . $span . ': ' . implode('  ', $parts));
            $this->line('  last settled week: ' . ($lastWeek ?? ($st['last_week'] ?? '-')));
            return;
        }
        $this->warn('  (no parseable gate state)');
    }

    private function recordExecutionTime()
    {
        try {
            file_put_contents(storage_path('trades_last_run.txt'), now()->format('Y-m-d H:i:s'));
        } catch (\Exception $e) {
            \Log::warning('Could not record execution time: ' . $e->getMessage());
        }
    }

    /**
     * Data-readiness gate. Returns null when the weekly + daily series are safe to
     * act on, or a human-readable error string when they are not (fail closed).
     *
     * Two checks:
     *  1. Series freshness (cheap, in-process): the newest consumed settled weekly
     *     bar must not be older than last Monday. Mirrors the series SQL's
     *     `(d.date::date + 7) <= CURRENT_DATE` consumption rule, so a stale
     *     frontier is caught even if the Python gate is unavailable.
     *  2. Canonical gate (subprocess): scanner/services/scripts/data_readiness.py
     *     --tf week,day --mode etf, the SAME gate MTF (runner.py) and DailySignal
     *     use — verify -> repair -> re-verify. Its JSON `modes.*.*.problems`
     *     drives the pass/fail.
     *
     * `--dry-run` runs only the read-only `--check` variant so a preview never
     * mutates data; live uses `--ensure` (repair then re-verify).
     *
     * Env override DATA_GATE_SCRIPT points the subprocess at an alternate script
     * (used by tests); it can only tighten the gate, never bypass it.
     */
    private function dataReadinessGate(bool $dryRun): ?string
    {
        // --- 1. Series freshness (mirrors the series consumption SQL). ---
        try {
            $span = (int) ($this->option('span') !== null ? $this->option('span') : env('COREEW_LEG_EMA_SPAN', 20));
            $st = app(TradeExecutorService::class)->legEmaState($span);
            if (!empty($st['error'])) {
                return 'data gate: series state error: ' . $st['error'];
            }
            $lastWeek = $st['last_week'] ?? null;
            if ($lastWeek) {
                // Newest settled week must not be older than the previous Monday.
                $staleAfter = strtotime($lastWeek . ' +14 days');
                if ($staleAfter !== false && $staleAfter <= strtotime('today')) {
                    return 'data gate: weekly series stale (last settled week ' . $lastWeek
                        . '); scanner data did not catch up';
                }
            }
        } catch (\Exception $e) {
            return 'data gate: freshness check failed: ' . $e->getMessage();
        }

        // --- 2. Canonical readiness gate (subprocess). ---
        $root = dirname(base_path(), 2);
        $script = env('DATA_GATE_SCRIPT', $root . '/scanner/services/scripts/data_readiness.py');
        $python = $root . '/scanner/.venv/bin/python3';
        if (!is_file($python)) {
            return 'data gate: python venv not found at ' . $python;
        }
        if (!is_file($script)) {
            return 'data gate: readiness script not found at ' . $script;
        }

        $args = [$python, $script];
        $args[] = $dryRun ? '--check' : '--ensure';
        $args[] = '--tf';
        $args[] = 'week,day';
        $args[] = '--mode';
        $args[] = 'etf';
        $args[] = '--json';
        $args[] = '--workers';
        $args[] = '6';

        try {
            $proc = new Process($args);
            $proc->setTimeout(900);
            $proc->run();
        } catch (\Exception $e) {
            return 'data gate: could not run readiness script: ' . $e->getMessage();
        }

        $out = $proc->getOutput();
        $report = null;
        foreach (array_reverse(preg_split('/\r?\n/', (string) $out)) as $line) {
            $line = trim($line);
            if ($line !== '' && $line[0] === '{') {
                $decoded = json_decode($line, true);
                if (is_array($decoded)) {
                    $report = $decoded;
                    break;
                }
            }
        }

        if ($report === null) {
            $tail = trim((string) $proc->getErrorOutput());
            return 'data gate: no readiness report (exit ' . $proc->getExitCode() . ')'
                . ($tail !== '' ? ': ' . mb_substr($tail, -300) : '');
        }

        $problems = [];
        foreach (($report['modes'] ?? []) as $modeReports) {
            foreach ((array) $modeReports as $tfReport) {
                foreach (($tfReport['problems'] ?? []) as $p) {
                    $problems[] = $p;
                }
            }
        }

        if (!empty($report['ready']) && empty($problems)) {
            return null;
        }

        $detail = $problems ? implode('; ', array_slice($problems, 0, 4)) : 'readiness not met';
        return 'data gate: scanner data not ready - ' . $detail;
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

    private function sendSlackReport($results, $equity, $acctNo, $span, $errorMsg = null)
    {
        $webhookUrl = env('SLACK_WEBHOOK_URL');
        if (!$webhookUrl) {
            return;
        }

        if ($errorMsg !== null) {
            $payload = [
                'text' => '[CoreEW-LegEMA] :x: per-leg EMA gate FAILED  |  acct #' . $acctNo,
                'attachments' => [[
                    'color' => 'danger',
                    'title' => 'LegEMA Gate Error',
                    'text' => $errorMsg,
                    'footer' => 'Time: ' . now()->format('Y-m-d H:i:s'),
                ]],
            ];
        } else {
            $buys = $results['buys'] ?? [];
            $sells = $results['sells'] ?? [];
            $state = $results['state'] ?? [];
            $lines = [];
            $lines[] = 'Leg states (settled week ' . ($results['last_week'] ?? '-') . '):';
            foreach (['QQQ', 'VTI', 'VTV'] as $sym) {
                if (array_key_exists($sym, $state)) {
                    $lines[] = '  ' . $sym . ': ' . ($state[$sym] ? 'LONG' : 'CASH');
                }
            }
            $lines[] = 'Buys: ' . (count($buys) ? implode(', ', $buys) : 'none');
            $lines[] = 'Sells: ' . (count($sells) ? implode(', ', $sells) : 'none');

            $payload = [
                'text' => '[CoreEW-LegEMA] :chart_with_upwards_trend: weekly rebalance  |  acct #' . $acctNo,
                'attachments' => [[
                    'color' => 'good',
                    'title' => 'Per-leg EMA' . $span . ' — weekly action',
                    'fields' => [
                        ['title' => 'Book', 'value' => 'EW among ON legs, cash for OFF', 'short' => true],
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