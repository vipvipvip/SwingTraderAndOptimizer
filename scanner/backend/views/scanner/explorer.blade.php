<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MTF Explorer Dashboard</title>
<link rel="icon" href="data:,">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4e8; height: 100vh; display: flex; flex-direction: column; }
.top-bar { display: flex; align-items: center; gap: 10px; padding: 6px 14px; background: #1c1e26; border-bottom: 1px solid #2d2f3a; flex-shrink: 0; }
.top-bar select { background: #0f1117; border: 1px solid #2d2f3a; color: #e1e4e8; padding: 3px 6px; border-radius: 4px; font-size: 12px; }
.top-bar .signals { font-size: 12px; color: #3fb950; margin-left: auto; }
.top-bar .scanned { font-size: 12px; color: #8b949e; }
.divider { width:1px; height:16px; background:#2d2f3a; }
.table-wrap { flex-shrink: 0; overflow: auto; max-height: 180px; border-bottom: 1px solid #2d2f3a; }
.table-wrap table { border-collapse: collapse; min-width: 700px; }
.table-wrap thead { position: sticky; top: 0; z-index: 1; }
.table-wrap th { background: #23252f; padding: 3px 5px; text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: 0.3px; color: #8b949e; white-space: nowrap; }
.table-wrap td { padding: 2px 5px; font-size: 10px; border-bottom: 1px solid #1c1e26; white-space: nowrap; }
.table-wrap tr:last-child td { border-bottom: none; }
.table-wrap tr:hover td { background: #23252f; }
.table-wrap tr { cursor: pointer; }
.table-wrap tr.active td,
.table-wrap tr.active td { background: #1a3a5c; }
.table-wrap tr.active td:first-child { border-left: 2px solid #58a6ff; padding-left: 3px; }
.table-wrap .ticker { font-weight: 600; }
.table-wrap .ticker-bull { color: #3fb950; }
.table-wrap .num { font-family: 'JetBrains Mono', 'Fira Code', monospace; text-align: right; }
.table-wrap .pos { color: #3fb950; }
.table-wrap .neg { color: #f85149; }
.chart-wrap { flex: 1; min-height: 0; padding: 4px; display: flex; flex-direction: column; }
.chart-wrap .chart-inner { flex: 1; display: flex; flex-direction: column; gap: 2px; min-height: 0; }
.empty-chart { display: flex; align-items: center; justify-content: center; height: 100%; color: #4a4d59; font-size: 15px; }
.ticker-search { position:relative; }
.ticker-search input { background:#0f1117; border:1px solid #2d2f3a; color:#e1e4e8; padding:3px 6px; border-radius:4px; font-size:12px; width:90px; outline:none; }
.ticker-search input:focus { border-color:#58a6ff; }
.score-high { color: #c9a0ff; }
.score-mid { color: #d29922; }
.score-low { color: #8b949e; }
.loading-overlay { display: flex; position: absolute; inset: 0; background: #0f1117; z-index: 10; align-items: center; justify-content: center; flex-direction: column; gap: 16px; }
.loading-overlay.hidden { display: none; }
.spinner { width: 40px; height: 40px; border: 3px solid #30363d; border-top-color: #58a6ff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: #e1e4e8; }
.sort-arrow { display: inline-block; width: 10px; margin-left: 2px; font-size: 9px; }
.signal-bull { color: #3fb950; font-size: 11px; font-weight: 700; }
.signal-bear { color: #f85149; font-size: 11px; font-weight: 700; }
.signal-na { color: #484f58; font-size: 11px; }
@media (max-width: 768px) {
  body { height: auto; min-height: 100vh; }
  .top-bar { flex-wrap: wrap; gap: 4px; padding: 4px 8px; font-size: 11px; }
  .top-bar select { font-size: 11px; padding: 4px 6px; }
  .top-bar .scanned, .top-bar .signals { font-size: 11px; }
  .ticker-search input { width: 70px; font-size: 11px; }
  .table-wrap { max-height: 150px; }
  .table-wrap th, .table-wrap td { font-size: 9px; padding: 2px 3px; }
  .table-wrap th:nth-child(n+5):nth-child(-n+8),
  .table-wrap td:nth-child(n+5):nth-child(-n+8) { display: none; }
  .chart-wrap { min-height: 300px; }
  .chart-wrap .chart-inner { gap: 1px; }
}
@media (max-width: 480px) {
  .top-bar { gap: 2px; }
  .top-bar .divider { display: none; }
  .ticker-search input { width: 60px; }
  .table-wrap th, .table-wrap td { font-size: 8px; padding: 1px 2px; }
  .table-wrap th:nth-child(9), .table-wrap td:nth-child(9),
  .table-wrap th:nth-child(10), .table-wrap td:nth-child(10) { display: none; }
}
</style>
</head>
<body>

<div class="top-bar">
  <span style="color:#8b949e;font-size:12px;">MTF Explorer</span>
  <div class="divider"></div>
  <label style="color:#8b949e;font-size:12px;">Mode:</label>
  <select id="modeSelect" onchange="switchMode(this.value)">
    <option value="stock" {{ $mode == 'stock' ? 'selected' : '' }}>Stocks</option>
    <option value="etf" {{ $mode == 'etf' ? 'selected' : '' }}>ETFs</option>
  </select>
  <div class="divider"></div>
  <button onclick="copyTickers()" style="background:#1c1e26;border:1px solid #2d2f3a;color:#e1e4e8;padding:3px 10px;border-radius:4px;font-size:12px;cursor:pointer;" title="Copy tickers to clipboard">📋 Copy</button>
  <span class="scanned" id="countLabel">— tickers</span>
  <div class="ticker-search">
    <input type="text" id="tickerSearch" placeholder="Ticker..." list="tickerList" autocomplete="off">
    <datalist id="tickerList"></datalist>
  </div>
  <span class="signals" id="breadthLabel"></span>
</div>

<div class="table-wrap" id="tableWrap" style="position:relative;">
  <div class="loading-overlay" id="loadingOverlay">
    <div class="spinner"></div>
    <div style="color:#8b949e;font-size:0.85rem;">Loading MTF data...</div>
  </div>
  <table id="scannerTable">
    <thead>
      <tr>
        <th style="width:24px;"><input type="checkbox" id="selectAll" onclick="toggleAll(this)" title="Select all"></th>
        <th data-sort="symbol" class="sortable">Ticker <span class="sort-arrow"></span></th>
        <th data-sort="close" class="sortable" style="text-align:right;">Price <span class="sort-arrow"></span></th>
        <th data-sort="mtf_score" class="sortable" style="text-align:right;">MTF Score <span class="sort-arrow"></span></th>
        <th data-sort="daily_signal" class="sortable" style="text-align:center;">Daily Signal <span class="sort-arrow"></span></th>
        <th data-sort="emac" class="sortable" style="text-align:center;">EMAC <span class="sort-arrow"></span></th>
        <th data-sort="chand" class="sortable" style="text-align:center;">CHAND <span class="sort-arrow"></span></th>
        <th data-sort="mtcs" class="sortable" style="text-align:center;">MTCS <span class="sort-arrow"></span></th>
        <th data-sort="combined" class="sortable" style="text-align:right;">Combined <span class="sort-arrow"></span></th>
        <th data-sort="early" class="sortable" style="text-align:right;">Early <span class="sort-arrow"></span></th>
      </tr>
    </thead>
    <tbody id="tableBody"></tbody>
  </table>
</div>

<div class="chart-wrap">
  <div class="chart-inner" id="chartBody">
    <div class="empty-chart">Select a ticker to view chart</div>
  </div>
</div>

<script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
let currentMode = '{{ $mode }}';
let allData = [];
let allSymbols = [];
let chartInstance = null;
let activeTicker = null;
let selectedIndex = -1;
let sortField = 'combined';
let sortDir = -1;

function getSortValue(p, field) {
  if (field === 'symbol') return p.symbol.toUpperCase();
  if (field === 'name') return (p.name || '').toUpperCase();
  if (field === 'chand' || field === 'emac' || field === 'mtcs' || field === 'daily_signal') {
    if (p[field] === 'bull') return 1;
    if (p[field] === 'bear') return -1;
    return 0;
  }
  return p[field] ?? 0;
}

function signalHtml(val) {
  if (val === 'bull') return '<span class="signal-bull">▲</span>';
  if (val === 'bear') return '<span class="signal-bear">▼</span>';
  return '<span class="signal-na">—</span>';
}

function sortData() {
  allData.sort((a, b) => {
    const va = getSortValue(a, sortField);
    const vb = getSortValue(b, sortField);
    if (va < vb) return -sortDir;
    if (va > vb) return sortDir;
    return 0;
  });
}

function handleSort(field) {
  if (sortField === field) {
    sortDir *= -1;
  } else {
    sortField = field;
    sortDir = field === 'symbol' || field === 'name' ? 1 : -1;
  }
  sortData();
  const arrows = document.querySelectorAll('.sort-arrow');
  arrows.forEach(a => a.textContent = '');
  const idx = Array.from(document.querySelectorAll('th.sortable')).findIndex(th => th.dataset.sort === field);
  if (idx >= 0) arrows[idx].textContent = sortDir === 1 ? '▲' : '▼';
  renderTable();
  if (activeTicker) {
    const i = allData.findIndex(p => p.symbol === activeTicker);
    if (i >= 0) selectRow(i);
  }
}

function getRows() {
  return document.querySelectorAll('#scannerTable tbody tr');
}

function scrollRowIntoView(row) {
  const container = document.querySelector('.table-wrap');
  if (!container) return;
  const rowTop = row.offsetTop;
  const rowH = row.offsetHeight;
  const cH = container.clientHeight;
  const target = rowTop - (cH / 2) + (rowH / 2);
  container.scrollTop = Math.max(0, Math.min(target, container.scrollHeight - cH));
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
  scrollRowIntoView(row);
  const ticker = row.dataset.ticker;
  if (ticker && ticker !== activeTicker) loadChart(ticker, row);
}

function renderTable() {
  const tbody = document.getElementById('tableBody');
  const q = document.getElementById('tickerSearch').value.toUpperCase();
  const filtered = allData.filter(p => p.symbol.includes(q) || (p.name && p.name.toUpperCase().includes(q)));
  tbody.innerHTML = filtered.map((p, i) => {
    const scoreClass = p.mtf_score >= 5 ? 'score-high' : p.mtf_score >= 3 ? 'score-mid' : 'score-low';
    const combinedClass = p.combined >= 8 ? 'score-high' : p.combined >= 5 ? 'score-mid' : 'score-low';
    return '<tr data-ticker="' + p.symbol + '" data-index="' + i + '">'
      + '<td><input type="checkbox" class="row-checkbox" value="' + p.symbol + '"></td>'
      + '<td class="ticker ticker-bull">' + p.symbol + '</td>'
      + '<td class="num pos">$' + (p.close ? p.close.toFixed(2) : '') + '</td>'
      + '<td class="num ' + scoreClass + '">' + p.mtf_score.toFixed(1) + '</td>'
      + '<td style="text-align:center;">' + signalHtml(p.daily_signal) + '</td>'
      + '<td style="text-align:center;">' + signalHtml(p.emac) + '</td>'
      + '<td style="text-align:center;">' + signalHtml(p.chand) + '</td>'
      + '<td style="text-align:center;">' + signalHtml(p.mtcs) + '</td>'
      + '<td class="num ' + combinedClass + '">' + p.combined.toFixed(1) + '</td>'
      + '<td class="num ' + (p.early >= 2 ? 'score-high' : p.early >= 0 ? 'score-mid' : 'score-low') + '">' + p.early.toFixed(1) + '</td>'
      + '</tr>';
  }).join('');
  allSymbols = filtered.map(p => p.symbol);
  updateDatalist();
}

function updateDatalist() {
  const list = document.getElementById('tickerList');
  list.innerHTML = allSymbols.map(s => '<option value="' + s + '">').join('');
}

async function loadData() {
  const tbody = document.getElementById('tableBody');
  const overlay = document.getElementById('loadingOverlay');
  tbody.innerHTML = '';
  overlay.classList.remove('hidden');
  try {
    const res = await fetch('/scanner/explorer-data?mode=' + currentMode);
    const data = await res.json();
    overlay.classList.add('hidden');
    if (data.error) { tbody.innerHTML = '<tr><td colspan="9" style="color:#da3633;padding:20px;text-align:center;">' + data.error + '</td></tr>'; return; }
    allData = data.picks;
    sortData();
    document.getElementById('countLabel').textContent = data.total + ' tickers';
    if (data.breadth !== null) {
      document.getElementById('breadthLabel').innerHTML = 'Breadth: ' + data.breadth + '%'
        + ' <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:'
        + (data.breadth < 35 ? '#da3633' : data.breadth < 55 ? '#d29922' : '#3fb950')
        + ';margin-left:2px;vertical-align:middle;"></span>';
    }
    renderTable();
    if (activeTicker) {
      const idx = allData.findIndex(p => p.symbol === activeTicker);
      if (idx >= 0) selectRow(idx);
    }
  } catch (e) {
    overlay.classList.add('hidden');
    tbody.innerHTML = '<tr><td colspan="9" style="color:#da3633;padding:20px;text-align:center;">Failed to load data</td></tr>';
  }
}

function switchMode(mode) {
  currentMode = mode;
  if (chartInstance) { chartInstance.remove(); chartInstance = null; }
  activeTicker = null;
  selectedIndex = -1;
  document.getElementById('chartBody').innerHTML = '<div class="empty-chart">Select a ticker to view chart</div>';
  loadData();
}

function toggleAll(selectAll) {
  document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = selectAll.checked);
}

function copyTickers() {
  const checked = document.querySelectorAll('.row-checkbox:checked');
  if (checked.length > 0) {
    const tickers = Array.from(checked).map(cb => cb.value).join(',');
    navigator.clipboard.writeText(tickers).then(() => {
      const label = document.getElementById('breadthLabel');
      const orig = label.innerHTML;
      label.innerHTML = '✔ Copied!';
      setTimeout(() => label.innerHTML = orig, 1500);
    });
    return;
  }
  const tickers = allData.map(p => p.symbol).join(',');
  navigator.clipboard.writeText(tickers).then(() => {
    const label = document.getElementById('breadthLabel');
    const orig = label.innerHTML;
    label.innerHTML = '✔ Copied!';
    setTimeout(() => label.innerHTML = orig, 1500);
  });
}

function doSelectTicker(val) {
  val = val.toUpperCase();
  const rows = getRows();
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].dataset.ticker === val) {
      selectRow(i);
      return;
    }
  }
  if (allSymbols.includes(val)) {
    getRows().forEach(r => r.classList.remove('active'));
    activeTicker = null;
    loadChart(val);
  }
}

function parseTime(v) {
  return v;
}

function loadChart(ticker, row) {
  activeTicker = ticker;
  if (!row) row = document.querySelector('tr[data-ticker="' + ticker + '"]');
  const label = ticker;
  const body = document.getElementById('chartBody');
  body.innerHTML = '<div id="chartHeader" style="color:#e1e4e8;font-size:13px;font-weight:600;padding:4px 8px;border-bottom:1px solid #2d2f3a;flex-shrink:0;text-align:center;">' + label + '</div><div class="empty-chart">Loading ' + ticker + '...</div>';
  fetch('/scanner/data/' + ticker + '?timeframe=weekly&limit=300')
    .then(r => r.json())
    .then(d => renderChart(d))
    .catch(e => body.innerHTML = '<div id="chartHeader" style="color:#e1e4e8;font-size:13px;font-weight:600;padding:4px 8px;border-bottom:1px solid #2d2f3a;flex-shrink:0;text-align:center;">' + label + '</div><div class="empty-chart" style="color:#f85149;">Error: ' + e.message + '</div>');
}

function closeChart() {
  getRows().forEach(r => r.classList.remove('active'));
  if (chartInstance) { chartInstance.remove(); chartInstance = null; }
  activeTicker = null;
  selectedIndex = -1;
  document.getElementById('chartBody').innerHTML = '<div class="empty-chart">Select a ticker to view chart</div>';
}

function renderChart(d) {
  const body = document.getElementById('chartBody');
  if (chartInstance) { chartInstance.remove(); chartInstance = null; }
  const header = document.getElementById('chartHeader');
  body.innerHTML = '';
  body.style.display = 'flex'; body.style.flexDirection = 'column'; body.style.gap = '2px';
  if (header) body.appendChild(header);

  const pricePanel = document.createElement('div'); pricePanel.style.flex = '3'; body.appendChild(pricePanel);
  pricePanel.style.position = 'relative';
  const macdPanel = document.createElement('div'); macdPanel.style.flex = '2'; body.appendChild(macdPanel);
  const ppoPanel = document.createElement('div'); ppoPanel.style.flex = '2'; body.appendChild(ppoPanel);

  const base = {
    layout: { textColor:'#8b949e', background:{ color:'#13151f' } },
    grid: { vertLines:{ color:'#1c1e26' }, horzLines:{ color:'#1c1e26' } },
    crosshair: { mode:1, vertLine:{ visible:true, labelVisible:true, width:1, color:'#585858', style:2 }, horzLine:{ visible:true, labelVisible:true, width:1, color:'#585858', style:2 } },
    rightPriceScale: { borderColor:'#2d2f3a' },
    timeScale: { borderColor:'#2d2f3a', timeVisible:false, secondsVisible:false, rightOffset:4 },
  };
  const sub = { ...base, rightPriceScale: { ...base.rightPriceScale, scaleMargins: { top:0.1, bottom:0.1 } }, timeScale: { ...base.timeScale, visible:false } };

  const chart = LightweightCharts.createChart(pricePanel, base);
  const macdC = LightweightCharts.createChart(macdPanel, sub);
  const ppoC = LightweightCharts.createChart(ppoPanel, sub);
  const allLineSeries = [];

  const candleData = d.bars.map(b => ({ time:b.date, open:parseFloat(b.open), high:parseFloat(b.high), low:parseFloat(b.low), close:parseFloat(b.close) }));
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

  if (d.latest && d.latest.atr_stop != null) {
    const atrLine = chart.addLineSeries({ color:'#f0883e', lineWidth:1, lineStyle:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:2, minMove:0.01 } });
    const atrVal = parseFloat(d.latest.atr_stop);
    atrLine.setData(candleData.map(c => ({ time: c.time, value: atrVal })));
    allLineSeries.push({ series:atrLine, color:'#f0883e' });
  }

  const ind = d.indicators;
  function nn(v) { return v != null && !isNaN(v); }
  const macdLine = macdC.addLineSeries({ color:'#58a6ff', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); macdLine.setData(ind.filter(i => nn(i.macd_line)).map(i => ({ time:i.date, value:parseFloat(i.macd_line) }))); allLineSeries.push({ series:macdLine, color:'#58a6ff' });
  const macdSig = macdC.addLineSeries({ color:'#ffa657', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); macdSig.setData(ind.filter(i => nn(i.macd_signal)).map(i => ({ time:i.date, value:parseFloat(i.macd_signal) }))); allLineSeries.push({ series:macdSig, color:'#ffa657' });
  const macdHist = macdC.addHistogramSeries({ priceFormat:{ type:'volume' }, priceScaleId:'' }); macdHist.setData(ind.filter(i => nn(i.macd_histogram)).map(i => ({ time:i.date, value:parseFloat(i.macd_histogram), color:i.macd_histogram>=0?'rgba(63,185,80,0.5)':'rgba(248,81,73,0.5)' })));

  const ppoLine = ppoC.addLineSeries({ color:'#3fb950', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoLine.setData(ind.filter(i => nn(i.ppo_line)).map(i => ({ time:i.date, value:parseFloat(i.ppo_line) }))); allLineSeries.push({ series:ppoLine, color:'#3fb950' });
  const ppoSig = ppoC.addLineSeries({ color:'#ffa657', lineWidth:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoSig.setData(ind.filter(i => nn(i.ppo_signal)).map(i => ({ time:i.date, value:parseFloat(i.ppo_signal) }))); allLineSeries.push({ series:ppoSig, color:'#ffa657' });
  const ppoZero = ppoC.addLineSeries({ color:'#f85149', lineWidth:1, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:4, minMove:0.0001 } }); ppoZero.setData(ind.map(i => ({ time:i.date, value:0 }))); allLineSeries.push({ series:ppoZero, color:'#f85149' });

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
    const t = c.date;
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
  function syncCrosshair(param) {
    crosshairTime = param.time ? param.time : null;
    allLineSeries.forEach(({ series, color }) => {
      if (series === ema10s) {
        ema10s.setMarkers(crosshairTime ? [...allPriceMarkers, { time:crosshairTime, position:'inBar', shape:'circle', color, size:2 }] : allPriceMarkers);
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

document.addEventListener('DOMContentLoaded', () => {
  const initialArrow = document.querySelector('th[data-sort="combined"] .sort-arrow');
  if (initialArrow) initialArrow.textContent = '▼';
  loadData();
});

document.querySelectorAll('th.sortable').forEach(th => {
  th.addEventListener('click', () => handleSort(th.dataset.sort));
});

document.getElementById('scannerTable')?.addEventListener('click', e => {
  if (e.target.closest('.row-checkbox')) return;
  const row = e.target.closest('tr');
  if (!row || !row.dataset.ticker) return;
  const idx = Array.from(getRows()).indexOf(row);
  selectRow(idx);
});

document.addEventListener('keydown', e => {
  const rows = getRows();
  if (rows.length === 0) return;
  const isSearchFocused = document.activeElement === document.getElementById('tickerSearch');
  if (e.key === 'ArrowDown') {
    if (isSearchFocused) return;
    e.preventDefault();
    selectRow(selectedIndex < 0 ? 0 : Math.min(selectedIndex + 1, rows.length - 1));
  } else if (e.key === 'ArrowUp') {
    if (isSearchFocused) return;
    e.preventDefault();
    selectRow(selectedIndex < 0 ? rows.length - 1 : Math.max(selectedIndex - 1, 0));
  } else if (e.key === 'Escape') {
    closeChart();
  }
});

const tickerSearch = document.getElementById('tickerSearch');
let searchIndex = -1;

tickerSearch.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    searchIndex = searchIndex < 0 ? 0 : Math.min(searchIndex + 1, allSymbols.length - 1);
    this.value = allSymbols[searchIndex];
    doSelectTicker(this.value);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    searchIndex = searchIndex < 0 ? allSymbols.length - 1 : Math.max(searchIndex - 1, 0);
    this.value = allSymbols[searchIndex];
    doSelectTicker(this.value);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const val = this.value.toUpperCase();
    doSelectTicker(val);
    this.blur();
    this.value = '';
    searchIndex = -1;
  }
});

tickerSearch.addEventListener('change', function() {
  const val = this.value.toUpperCase();
  if (allSymbols.includes(val)) doSelectTicker(val);
  this.value = '';
  searchIndex = -1;
});

tickerSearch.addEventListener('input', function() {
  renderTable();
});
</script>
</body>
</html>
