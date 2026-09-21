<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;

class ExecuteEWGate extends Command
{
    protected $signature = 'trades:execute-EW-gate {--override : Force gate evaluation/action now (ignore the settled-week dedupe)} {--dry-run : Preview gate actions without placing orders} {--mult= : Weekly ratchet ATR multiplier (default: COREEW_GATE_MULT env, 2.0)}';

    protected $description = 'CoreEW monotone weekly-ratchet gate (QQQ/VTI/VTV) - replay settled weekly bars, exit FLAT legs, rebalance gate-LONG passers to equal weight';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);
        $override = $this->option('override');
        $dryRun = $this->option('dry-run');

        try {
            $chandAccount = $alpacaService->getAccount();
            $chandAcctNo = $chandAccount['account_number'] ?? '?';
        } catch (\Exception $e) {
            $chandAcctNo = '?';
        }

        $this->recordExecutionTime();

        $mult = (float) ($this->option('mult') !== null
            ? $this->option('mult')
            : env('COREEW_GATE_MULT', 2.0));
        if ($mult <= 0 || $mult > 10) {
            $this->error('--mult must be > 0 (and reasonably <= 10).');
            return 1;
        }

        try {
            $clock = $alpacaService->getClock();

            if (!$clock['is_open']) {
                $this->info('Market is closed. No trades executed.');
                return 0;
            }

            // Same 30-min opening warm-up gate as the EW driver: never trade
            // during 09:30-10:00 ET (volatile opens). The settled-week dedupe
            // already makes the gate act only when a NEW settled weekly bar
            // appears; this blocks reacting right at the open auction.
            if (!$dryRun) {
                $secsSinceOpen = $this->secondsSinceSessionOpen($clock);
                if ($secsSinceOpen !== null && $secsSinceOpen < 1800) {
                    $this->info('Market open but within the 30-min opening warm-up ('
                        . max(0, 1800 - $secsSinceOpen) . 's remain) — no trades.');
                    return 0;
                }
            }

            if ($dryRun) {
                $this->info('DRY-RUN: previewing monotone weekly gate (no orders placed)...');
            } else {
                $this->info('Market is open. Monotone weekly gate (mult ' . $mult . 'x)...');
            }
            $results = $tradeExecutor->runMonotoneGate($dryRun, $mult, $override);

            foreach (($results['state'] ?? []) as $sym => $st) {
                $this->line(sprintf(
                    '  %s: %s entries=%d peak=%s stop=%s settled=%s',
                    $sym,
                    !empty($st['long']) ? 'LONG' : 'FLAT',
                    $st['entries'] ?? 0,
                    isset($st['peak']) ? '$' . number_format($st['peak'], 2) : '-',
                    isset($st['stop']) ? '$' . number_format($st['stop'], 2) : '-',
                    $st['last_week'] ?? '-'
                ));
            }

            $equity = $equityService->snapshotAccountEquity($alpacaService);

            $this->info('Trade execution completed');
            if ($equity) {
                $this->info("Account equity: \$" . number_format($equity, 2));
            }

            // Sync positions cache after trades
            $this->call('positions:sync');

            // Only send Slack report if trades occurred (and not a dry-run)
            $hasTrades = count($results['buys'] ?? []) > 0 || count($results['sells'] ?? []) > 0;
            if ($hasTrades && !$dryRun) {
                $this->sendSlackReport($results, $equity, true, null, $chandAcctNo);
            } elseif ($dryRun) {
                $this->info('DRY-RUN: buys=' . count($results['buys'] ?? [])
                    . ' sells=' . count($results['sells'] ?? [])
                    . (isset($results['noop']) ? ' (' . $results['noop'] . ')' : ''));
            }

            return 0;
        } catch (\Exception $e) {
            $this->error('Trade execution failed: ' . $e->getMessage());
            $this->sendSlackReport(null, null, false, $e->getMessage(), $chandAcctNo);
            return 1;
        }
    }

    private function recordExecutionTime()
    {
        try {
            $timestamp = now()->format('Y-m-d H:i:s');
            $statusFile = storage_path('trades_last_run.txt');
            file_put_contents($statusFile, $timestamp);
        } catch (\Exception $e) {
            \Log::warning('Could not record execution time: ' . $e->getMessage());
        }
    }

    /**
     * Seconds elapsed since the current session opened (09:30 ET today), using
     * the Alpaca clock timestamp as the source of truth. Returns null when the
     * clock timestamp is missing/unparseable (gate then simply doesn't apply).
     */
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

    private function sendSlackReport($results, $equity, $success = true, $errorMsg = null, $acctNo = '?')
    {
        $webhookUrl = env('SLACK_WEBHOOK_URL');

        if (!$webhookUrl) {
            return;
        }

        if (!$success) {
            $payload = [
                'text' => '[CoreEW-Gate] :x: Trade Execution Failed  |  acct #' . $acctNo,
                'attachments' => [
                    [
                        'color' => 'danger',
                        'title' => 'Trade Execution Error',
                        'text' => $errorMsg,
                        'footer' => 'Time: ' . now()->format('Y-m-d H:i:s')
                    ]
                ]
            ];
        } else {
            $buyCounts = count($results['buys'] ?? []);
            $sellCount = count($results['sells'] ?? []);
            $errorCount = count($results['errors'] ?? []);

            $buyText = $buyCounts > 0 ? "📈 BUYS: " . implode(', ', $results['buys']) : "No buys";
            $sellText = $sellCount > 0 ? "📉 SELLS: " . implode(', ', $results['sells']) : "No sells";
            $errorText = $errorCount > 0 ? "⚠️ ERRORS: " . $errorCount : "";

            $stateText = [];
            foreach (($results['state'] ?? []) as $sym => $st) {
                $stateText[] = $sym . '=' . (!empty($st['long']) ? 'LONG' : 'FLAT');
            }
            $stateLine = count($stateText) > 0 ? "Gate state: " . implode(' ', $stateText) : "";

            $tradeLines = array_filter([$stateLine, $buyText, $sellText, $errorText]);
            $tradeContent = implode("\n", $tradeLines);

            $color = ($buyCounts > 0 || $sellCount > 0) ? 'good' : '#cccccc';

            $payload = [
                'text' => '[CoreEW-Gate] :chart_with_upwards_trend: Gate Summary  |  acct #' . $acctNo,
                'attachments' => [
                    [
                        'color' => $color,
                        'title' => 'Monotone Weekly Gate Report',
                        'fields' => [
                            [
                                'title' => 'Tickers Processed',
                                'value' => $results['total'],
                                'short' => true
                            ],
                            [
                                'title' => 'Trades Executed',
                                'value' => ($buyCounts + $sellCount),
                                'short' => true
                            ],
                            [
                                'title' => 'Account Equity',
                                'value' => '$' . number_format($equity ?? 0, 2),
                                'short' => true
                            ],
                            [
                                'title' => 'Account #',
                                'value' => $acctNo,
                                'short' => true
                            ],
                            [
                                'title' => 'Execution Status',
                                'value' => 'Success',
                                'short' => true
                            ]
                        ],
                        'text' => $tradeContent,
                        'footer' => 'Time: ' . now()->format('Y-m-d H:i:s')
                    ]
                ]
            ];
        }

        try {
            $client = new Client();
            $client->post($webhookUrl, [
                'json' => $payload
            ]);
        } catch (\Exception $e) {
            \Log::error('Failed to send Slack report: ' . $e->getMessage());
        }
    }
}