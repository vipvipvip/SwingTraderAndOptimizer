# Testing Strategy

## Integration Tests (Hit Real APIs)

These tests connect to real external services and will fail if endpoints change or credentials are invalid. Run them before merging.

| Test | Service | Detects |
|------|---------|---------|
| `AlpacaServiceTest::test_getBars_connects_to_real_alpaca_api` | Alpaca Data API | Wrong URL, auth failure, endpoint deprecation |
| `AlpacaServiceTest::test_getAccount_connects_to_trading_api` | Alpaca Trading API | Paper trading API availability |

**Run integration tests:**
```bash
./vendor/bin/phpunit tests/Feature/AlpacaServiceTest.php
```

## Unit Tests (Mocked)

Placeholder tests that validate basic routing. These do NOT catch API changes.

| Test | Coverage |
|------|----------|
| `ExampleTest::test_the_application_returns_a_successful_response` | Basic 200 response on / |

## Key Lesson

**Mocked tests pass even when APIs fail.** The wrong Alpaca URL (`paper-api.alpaca.markets/v1/data` instead of `data.alpaca.markets/v1beta3`) was never caught because AlpacaService wasn't integration-tested. Only production caught it when trades failed.

**Solution:** Before modifying any external API call:
1. Run the integration test for that service
2. If it passes, your change is compatible
3. If it fails, the API may have changed upstream
