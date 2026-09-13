<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;

class ExecuteEWETF extends Command
{
    protected $signature = 'trades:execute-EW-ETF {--force-test : Force a buy+sell round-trip per ticker (paper account test mode)} {--override : Manual override. force rebalance mid-week} {--dry-run : Preview the weekly EW rebalance without placing orders}';

    protected $description = 'Weekly equal-weight CoreEW trio rebalance (QQQ/VTI/VTV)';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);
        $forceTest = $this->option('force-test');
        $override = $this->option('override');
        $dryRun = $this->option('dry-run');

        // Get CoreEW Alpaca account number
        try {
            $chandAccount = $alpacaService->getAccount();
            $chandAcctNo = $chandAccount['account_number'] ?? '?';
        } catch (\Exception $e) {
            $chandAcctNo = '?';
        }

        // Record execution time
        $this->recordExecutionTime();

        // CoreEW is a weekly equal-weight trio book (QQQ/VTI/VTV @ equity/3).
        // Rebalance only on configured weekday(s) (ET) — COREEW_REBALANCE_DAYS
        // in .env, 1..7 (Mon..Sun), comma-separated; currently Monday, plan to
        // flip to Friday later. --override forces a manual run on any day.
        $ny = now()->setTimezone('America/New_York');
        $rebalanceDays = array_values(array_filter(array_map('intval', explode(',', (string) env('COREEW_REBALANCE_DAYS', '1')))));
        if (count($rebalanceDays) < 1) {
            $rebalanceDays = [1];
        }
        $isRebalanceDay = in_array($ny->dayOfWeek, $rebalanceDays, true);
        if (!$isRebalanceDay && !$override) {
            $this->info("Not a rebalance day ({$ny->format('D Y-m-d')}) — CoreEW rebalances on weekday(s) " . implode(',', $rebalanceDays) . " (Mon=1..Sun=7). No trades.");
            return 0;
        }

        // Rebalance at most once per calendar day (the 5-min scheduler fires
        // repeatedly; the marker keeps it to a single daily execution).
        $markerFile = storage_path('chand_last_rebalance.txt');
        if (!$override && !$dryRun && $isRebalanceDay && is_file($markerFile)) {
            $lastRebalance = trim((string) file_get_contents($markerFile));
            if ($lastRebalance === $ny->format('Y-m-d')) {
                $this->info("Already rebalanced today ({$lastRebalance}) — skipping weekly EW rebalance.");
                return 0;
            }
        }

        try {
            $clock = $alpacaService->getClock();
            // $clock['is_open'] = true;

            if (!$clock['is_open']) {
                $this->info('Market is closed. No trades executed.');
                return 0;
            }

            if ($forceTest) {
                $this->info('FORCE-TEST mode: placing buy+sell round-trip for each ticker...');
                $results = $tradeExecutor->forceTestAllTickers(1);
            } elseif ($dryRun) {
                $this->info('DRY-RUN: previewing EW rebalance (no orders placed)...');
                $results = $tradeExecutor->rebalanceEqualWeightWeekly(true);
            } else {
                $this->info('Market is open. Equal-weight weekly rebalance...');
                $results = $tradeExecutor->rebalanceEqualWeightWeekly();
                if ($isRebalanceDay && !$override) {
                    @file_put_contents($markerFile, $ny->format('Y-m-d'));
                }
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

    private function sendSlackReport($results, $equity, $success = true, $errorMsg = null, $acctNo = '?')
    {
        $webhookUrl = env('SLACK_WEBHOOK_URL');

        if (!$webhookUrl) {
            return;
        }

        if (!$success) {
            $payload = [
                'text' => '[CoreEW] :x: Trade Execution Failed  |  acct #' . $acctNo,
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

            $tradeLines = array_filter([$buyText, $sellText, $errorText]);
            $tradeContent = implode("\n", $tradeLines);

            $color = ($buyCounts > 0 || $sellCount > 0) ? 'good' : '#cccccc';

            $payload = [
                'text' => '[CoreEW] :chart_with_upwards_trend: Trade Execution Summary  |  acct #' . $acctNo,
                'attachments' => [
                    [
                        'color' => $color,
                        'title' => 'Trade Execution Report',
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
