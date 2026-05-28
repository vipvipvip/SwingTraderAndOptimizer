<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Scanner</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4e8; height: 100vh; display: flex; flex-direction: column; }
        .top-bar { display: flex; align-items: center; gap: 10px; padding: 6px 14px; background: #1c1e26; border-bottom: 1px solid #2d2f3a; flex-shrink: 0; }
        .top-bar select { background: #0f1117; border: 1px solid #2d2f3a; color: #e1e4e8; padding: 3px 6px; border-radius: 4px; font-size: 12px; }
        .top-bar .signals { font-size: 12px; color: #3fb950; margin-left: auto; }
        .top-bar .scanned { font-size: 12px; color: #8b949e; }
        .divider { width:1px; height:16px; background:#2d2f3a; }
        .table-wrap { flex-shrink: 0; overflow-y: auto; max-height: 180px; border-bottom: 1px solid #2d2f3a; }
        .table-wrap table { width: 100%; border-collapse: collapse; table-layout: fixed; }

        .table-wrap thead { position: sticky; top: 0; z-index: 1; }
        .table-wrap th { background: #23252f; padding: 3px 5px; text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: 0.3px; color: #8b949e; white-space: nowrap; }
        .table-wrap td { padding: 2px 5px; font-size: 10px; border-bottom: 1px solid #1c1e26; white-space: nowrap; }
        .table-wrap tr:last-child td { border-bottom: none; }
        .table-wrap tr:hover td { background: #23252f; }
        .table-wrap tr { cursor: pointer; }
        .table-wrap tr.active td { background: #1a2a3a; }
        .table-wrap tr.new-row td { background: #14281a; }
        .table-wrap tr.new-row:hover td { background: #1a3322; }
        .table-wrap .new-badge { display: inline-block; font-size: 8px; font-weight: 700; color: #3fb950; background: #1a3322; padding: 1px 4px; border-radius: 3px; margin-left: 4px; vertical-align: middle; }
        .table-wrap .ticker { font-weight: 600; }
        .table-wrap .ticker-bull { color: #3fb950; }
        .table-wrap .ticker-bear { color: #f85149; }
        .table-wrap .num { font-family: 'JetBrains Mono', 'Fira Code', monospace; text-align: right; }
        .table-wrap .pos { color: #3fb950; }
        .table-wrap .neg { color: #f85149; }
        .cross-dot { display:inline-block; width:4px; height:4px; border-radius:50%; margin-right:1px; vertical-align:middle; }
        .chart-wrap { flex: 1; min-height: 0; padding: 4px; display: flex; flex-direction: column; }
        .chart-wrap .chart-inner { flex: 1; display: flex; flex-direction: column; gap: 2px; min-height: 0; }
        .empty-chart { display: flex; align-items: center; justify-content: center; height: 100%; color: #4a4d59; font-size: 15px; }
        .ticker-search { position:relative; }
        .ticker-search input { background:#0f1117; border:1px solid #2d2f3a; color:#e1e4e8; padding:3px 6px; border-radius:4px; font-size:12px; width:90px; outline:none; }
        .ticker-search input:focus { border-color:#58a6ff; }
    </style>
</head>
<body>
    <div class="top-bar">
        <span style="color:#8b949e;font-size:12px;">as of: <?php echo e($timeframe === '1hour' ? \Carbon\Carbon::parse($latest_run)->format('M j, g:ia') : \Carbon\Carbon::parse($latest_run)->format('M j, Y')); ?></span>
        <div class="divider"></div>
        <label style="color:#8b949e;font-size:12px;">Time:</label>
        <select onchange="changeTimeframe(this.value)">
            <option value="weekly" <?php echo e($timeframe == 'weekly' ? 'selected' : ''); ?>>W</option>
            <option value="daily" <?php echo e($timeframe == 'daily' ? 'selected' : ''); ?>>D</option>
            <option value="1hour" <?php echo e($timeframe == '1hour' ? 'selected' : ''); ?>>1H</option>
        </select>
        <div class="ticker-search">
            <input type="text" id="tickerSearch" placeholder="Ticker..." list="tickerList" autocomplete="off">
            <datalist id="tickerList"></datalist>
        </div>
        <span class="scanned"><?php echo e(number_format($total_scanned)); ?> tickers</span>
        <span class="signals"><?php echo e($total_signals); ?> signals</span>
    </div>

    <?php if(count($results) > 0): ?>
        <div class="table-wrap" id="tableWrap">
            <table id="scannerTable">
                <colgroup>
                    <col style="width:42px;">
                    <col style="width:108px;">
                    <col style="width:52px;">
                    <col style="width:72px;">
                    <col style="width:48px;">
                </colgroup>
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Crossovers</th>
                        <th style="text-align:right;">Stop</th>
                        <th style="text-align:right;">Dist</th>
                        <th style="text-align:right;">Close</th>
                    </tr>
                </thead>
                <tbody>
                    <?php $__currentLoopData = $results; $__env->addLoop($__currentLoopData); foreach($__currentLoopData as $row): $__env->incrementLoopIndices(); $loop = $__env->getLastLoop(); ?>
                        <?php
                            $fmt = $timeframe === '1hour' ? 'M j, g:ia' : 'M j';
                            $md = \Carbon\Carbon::parse($row->macd_cross_date)->format($fmt);
                            $pd = \Carbon\Carbon::parse($row->ppo_cross_date)->format($fmt);
                            $sd = \Carbon\Carbon::parse($row->sma_cross_date)->format($fmt);
                            $atr = $row->atr_stop !== null ? number_format((float)$row->atr_stop, 2) : '-';
                            $distD = $row->stop_dist_dollar !== null ? number_format($row->stop_dist_dollar, 2) : '-';
                            $distP = $row->stop_dist_pct !== null ? number_format($row->stop_dist_pct, 1) . '%' : '-';
                        ?>
                        <tr data-ticker="<?php echo e($row->ticker); ?>">
                            <td class="ticker <?php echo e($row->cross_bullish ? 'ticker-bull' : 'ticker-bear'); ?>"><?php echo e($row->ticker); ?></td>
                            <td style="font-size:10px; line-height:1.5; letter-spacing:-0.2px;">
                                <span class="cross-dot" style="background:#58a6ff;"></span><?php echo e($md); ?>

                                <span class="cross-dot" style="background:#3fb950;margin-left:3px;"></span><?php echo e($pd); ?>

                                <span class="cross-dot" style="background:#f0883e;margin-left:3px;"></span><?php echo e($sd); ?>

                            </td>
                            <td class="num"><?php echo e($atr); ?></td>
                            <td class="num"><?php echo e($distD); ?> <span style="color:#8b949e;font-size:10px;"><?php echo e($distP); ?></span></td>
                            <td class="num <?php echo e($row->close >= 0 ? 'pos' : 'neg'); ?>"><?php echo e(number_format($row->close, 2)); ?></td>
                        </tr>
                    <?php endforeach; $__env->popLoop(); $loop = $__env->getLastLoop(); ?>
                </tbody>
            </table>
        </div>
    <?php else: ?>
        <div class="empty" style="padding:20px;text-align:center;color:#4a4d59;">No signals found for <?php echo e($timeframe); ?> timeframe.</div>
    <?php endif; ?>

    <div class="chart-wrap">
        <div class="chart-inner" id="chartBody">
            <div id="chartLoading" class="empty-chart">Click a ticker to view chart</div>
        </div>
    </div>

    <script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
    <script>
        const currentTimeframe = '<?php echo e($timeframe); ?>';
        let chartInstance = null;
        let activeTicker = null;
        let selectedIndex = -1;

        function getRows() {
            return document.querySelectorAll('#scannerTable tbody tr');
        }

        function changeTimeframe(tf) {
            let url = '/scanner?timeframe=' + tf;
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
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
            const tableWrap = document.getElementById('tableWrap');
            if (tableWrap) {
                const wrapRect = tableWrap.getBoundingClientRect();
                const rowRect = row.getBoundingClientRect();
                tableWrap.scrollTop += rowRect.top - wrapRect.top - wrapRect.height / 2 + rowRect.height / 2;
            }
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

        const allTickers = <?php echo json_encode($all_tickers, 15, 512) ?>;
        const tickerSearch = document.getElementById('tickerSearch');
        const tickerList = document.getElementById('tickerList');
        allTickers.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            tickerList.appendChild(opt);
        });
        function selectTicker(val) {
            const rows = getRows();
            let found = false;
            for (let i = 0; i < rows.length; i++) {
                if (rows[i].dataset.ticker === val) {
                    selectRow(i);
                    found = true;
                    break;
                }
            }
            if (!found) {
                getRows().forEach(r => r.classList.remove('active'));
                activeTicker = null;
                loadChart(val);
            }
        }

        tickerSearch.addEventListener('change', function() {
            const val = this.value.toUpperCase();
            if (!allTickers.includes(val)) return;
            this.value = val;
            selectTicker(val);
        });

        const urlParams = new URLSearchParams(window.location.search);
        const urlTicker = urlParams.get('ticker');
        if (urlTicker && allTickers.includes(urlTicker)) {
            tickerSearch.value = urlTicker;
            selectTicker(urlTicker);
        }

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
            const regimePanel = document.createElement('div'); regimePanel.style.flex = '0.4'; body.appendChild(regimePanel);
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
            const subRegime = { ...base, rightPriceScale: { ...base.rightPriceScale, scaleMargins: { top:0.0, bottom:0.0 } }, timeScale: { ...base.timeScale, visible:false } };

            const chart = LightweightCharts.createChart(pricePanel, base);
            const macdC = LightweightCharts.createChart(macdPanel, sub);
            const ppoC = LightweightCharts.createChart(ppoPanel, sub);
            const regimeC = LightweightCharts.createChart(regimePanel, subRegime);
            const allLineSeries = [];

            const candleData = d.bars.map(b => ({ time:parseTime(b.date), open:parseFloat(b.open), high:parseFloat(b.high), low:parseFloat(b.low), close:parseFloat(b.close) }));
            const candleSeries = chart.addCandlestickSeries({ upColor:'#3fb950', downColor:'#f85149', borderDownColor:'#f85149', borderUpColor:'#3fb950', wickDownColor:'#f85149', wickUpColor:'#3fb950', priceLineVisible:false, lastValueVisible:false });
            candleSeries.setData(candleData);
            allLineSeries.push({ series: candleSeries, color: '#3fb950' });

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

            if (d.latest && d.latest.atr_stop != null) {
                const atrLine = chart.addLineSeries({ color:'#f0883e', lineWidth:1, lineStyle:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:2, minMove:0.01 } });
                const atrVal = parseFloat(d.latest.atr_stop);
                atrLine.setData(candleData.map(c => ({ time: c.time, value: atrVal })));
                allLineSeries.push({ series:atrLine, color:'#f0883e' });
            }

            const ind = d.indicators;
            function nn(v) { return v != null && !isNaN(v); }

            // Regime panel — colored background fill
            const regimeColors = { 'Bull': 'rgba(63,185,80,0.55)', 'Bear': 'rgba(248,81,73,0.55)', 'Choppy': 'rgba(240,136,62,0.5)' };
            const good = ind.filter(i => i.hmm_regime);
            if (good.length > 1) {
                const backgroundData = good.map(i => ({
                    time: parseTime(i.date),
                    value: regimeColors[i.hmm_regime] === regimeColors.Bull ? 2 : regimeColors[i.hmm_regime] === regimeColors.Bear ? 0 : 1,
                    color: regimeColors[i.hmm_regime] || 'rgba(128,128,128,0.3)'
                }));
                if (backgroundData.length > 1) {
                    regimeC.addHistogramSeries({ priceFormat: { type: 'volume' } }).setData(backgroundData);
                    regimeC.priceScale('right').applyOptions({ scaleMargins: { top: 0.0, bottom: 0.0 } });
                    regimeC.timeScale().setVisibleRange({ from: backgroundData[0].time, to: backgroundData[backgroundData.length-1].time });
                }
            }
            // Regime badge on price panel
            if (good.length > 0) {
                const latest = good[good.length - 1];
                const r = latest.hmm_regime;
                const badge = document.createElement('div');
                badge.style.cssText = 'position:absolute;top:8px;right:8px;z-index:1000;font-size:11px;padding:3px 10px;border-radius:5px;background:' + (regimeColors[r].replace('0.5', '0.85')||'#555') + ';color:#fff;border:1px solid rgba(255,255,255,0.3);';
                const pct = Math.round(parseFloat(latest['hmm_' + r.toLowerCase() + '_prob'] || 0) * 100);
                badge.textContent = r + ' ' + pct + '%';
                pricePanel.appendChild(badge);
            }
            const macdLine = macdC.addLineSeries({ color:'#58a6ff', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); macdLine.setData(ind.filter(i => nn(i.macd_line)).map(i => ({ time:parseTime(i.date), value:parseFloat(i.macd_line) }))); allLineSeries.push({ series:macdLine, color:'#58a6ff' });
            const macdSig = macdC.addLineSeries({ color:'#ffa657', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); macdSig.setData(ind.filter(i => nn(i.macd_signal)).map(i => ({ time:parseTime(i.date), value:parseFloat(i.macd_signal) }))); allLineSeries.push({ series:macdSig, color:'#ffa657' });
            const macdHist = macdC.addHistogramSeries({ priceFormat:{ type:'volume' }, priceScaleId:'' }); macdHist.setData(ind.filter(i => nn(i.macd_histogram)).map(i => ({ time:parseTime(i.date), value:parseFloat(i.macd_histogram), color:i.macd_histogram>=0?'rgba(63,185,80,0.5)':'rgba(248,81,73,0.5)' })));

            const ppoLine = ppoC.addLineSeries({ color:'#3fb950', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoLine.setData(ind.filter(i => nn(i.ppo_line)).map(i => ({ time:parseTime(i.date), value:parseFloat(i.ppo_line) }))); allLineSeries.push({ series:ppoLine, color:'#3fb950' });
            const ppoSig = ppoC.addLineSeries({ color:'#ffa657', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoSig.setData(ind.filter(i => nn(i.ppo_signal)).map(i => ({ time:parseTime(i.date), value:parseFloat(i.ppo_signal) }))); allLineSeries.push({ series:ppoSig, color:'#ffa657' });
            const ppoZero = ppoC.addLineSeries({ color:'#f85149', lineWidth:1, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoZero.setData(ind.map(i => ({ time:parseTime(i.date), value:0 }))); allLineSeries.push({ series:ppoZero, color:'#f85149' });

            const priceMarkers = [], macdMarkers = [], ppoMarkers = [], smaMarkers = [];
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
                if (c.sma_crossover) smaMarkers.push({ time:t, position:'belowBar', shape:'diamond', color:'#f0883e', size:1 });
            }

            const allPriceMarkers = [...priceMarkers, ...smaMarkers];

             let crosshairTime = null;
             let syncingCrosshair = false;
              function syncCrosshair(param) {
                  if (syncingCrosshair) return;
                  syncingCrosshair = true;
                  try {
                      crosshairTime = param.time ? param.time : null;
                      const cc = '#f0f0f0';
                      allLineSeries.forEach(({ series, color }) => {
                          if (series === ema10s) {
                              ema10s.setMarkers(crosshairTime ? [...allPriceMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color:cc, size:2 }] : allPriceMarkers);
                          } else if (series === macdLine) {
                              macdLine.setMarkers(crosshairTime ? [...macdMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color:cc, size:2 }] : macdMarkers);
                          } else if (series === ppoLine) {
                              ppoLine.setMarkers(crosshairTime ? [...ppoMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color:cc, size:2 }] : ppoMarkers);
                          } else if (series !== candleSeries) {
                              series.setMarkers(crosshairTime ? [{ time:crosshairTime, position:'inBar', shape:'circle', color:cc, size:2 }] : []);
                          }
                      });
                  } finally {
                      syncingCrosshair = false;
                  }
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
                if (source !== regimeC) regimeC.timeScale().setVisibleRange(rr);
                zoomSyncing = false;
            }
            chart.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(chart, r));
            macdC.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(macdC, r));
            ppoC.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(ppoC, r));
            regimeC.timeScale().subscribeVisibleTimeRangeChange(r => onZoomSync(regimeC, r));

            chart.timeScale().fitContent();
            chartInstance = chart;
        }
    </script>
</body>
</html><?php /**PATH /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/backend/resources/views/scanner/index.blade.php ENDPATH**/ ?>