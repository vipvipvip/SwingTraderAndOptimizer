<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;

class ExecuteEWETF extends Command
{
    protected $signature = 'trades:execute-EW-ETF {--force-test : Force a buy+sell round-trip per ticker (paper account test mode)} {--override : Manual override. Force an exact rebalance now (drift threshold 0)} {--dry-run : Preview the EW rebalance without placing orders} {--drift= : Drift threshold %% of equity before a leg is rebalanced (default: COREEW_DRIFT_PCT env, 0 = exact)} {--profit= : Rebalance to exact equal weight whenever ANY held ETF leg has unrealized profit >= this $ amount (default: COREEW_PROFIT_TRIGGER env, 0 = disabled)} {--gain-cap= : Gain rake - when ANY held leg has unrealized profit > this cap, bank the excess above buffer to CASH (default: COREEW_GAIN_CAP env, 0 = rake disabled and the equalize path runs instead)} {--gain-buffer= : $ of unrealized profit left on a leg after a rake (default: COREEW_GAIN_BUFFER env)}';

    protected $description = 'Intraday CoreEW trio driver (QQQ/VTI/VTV) - equal-weight rebalance OR gain-cap profit rake (rake banks profit and stops; rebalance runs on a cycle where no rake fires)';

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

        // CoreEW is an equal-weight trio book (QQQ/VTI/VTV @ equity/3).
        // This command is the live intraday driver: cron fires it every 5 min
        // during market hours and the drift threshold decides whether any leg
        // needs a trim/top-up. Default threshold from COREEW_DRIFT_PCT (0.5%),
        // --override forces an exact rebalance (threshold 0) at any time, and
        // --drift= overrides the threshold for one-off runs. A leg whose
        // unrealized profit reaches COREEW_PROFIT_TRIGGER ($100 default) also
        // forces an exact rebalance that cycle (harvest the gain).
        $driftPct = (float) ($this->option('drift') !== null
            ? $this->option('drift')
            : env('COREEW_DRIFT_PCT', 0.5));
        if ($override) {
            $driftPct = 0.0;
        }
        if ($driftPct < 0 || $driftPct > 100) {
            $this->error('--drift must be between 0 and 100 (% of equity).');
            return 1;
        }

        // Profit trigger: when ANY single held ETF leg reaches this much
        // unrealized profit, the drift gate is overridden and the book
        // rebalances to exact equal weight (harvest the gain). 0 = disabled.
        // Default from COREEW_PROFIT_TRIGGER env; --profit= overrides per run.
        $profitTrigger = (float) ($this->option('profit') !== null
            ? $this->option('profit')
            : env('COREEW_PROFIT_TRIGGER', 100));
        if ($profitTrigger < 0) {
            $this->error('--profit must be >= 0 (0 = disabled).');
            return 1;
        }

        // Gain-cap profit rake: when gainCap > 0 this driver runs the RAKER in
        // place of the equalize path (drift + profit trigger are bypassed while
        // a rake can fire). A leg with unbanked unrealized profit above the cap
        // sells the excess above the buffer to CASH and STOPS — the rake and the
        // equal-weight rebalance are strictly separate paths: no redeploy and no
        // rebalance in the same run. On any cycle where no rake fires, the
        // rebalance runs and is the mechanism that redeploys the banked cash
        // back into underweight legs (handled per cycle, no persisted gate).
        // 0 = rake off.
        $gainCap = (float) ($this->option('gain-cap') !== null
            ? $this->option('gain-cap')
            : env('COREEW_GAIN_CAP', 0));
        $gainBuffer = (float) ($this->option('gain-buffer') !== null
            ? $this->option('gain-buffer')
            : env('COREEW_GAIN_BUFFER', 25));
        if ($gainCap < 0) {
            $this->error('--gain-cap must be >= 0 (0 = rake disabled).');
            return 1;
        }
        if ($gainCap > 0 && $gainBuffer >= $gainCap) {
            $this->error('--gain-buffer must be < --gain-cap (buffer keeps a little profit on the leg).');
            return 1;
        }

        try {
            $clock = $alpacaService->getClock();

            if (!$clock['is_open']) {
                $this->info('Market is closed. No trades executed.');
                return 0;
            }

            $rakeMode = $gainCap > 0;

            if ($forceTest) {
                $this->info('FORCE-TEST mode: placing buy+sell round-trip for each ticker...');
                $results = $tradeExecutor->forceTestAllTickers(1);
            } elseif ($rakeMode) {
                // Strictly separate paths, evaluated per cycle (no persisted
                // day-gate): a rake cycle banks profit to CASH and STOPS — no
                // redeploy/rebalance in the same run. The next cycle the rake
                // recomputes from scratch; on any cycle where no rake fires the
                // equal-weight rebalance runs, and that rebalance is what
                // redeploys the banked cash back into underweight legs.
                $this->info(($dryRun ? 'DRY-RUN: previewing gain rake' : 'Market is open. Gain rake (cap $' . $gainCap . ', buffer $' . $gainBuffer . ')...'));
                $results = $tradeExecutor->rakeEqualWeight($dryRun, $gainCap, $gainBuffer);
                $rakeBanked = floatval($results['rake_banked'] ?? 0);
                if ($rakeBanked > 0) {
                    $this->info('Gain rake traded this cycle — banks the profit and STOPS; no rebalance this run.');
                } else {
                    $this->info(($dryRun ? 'DRY-RUN: no rake, previewing EW rebalance' : 'No rake this cycle. Running equal-weight rebalance (redeploys banked cash into underweight legs)...'));
                    $results = $tradeExecutor->rebalanceEqualWeightWeekly($dryRun, $driftPct, $profitTrigger);
                }
            } elseif ($dryRun) {
                $this->info('DRY-RUN: previewing EW rebalance (no orders placed)...');
                $results = $tradeExecutor->rebalanceEqualWeightWeekly(true, $driftPct, $profitTrigger);
            } else {
                $this->info('Market is open. Equal-weight rebalance (drift threshold ' . $driftPct . '%, profit trigger $' . $profitTrigger . ')...');
                $results = $tradeExecutor->rebalanceEqualWeightWeekly(false, $driftPct, $profitTrigger);
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
            $rakeBanked = floatval($results['rake_banked'] ?? 0);
            $rakeText = $rakeBanked > 0
                ? "🌾 gain rake banked \$" . number_format($rakeBanked, 2) . " to cash" . (!empty($results['rake_legs']) ? " (" . implode(', ', $results['rake_legs']) . ")" : "")
                : "";
            $triggerText = !empty($results['profit_triggered'])
                ? "💰 profit-triggered rebalance (a leg hit the profit threshold)"
                : "";

            $tradeLines = array_filter([$triggerText, $rakeText, $buyText, $sellText, $errorText]);
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
