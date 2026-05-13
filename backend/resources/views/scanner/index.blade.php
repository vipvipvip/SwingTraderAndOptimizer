<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4e8; height: 100vh; display: flex; flex-direction: column; }
        .top-bar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #1c1e26; border-bottom: 1px solid #2d2f3a; flex-shrink: 0; }
        .top-bar select { background: #0f1117; border: 1px solid #2d2f3a; color: #e1e4e8; padding: 4px 8px; border-radius: 4px; font-size: 13px; }
        .top-bar .signals { font-size: 13px; color: #3fb950; margin-left: auto; }
        .top-bar .scanned { font-size: 13px; color: #8b949e; }
        .table-wrap { flex-shrink: 0; overflow-y: auto; max-height: 210px; border-bottom: 1px solid #2d2f3a; }
        .table-wrap table { width: 100%; border-collapse: collapse; }
        .table-wrap thead { position: sticky; top: 0; z-index: 1; }
        .table-wrap th { background: #23252f; padding: 6px 12px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #8b949e; }
        .table-wrap td { padding: 5px 12px; font-size: 12px; border-bottom: 1px solid #1c1e26; }
        .table-wrap tr:last-child td { border-bottom: none; }
        .table-wrap tr:hover td { background: #23252f; }
        .table-wrap tr { cursor: pointer; }
        .table-wrap tr.active td { background: #1a2a3a; }
        .table-wrap .ticker { font-weight: 600; color: #58a6ff; }
        .table-wrap .num { font-family: 'JetBrains Mono', 'Fira Code', monospace; text-align: right; }
        .table-wrap .pos { color: #3fb950; }
        .table-wrap .neg { color: #f85149; }
        .chart-wrap { flex: 1; min-height: 0; padding: 4px; display: flex; flex-direction: column; }
        .chart-wrap .chart-inner { flex: 1; display: flex; flex-direction: column; gap: 2px; min-height: 0; }
        .chart-wrap .chart-panel { min-height: 0; }
        .empty-chart { display: flex; align-items: center; justify-content: center; height: 100%; color: #4a4d59; font-size: 15px; }
    </style>
</head>
<body>
    <div class="top-bar">
        <label style="color:#8b949e;font-size:13px;">Lookback:</label>
        <select onchange="window.location='/scanner?weeks='+this.value">
            <option value="1" {{ $weeks == 1 ? 'selected' : '' }}>1w</option>
            <option value="2" {{ $weeks == 2 ? 'selected' : '' }}>2w</option>
            <option value="3" {{ $weeks == 3 ? 'selected' : '' }} selected>3w</option>
            <option value="4" {{ $weeks == 4 ? 'selected' : '' }}>4w</option>
            <option value="8" {{ $weeks == 8 ? 'selected' : '' }}>8w</option>
        </select>
        <span class="scanned">{{ number_format($total_scanned) }} tickers</span>
        <span class="signals">{{ $total_signals }} signals</span>
    </div>

    @if (count($results) > 0)
        <div class="table-wrap" id="tableWrap">
            <table id="scannerTable">
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Date</th>
                        <th>Close</th>
                    </tr>
                </thead>
                <tbody>
                    @foreach ($results as $row)
                        <tr onclick="toggleChart('{{ $row->ticker }}')">
                            <td class="ticker">{{ $row->ticker }}</td>
                            <td>{{ $row->date }}</td>
                            <td class="num {{ $row->close >= 0 ? 'pos' : 'neg' }}">{{ number_format($row->close, 2) }}</td>
                        </tr>
                    @endforeach
                </tbody>
            </table>
        </div>
    @else
        <div class="empty">No signals found.</div>
    @endif

    <div class="chart-wrap">
        <div class="chart-inner" id="chartBody">
            <div id="chartLoading" class="empty-chart">Click a ticker to view chart</div>
        </div>
    </div>

    <script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
    <script>
        let chartInstance = null;
        let activeTicker = null;

        function toggleChart(ticker) {
            if (activeTicker === ticker) { closeChart(); return; }
            document.querySelectorAll('#scannerTable tr').forEach(r => r.classList.remove('active'));
            event?.target?.closest('tr')?.classList?.add('active');
            activeTicker = ticker;
            const body = document.getElementById('chartBody');
            body.innerHTML = '<div class="empty-chart">Loading ' + ticker + '...</div>';
            fetch('/scanner/data/' + ticker)
                .then(r => r.json())
                .then(d => renderChart(d))
                .catch(e => body.innerHTML = '<div class="empty-chart" style="color:#f85149;">Error: ' + e.message + '</div>');
        }

        function closeChart() {
            document.querySelectorAll('#scannerTable tr.active').forEach(r => r.classList.remove('active'));
            if (chartInstance) { chartInstance.remove(); chartInstance = null; }
            activeTicker = null;
            document.getElementById('chartBody').innerHTML = '<div class="empty-chart">Click a ticker to view chart</div>';
        }

        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeChart(); });

        function renderChart(d) {
            const body = document.getElementById('chartBody');
            if (chartInstance) { chartInstance.remove(); chartInstance = null; }
            body.innerHTML = '';
            body.style.display = 'flex'; body.style.flexDirection = 'column'; body.style.gap = '2px';

            const pricePanel = document.createElement('div'); pricePanel.style.flex = '3'; body.appendChild(pricePanel);
            const macdPanel = document.createElement('div'); macdPanel.style.flex = '2'; body.appendChild(macdPanel);
            const ppoPanel = document.createElement('div'); ppoPanel.style.flex = '2'; body.appendChild(ppoPanel);

            const base = {
                layout: { textColor:'#8b949e', background:{ color:'#13151f' } },
                grid: { vertLines:{ color:'#1c1e26' }, horzLines:{ color:'#1c1e26' } },
                crosshair: { mode:0, vertLine:{ visible:false, labelVisible:false }, horzLine:{ visible:false, labelVisible:false } },
                rightPriceScale: { borderColor:'#2d2f3a' },
                timeScale: { borderColor:'#2d2f3a', timeVisible:false, rightOffset:4 },
            };
            const sub = { ...base, rightPriceScale: { ...base.rightPriceScale, scaleMargins: { top:0.1, bottom:0.1 } }, timeScale: { ...base.timeScale, visible:false } };

            const chart = LightweightCharts.createChart(pricePanel, base);
            const macdC = LightweightCharts.createChart(macdPanel, sub);
            const ppoC = LightweightCharts.createChart(ppoPanel, sub);

            const candleData = d.bars.map(b => ({ time:b.date, open:parseFloat(b.open), high:parseFloat(b.high), low:parseFloat(b.low), close:parseFloat(b.close) }));
            chart.addCandlestickSeries({ upColor:'#3fb950', downColor:'#f85149', borderDownColor:'#f85149', borderUpColor:'#3fb950', wickDownColor:'#f85149', wickUpColor:'#3fb950' })
                .setData(candleData);

            const ema10 = [];
            const period = 10, mult = 2 / (period + 1);
            candleData.forEach((c, i) => {
                const prev = i > 0 ? ema10[i-1].value : c.close;
                ema10.push({ time: c.time, value: (c.close - prev) * mult + prev });
            });
            chart.addLineSeries({ color:'#3fb950', lineWidth:2, title:'EMA10', priceFormat:{ type:'price', precision:2, minMove:0.01 } }).setData(ema10);

            const sma40 = [];
            const period40 = 40;
            candleData.forEach((c, i) => {
                if (i < period40 - 1) return;
                let sum = 0;
                for (let j = i - period40 + 1; j <= i; j++) sum += candleData[j].close;
                sma40.push({ time: c.time, value: sum / period40 });
            });
            chart.addLineSeries({ color:'#f85149', lineWidth:2, title:'SMA40', priceFormat:{ type:'price', precision:2, minMove:0.01 } }).setData(sma40);

            const ind = d.indicators;
            macdC.addLineSeries({ color:'#58a6ff', lineWidth:1.5, title:'MACD', priceFormat:{ type:'price', precision:4, minMove:0.0001 } })
                .setData(ind.map(i => ({ time:i.date, value:parseFloat(i.macd_line||0) })));
            macdC.addLineSeries({ color:'#ffa657', lineWidth:1.5, title:'Signal', priceFormat:{ type:'price', precision:4, minMove:0.0001 } })
                .setData(ind.map(i => ({ time:i.date, value:parseFloat(i.macd_signal||0) })));
            macdC.addHistogramSeries({ priceFormat:{ type:'volume' }, priceScaleId:'' })
                .setData(ind.map(i => ({ time:i.date, value:parseFloat(i.macd_histogram||0), color:(i.macd_histogram||0)>=0?'rgba(63,185,80,0.5)':'rgba(248,81,73,0.5)' })));

            ppoC.addLineSeries({ color:'#3fb950', lineWidth:1.5, title:'PPO', priceFormat:{ type:'price', precision:4, minMove:0.0001 } })
                .setData(ind.map(i => ({ time:i.date, value:parseFloat(i.ppo_line||0) })));
            ppoC.addLineSeries({ color:'#f85149', lineWidth:1, title:'Zero', priceFormat:{ type:'price', precision:4, minMove:0.0001 } })
                .setData(ind.map(i => ({ time:i.date, value:0 })));

            chart.timeScale().fitContent();
            chartInstance = chart;
        }
    </script>
</body>
</html>
