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
        .divider { width:1px; height:20px; background:#2d2f3a; }
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
        <span style="color:#8b949e;font-size:13px;">as of: {{ $timeframe === '1hour' ? \Carbon\Carbon::parse($latest_run)->format('M j, g:ia') : \Carbon\Carbon::parse($latest_run)->format('M j, Y') }}</span>
        <div class="divider"></div>
        <label style="color:#8b949e;font-size:13px;">Timeframe:</label>
        <select onchange="changeTimeframe(this.value)">
            <option value="weekly" {{ $timeframe == 'weekly' ? 'selected' : '' }}>Weekly</option>
            <option value="daily" {{ $timeframe == 'daily' ? 'selected' : '' }}>Daily</option>
            <option value="1hour" {{ $timeframe == '1hour' ? 'selected' : '' }}>1Hour</option>
        </select>
        <div class="divider"></div>
        <label style="color:#8b949e;font-size:13px;">Lookback:</label>
        <select onchange="changeLookback(this.value)">
            <option value="1" {{ $weeks == 1 ? 'selected' : '' }}>1w</option>
            <option value="2" {{ $weeks == 2 ? 'selected' : '' }}>2w</option>
            <option value="3" {{ $weeks == 3 ? 'selected' : '' }}>3w</option>
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
                        <tr data-ticker="{{ $row->ticker }}">
                            <td class="ticker">{{ $row->ticker }}</td>
                            <td>{{ $row->date }}</td>
                            <td class="num {{ $row->close >= 0 ? 'pos' : 'neg' }}">{{ number_format($row->close, 2) }}</td>
                        </tr>
                    @endforeach
                </tbody>
            </table>
        </div>
    @else
        <div class="empty" style="padding:20px;text-align:center;color:#4a4d59;">No signals found for {{ $timeframe }} timeframe.</div>
    @endif

    <div class="chart-wrap">
        <div class="chart-inner" id="chartBody">
            <div id="chartLoading" class="empty-chart">Click a ticker to view chart</div>
        </div>
    </div>

    <script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
    <script>
        const currentTimeframe = '{{ $timeframe }}';
        const currentWeeks = {{ $weeks }};
        let chartInstance = null;
        let activeTicker = null;
        let selectedIndex = -1;

        function getRows() {
            return document.querySelectorAll('#scannerTable tbody tr');
        }

        function changeTimeframe(tf) {
            window.location = '/scanner?timeframe=' + tf + '&weeks=' + currentWeeks;
        }

        function changeLookback(w) {
            window.location = '/scanner?timeframe=' + currentTimeframe + '&weeks=' + w;
        }

        function selectRow(index) {
            const rows = getRows();
            if (index < 0) index = 0;
            if (index >= rows.length) index = rows.length - 1;
            rows.forEach(r => r.classList.remove('active'));
            const row = rows[index];
            if (!row) return;
            row.classList.add('active');
            selectedIndex = index;
            row.scrollIntoView({ block: 'nearest' });
            const ticker = row.dataset.ticker;
            if (ticker && ticker !== activeTicker) loadChart(ticker);
        }

        function loadChart(ticker) {
            activeTicker = ticker;
            const body = document.getElementById('chartBody');
            body.innerHTML = '<div class="empty-chart">Loading ' + ticker + '...</div>';
            fetch('/scanner/data/' + ticker + '?timeframe=' + currentTimeframe)
                .then(r => r.json())
                .then(d => renderChart(d))
                .catch(e => body.innerHTML = '<div class="empty-chart" style="color:#f85149;">Error: ' + e.message + '</div>');
        }

        function closeChart() {
            getRows().forEach(r => r.classList.remove('active'));
            if (chartInstance) { chartInstance.remove(); chartInstance = null; }
            activeTicker = null;
            selectedIndex = -1;
            document.getElementById('chartBody').innerHTML = '<div class="empty-chart">Select a ticker</div>';
        }

        document.addEventListener('keydown', e => {
            const rows = getRows();
            if (rows.length === 0) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectRow(selectedIndex < 0 ? 0 : Math.min(selectedIndex + 1, rows.length - 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectRow(selectedIndex < 0 ? rows.length - 1 : Math.max(selectedIndex - 1, 0));
            } else if (e.key === 'Escape') {
                closeChart();
            }
        });

        document.getElementById('scannerTable')?.addEventListener('click', e => {
            const row = e.target.closest('tr');
            if (!row || !row.dataset.ticker) return;
            const idx = Array.from(getRows()).indexOf(row);
            selectRow(idx);
        });

        function parseTime(v) {
            if (currentTimeframe === '1hour') {
                const d = new Date(v + (v.includes('Z') || v.includes('+') ? '' : 'Z'));
                return Math.floor(d.getTime() / 1000);
            }
            return v;
        }

        function renderChart(d) {
            const body = document.getElementById('chartBody');
            if (chartInstance) { chartInstance.remove(); chartInstance = null; }
            body.innerHTML = '';
            body.style.display = 'flex'; body.style.flexDirection = 'column'; body.style.gap = '2px';

            const pricePanel = document.createElement('div'); pricePanel.style.flex = '3'; body.appendChild(pricePanel);
            pricePanel.style.position = 'relative';
            const macdPanel = document.createElement('div'); macdPanel.style.flex = '2'; body.appendChild(macdPanel);
            const ppoPanel = document.createElement('div'); ppoPanel.style.flex = '2'; body.appendChild(ppoPanel);

            const isIntraday = currentTimeframe === '1hour';
            const base = {
                layout: { textColor:'#8b949e', background:{ color:'#13151f' } },
                grid: { vertLines:{ color:'#1c1e26' }, horzLines:{ color:'#1c1e26' } },
                crosshair: { mode:1, vertLine:{ visible:true, labelVisible:true, width:1, color:'#585858', style:2 }, horzLine:{ visible:true, labelVisible:true, width:1, color:'#585858', style:2 } },
                rightPriceScale: { borderColor:'#2d2f3a' },
                timeScale: { borderColor:'#2d2f3a', timeVisible:isIntraday, secondsVisible:false, rightOffset:4 },
            };
            const sub = { ...base, rightPriceScale: { ...base.rightPriceScale, scaleMargins: { top:0.1, bottom:0.1 } }, timeScale: { ...base.timeScale, visible:false } };

            const chart = LightweightCharts.createChart(pricePanel, base);
            const macdC = LightweightCharts.createChart(macdPanel, sub);
            const ppoC = LightweightCharts.createChart(ppoPanel, sub);
            const allLineSeries = [];

            const candleData = d.bars.map(b => ({ time:parseTime(b.date), open:parseFloat(b.open), high:parseFloat(b.high), low:parseFloat(b.low), close:parseFloat(b.close) }));
            chart.addCandlestickSeries({ upColor:'#3fb950', downColor:'#f85149', borderDownColor:'#f85149', borderUpColor:'#3fb950', wickDownColor:'#f85149', wickUpColor:'#3fb950', priceLineVisible:false, lastValueVisible:false })
                .setData(candleData);

            const ema10 = [];
            const period = 10, mult = 2 / (period + 1);
            candleData.forEach((c, i) => {
                const prev = i > 0 ? ema10[i-1].value : c.close;
                ema10.push({ time: c.time, value: (c.close - prev) * mult + prev });
            });
            const ema10s = chart.addLineSeries({ color:'#3fb950', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:2, minMove:0.01 } }); ema10s.setData(ema10); allLineSeries.push({ series:ema10s, color:'#3fb950' });

            const sma40 = [];
            const period40 = 40;
            candleData.forEach((c, i) => {
                if (i < period40 - 1) return;
                let sum = 0;
                for (let j = i - period40 + 1; j <= i; j++) sum += candleData[j].close;
                sma40.push({ time: c.time, value: sum / period40 });
            });
            const sma40s = chart.addLineSeries({ color:'#f85149', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:2, minMove:0.01 } }); sma40s.setData(sma40); allLineSeries.push({ series:sma40s, color:'#f85149' });

            const sma200 = [];
            const period200 = 200;
            candleData.forEach((c, i) => {
                if (i < period200 - 1) return;
                let sum = 0;
                for (let j = i - period200 + 1; j <= i; j++) sum += candleData[j].close;
                sma200.push({ time: c.time, value: sum / period200 });
            });
            const sma200s = chart.addLineSeries({ color:'#58a6ff', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:2, minMove:0.01 } }); sma200s.setData(sma200); allLineSeries.push({ series:sma200s, color:'#58a6ff' });

            const ind = d.indicators;
            const macdLine = macdC.addLineSeries({ color:'#58a6ff', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); macdLine.setData(ind.map(i => ({ time:parseTime(i.date), value:parseFloat(i.macd_line||0) }))); allLineSeries.push({ series:macdLine, color:'#58a6ff' });
            const macdSig = macdC.addLineSeries({ color:'#ffa657', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); macdSig.setData(ind.map(i => ({ time:parseTime(i.date), value:parseFloat(i.macd_signal||0) }))); allLineSeries.push({ series:macdSig, color:'#ffa657' });
            const macdHist = macdC.addHistogramSeries({ priceFormat:{ type:'volume' }, priceScaleId:'' }); macdHist.setData(ind.map(i => ({ time:parseTime(i.date), value:parseFloat(i.macd_histogram||0), color:(i.macd_histogram||0)>=0?'rgba(63,185,80,0.5)':'rgba(248,81,73,0.5)' })));

            const ppoLine = ppoC.addLineSeries({ color:'#3fb950', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoLine.setData(ind.map(i => ({ time:parseTime(i.date), value:parseFloat(i.ppo_line||0) }))); allLineSeries.push({ series:ppoLine, color:'#3fb950' });
            const ppoSig = ppoC.addLineSeries({ color:'#ffa657', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoSig.setData(ind.map(i => ({ time:parseTime(i.date), value:parseFloat(i.ppo_signal||0) }))); allLineSeries.push({ series:ppoSig, color:'#ffa657' });
            const ppoZero = ppoC.addLineSeries({ color:'#f85149', lineWidth:1, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoZero.setData(ind.map(i => ({ time:parseTime(i.date), value:0 }))); allLineSeries.push({ series:ppoZero, color:'#f85149' });

            const priceMarkers = [], macdMarkers = [], ppoMarkers = [];
            for (let i = 1; i < candleData.length; i++) {
                const pc = candleData[i], pp = candleData[i-1];
                const c10 = ema10.find(e => e.time === pc.time)?.value;
                const p10 = ema10.find(e => e.time === pp.time)?.value;
                const c40 = sma40.find(e => e.time === pc.time)?.value;
                const p40 = sma40.find(e => e.time === pp.time)?.value;
                if (c10 && p10 && c40 && p40) {
                    if (c10 > c40 && p10 <= p40) priceMarkers.push({ time:pc.time, position:'belowBar', shape:'arrowUp', color:'#3fb950', size:1 });
                    if (c10 < c40 && p10 >= p40) priceMarkers.push({ time:pc.time, position:'aboveBar', shape:'arrowDown', color:'#f85149', size:1 });
                }
            }
            for (let i = 1; i < ind.length; i++) {
                const c = ind[i], p = ind[i-1];
                const t = parseTime(c.date);
                const cml = parseFloat(c.macd_line), pml = parseFloat(p.macd_line);
                const cms = parseFloat(c.macd_signal), pms = parseFloat(p.macd_signal);
                if (cml > cms && pml <= pms) macdMarkers.push({ time:t, position:'belowBar', shape:'arrowUp', color:'#3fb950', size:1 });
                if (cml < cms && pml >= pms) macdMarkers.push({ time:t, position:'aboveBar', shape:'arrowDown', color:'#f85149', size:1 });
                const cpl = parseFloat(c.ppo_line), ppl = parseFloat(p.ppo_line);
                const cps = parseFloat(c.ppo_signal), pps = parseFloat(p.ppo_signal);
                if (cpl > cps && ppl <= pps) ppoMarkers.push({ time:t, position:'belowBar', shape:'arrowUp', color:'#3fb950', size:1 });
                if (cpl < cps && ppl >= pps) ppoMarkers.push({ time:t, position:'aboveBar', shape:'arrowDown', color:'#f85149', size:1 });
            }

            let crosshairTime = null;
            function syncCrosshair(param) {
                crosshairTime = param.time ? param.time : null;
                allLineSeries.forEach(({ series, color }) => {
                    if (series === ema10s) {
                        ema10s.setMarkers(crosshairTime ? [...priceMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color, size:2 }] : priceMarkers);
                    } else if (series === macdLine) {
                        macdLine.setMarkers(crosshairTime ? [...macdMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color, size:2 }] : macdMarkers);
                    } else if (series === ppoLine) {
                        ppoLine.setMarkers(crosshairTime ? [...ppoMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color, size:2 }] : ppoMarkers);
                    } else {
                        series.setMarkers(crosshairTime ? [{ time:crosshairTime, position:'inBar', shape:'circle', color, size:2 }] : []);
                    }
                });
            }
            chart.subscribeCrosshairMove(syncCrosshair);
            macdC.subscribeCrosshairMove(syncCrosshair);
            ppoC.subscribeCrosshairMove(syncCrosshair);
            syncCrosshair({});
            let zoomSyncing = false;
            function onZoomSync(source, range) {
                if (zoomSyncing || !range) return;
                zoomSyncing = true;
                const rr = { from: range.from, to: range.to };
                if (source !== chart) chart.timeScale().setVisibleRange(rr);
                if (source !== macdC) macdC.timeScale().setVisibleRange(rr);
                if (source !== ppoC) ppoC.timeScale().setVisibleRange(rr);
                zoomSyncing = false;
            }
            chart.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(chart, r));
            macdC.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(macdC, r));
            ppoC.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(ppoC, r));

            chart.timeScale().fitContent();
            chartInstance = chart;
        }
    </script>
</body>
</html>
