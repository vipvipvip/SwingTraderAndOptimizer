<?php

namespace Tests\Feature;

use Tests\TestCase;
use App\Services\AlpacaService;

class AlpacaServiceTest extends TestCase
{
    private $alpacaService;

    protected function setUp(): void
    {
        parent::setUp();
        $this->alpacaService = new AlpacaService();
    }

    /**
     * Test that getBars() successfully connects to the real Alpaca data API.
     * This integration test catches endpoint changes, auth failures, and API version mismatches.
     *
     * If this test fails: check that ALPACA_API_KEY, ALPACA_SECRET_KEY are valid
     * and that Alpaca hasn't changed the /v1beta3/stocks/bars endpoint.
     */
    public function test_getBars_connects_to_real_alpaca_api(): void
    {
        // Use a short date range to minimize API cost
        $bars = $this->alpacaService->getBars(
            'SPY',
            '1Hour',
            '2026-04-20',
            '2026-04-21'
        );

        // Should return an array (even if empty, it means the API endpoint is valid)
        $this->assertIsArray($bars);
    }

    /**
     * Test that account endpoint is reachable.
     * Confirms trading API (paper-api.alpaca.markets) is working.
     */
    public function test_getAccount_connects_to_trading_api(): void
    {
        $account = $this->alpacaService->getAccount();
        $this->assertIsArray($account);
        $this->assertArrayHasKey('account_number', $account);
    }
}
