<!DOCTYPE html>
<html>
<head>
    <title>API Test</title>
    <style>
        body { font-family: Arial; padding: 20px; background: #f5f5f5; }
        .test { background: white; padding: 15px; margin: 10px 0; border-radius: 4px; }
        .loading { color: #666; }
        .success { color: #2e7d32; }
        .error { color: #d32f2f; }
        pre { background: #f9f9f9; padding: 10px; overflow-x: auto; }
    </style>
</head>
<body>
    <h1>Trading Dashboard - API Test</h1>

    <div class="test">
        <h2>Account Data</h2>
        <div id="account" class="loading">Loading...</div>
    </div>

    <div class="test">
        <h2>Strategies</h2>
        <div id="strategies" class="loading">Loading...</div>
    </div>

    <div class="test">
        <h2>Equity Curve (SPY)</h2>
        <div id="equity" class="loading">Loading...</div>
    </div>

    <div class="test">
        <h2>P&L Summary</h2>
        <div id="pnl" class="loading">Loading...</div>
    </div>

    <script>
        async function test(name, url, elementId) {
            try {
                const res = await fetch(url);
                const data = await res.json();
                document.getElementById(elementId).className = 'success';
                document.getElementById(elementId).innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            } catch (e) {
                document.getElementById(elementId).className = 'error';
                document.getElementById(elementId).innerHTML = 'Error: ' + e.message;
            }
        }

        test('Account', '/api/v1/account', 'account');
        test('Strategies', '/api/v1/strategies', 'strategies');
        test('Equity', '/api/v1/equity/SPY', 'equity');
        test('P&L', '/api/v1/trades/pnl', 'pnl');
    </script>
</body>
</html>
