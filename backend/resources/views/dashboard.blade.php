<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Swing Trader - Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1419; color: #e0e0e0; line-height: 1.6; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        header { margin-bottom: 30px; }
        h1 { font-size: 28px; margin-bottom: 10px; }
        .header-meta { font-size: 13px; color: #888; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .card { background: #1a1f27; border: 1px solid #2a3039; border-radius: 8px; padding: 20px; }
        .card h2 { font-size: 14px; color: #999; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .card .value { font-size: 24px; font-weight: 600; }
        .card .sub { font-size: 12px; color: #666; margin-top: 5px; }
        .ticker-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .ticker-card { background: #1a1f27; border: 1px solid #2a3039; border-radius: 8px; padding: 20px; }
        .ticker-card .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 1px solid #2a3039; padding-bottom: 10px; }
        .ticker-card .symbol { font-size: 18px; font-weight: 700; }
        .metric { display: flex; justify-content: space-between; margin: 8px 0; font-size: 13px; }
        .metric .label { color: #888; }
        .metric .val { font-weight: 500; }
        .chart-container { background: #1a1f27; border: 1px solid #2a3039; border-radius: 8px; padding: 20px; margin-bottom: 30px; position: relative; height: 400px; }
        .error { color: #ff6b6b; }
        .success { color: #51cf66; }
        .loading { color: #888; font-style: italic; }
        button { background: #2563eb; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
        button:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Swing Trading Dashboard</h1>
            <div class="header-meta" id="status">Connecting to API...</div>
        </header>

        <div class="grid">
            <div class="card">
                <h2>Account Equity</h2>
                <div class="value" id="equity">—</div>
                <div class="sub" id="equity-sub"></div>
            </div>
            <div class="card">
                <h2>Buying Power</h2>
                <div class="value" id="buying-power">—</div>
            </div>
            <div class="card">
                <h2>Win Rate (Live)</h2>
                <div class="value" id="win-rate">—</div>
            </div>
            <div class="card">
                <h2>Total P&L</h2>
                <div class="value" id="total-pnl">—</div>
            </div>
        </div>

        <h2 style="margin-bottom: 20px; font-size: 18px;">Strategy Parameters</h2>
        <div class="ticker-cards" id="tickers"></div>

        <h2 style="margin-bottom: 20px; font-size: 18px;">Equity Curve - SPY</h2>
        <div class="chart-container">
            <canvas id="equityChart"></canvas>
        </div>

        <div style="text-align: center; margin-top: 40px;">
            <button onclick="triggerOptimizer()">Trigger Nightly Optimizer</button>
        </div>
    </div>

    <script>
        const API_BASE = 'http://localhost:8000/api/v1';

        async function fetchAPI(endpoint) {
            try {
                const res = await fetch(`${API_BASE}${endpoint}`);
                if (!res.ok) throw new Error(`${res.status}`);
                return await res.json();
            } catch (err) {
                console.error(`API Error: ${endpoint}`, err);
                return null;
            }
        }

        async function loadDashboard() {
            document.getElementById('status').textContent = 'Loading data...';

            // Load account data
            const account = await fetchAPI('/account');
            if (account) {
                document.getElementById('equity').textContent = `$${parseFloat(account.equity || 0).toFixed(2)}`;
                document.getElementById('buying-power').textContent = `$${parseFloat(account.buying_power || 0).toFixed(2)}`;
            }

            // Load P&L summary
            const pnl = await fetchAPI('/trades/pnl');
            if (pnl) {
                document.getElementById('total-pnl').textContent = `$${parseFloat(pnl.total_pnl || 0).toFixed(2)}`;
                document.getElementById('win-rate').textContent = `${parseFloat(pnl.win_rate || 0).toFixed(1)}%`;
            }

            // Load tickers & strategies
            const tickers = await fetchAPI('/tickers');
            if (tickers && Array.isArray(tickers)) {
                document.getElementById('tickers').innerHTML = tickers.map(t => `
                    <div class="ticker-card">
                        <div class="header">
                            <div class="symbol">${t.symbol}</div>
                        </div>
                        ${t.params ? `
                            <div class="metric">
                                <span class="label">Sharpe Ratio</span>
                                <span class="val">${parseFloat(t.params.sharpe_ratio || 0).toFixed(2)}</span>
                            </div>
                            <div class="metric">
                                <span class="label">Win Rate</span>
                                <span class="val">${(parseFloat(t.params.win_rate || 0) * 100).toFixed(1)}%</span>
                            </div>
                            <div class="metric">
                                <span class="label">Return</span>
                                <span class="val ${(parseFloat(t.params.total_return || 0) > 0 ? 'success' : 'error')}">${(parseFloat(t.params.total_return || 0) * 100).toFixed(2)}%</span>
                            </div>
                            <div class="metric">
                                <span class="label">MACD</span>
                                <span class="val">(${t.params.macd_fast},${t.params.macd_slow},${t.params.macd_signal})</span>
                            </div>
                            <div class="metric">
                                <span class="label">SMA</span>
                                <span class="val">(${t.params.sma_short},${t.params.sma_long})</span>
                            </div>
                        ` : '<div class="loading">No parameters optimized yet</div>'}
                    </div>
                `).join('');
            }

            // Load equity curve for SPY
            const equityCurve = await fetchAPI('/equity/SPY');
            if (equityCurve && (equityCurve.backtest || equityCurve.live)) {
                drawEquityChart(equityCurve);
            }

            document.getElementById('status').textContent = `Connected • ${new Date().toLocaleTimeString()}`;
        }

        function drawEquityChart(data) {
            const ctx = document.getElementById('equityChart').getContext('2d');
            const backtestDates = (data.backtest || []).map(d => d.date);
            const backtestValues = (data.backtest || []).map(d => d.value);
            const liveDates = (data.live || []).map(d => d.date);
            const liveValues = (data.live || []).map(d => d.value);

            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: backtestDates.length > 0 ? backtestDates : liveDates,
                    datasets: [
                        backtestValues.length > 0 && {
                            label: 'Backtest',
                            data: backtestValues,
                            borderColor: '#888',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            fill: false,
                            tension: 0.1,
                        },
                        liveValues.length > 0 && {
                            label: 'Live',
                            data: liveValues,
                            borderColor: '#51cf66',
                            borderWidth: 2,
                            fill: false,
                            tension: 0.1,
                        }
                    ].filter(Boolean)
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#e0e0e0' } },
                    },
                    scales: {
                        y: { ticks: { color: '#888' }, grid: { color: '#2a3039' } },
                        x: { ticks: { color: '#888' }, grid: { color: '#2a3039' } },
                    }
                }
            });
        }

        async function triggerOptimizer() {
            if (!confirm('Run nightly optimizer? This may take a few minutes.')) return;
            const res = await fetchAPI('/admin/optimize/trigger', { method: 'POST' });
            if (res) {
                alert('Optimizer triggered successfully');
                setTimeout(loadDashboard, 5000);
            }
        }

        // Load on startup
        loadDashboard();
        // Refresh every 60 seconds
        setInterval(loadDashboard, 60000);
    </script>
</body>
</html>
