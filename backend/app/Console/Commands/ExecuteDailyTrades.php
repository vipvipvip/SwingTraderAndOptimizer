<?php

namespace App\Console\Commands;

use App\Services\AlpacaService;
use App\Services\TradeExecutorService;
use App\Services\EquityService;
use Illuminate\Console\Command;
use GuzzleHttp\Client;

class ExecuteDailyTrades extends Command
{
    protected $signature = 'trades:execute-daily {--force-test : Force a buy+sell round-trip per ticker (paper account test mode)}';

    protected $description = 'Execute daily trades for all enabled tickers';

    public function handle()
    {
        $alpacaService = app(AlpacaService::class);
        $tradeExecutor = app(TradeExecutorService::class);
        $equityService = app(EquityService::class);
        $forceTest = $this->option('force-test');

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
            } else {
                $this->info('Market is open. Executing trades...');
                $results = $tradeExecutor->executeForAllTickers();
            }
            $equity = $equityService->snapshotAccountEquity($alpacaService);

            $this->info('Trade execution completed');
            if ($equity) {
                $this->info("Account equity: \$" . number_format($equity, 2));
            }

            $this->sendSlackReport($results, $equity, true);

            return 0;
        } catch (\Exception $e) {
            $this->error('Trade execution failed: ' . $e->getMessage());
            $this->sendSlackReport(null, null, false, $e->getMessage());
            return 1;
        }
    }

    private function sendSlackReport($results, $equity, $success = true, $errorMsg = null)
    {
        $webhookUrl = env('SLACK_WEBHOOK_URL');

        if (!$webhookUrl) {
            return;
        }

        if (!$success) {
            $payload = [
                'text' => ':x: Trade Execution Failed',
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
                'text' => ':chart_with_upwards_trend: Trade Execution Summary',
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
