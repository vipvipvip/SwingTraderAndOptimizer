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
        <span style="color:#8b949e;font-size:12px;">as of: {{ $timeframe === '1hour' ? \Carbon\Carbon::parse($latest_run)->format('M j, g:ia') : \Carbon\Carbon::parse($latest_run)->format('M j, Y') }}</span>
        <div class="divider"></div>
        <label style="color:#8b949e;font-size:12px;">Time:</label>
        <select onchange="changeTimeframe(this.value)">
            <option value="weekly" {{ $timeframe == 'weekly' ? 'selected' : '' }}>W</option>
            <option value="daily" {{ $timeframe == 'daily' ? 'selected' : '' }}>D</option>
            <option value="1hour" {{ $timeframe == '1hour' ? 'selected' : '' }}>1H</option>
        </select>
        <div class="divider"></div>
        <label style="color:#8b949e;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px;">
            <input type="checkbox" id="longToggle" {{ isset($long) && $long ? 'checked' : '' }} style="accent-color:#3fb950;cursor:pointer;">
            <span style="color:#3fb950;font-weight:600;">Long</span>
        </label>
        <label style="color:#8b949e;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px;">
            <input type="checkbox" id="shortToggle" {{ isset($short) && $short ? 'checked' : '' }} style="accent-color:#f85149;cursor:pointer;">
            <span style="color:#f85149;font-weight:600;">Short</span>
        </label>
        <div class="divider"></div>
        <label style="color:#8b949e;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px;">
            <input type="checkbox" id="undervaluedToggle" {{ $undervalued ? 'checked' : '' }} style="accent-color:#3fb950;cursor:pointer;">
            Undervalued
        </label>
        <label style="color:#8b949e;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px;">
            <input type="checkbox" id="weeklyCrossoverToggle" {{ $weekly_crossover ? 'checked' : '' }} style="accent-color:#58a6ff;cursor:pointer;">
            Wkly Cross
        </label>
        <label style="color:#8b949e;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px;">
            <input type="checkbox" id="multitfUptrendToggle" {{ isset($multitf_uptrend) && $multitf_uptrend ? 'checked' : '' }} style="accent-color:#c9a0ff;cursor:pointer;">
            Multi-TF
        </label>
        <label style="color:#8b949e;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:4px;">
            <input type="checkbox" id="infancyToggle" {{ isset($infancy) && $infancy ? 'checked' : '' }} style="accent-color:#ff7b72;cursor:pointer;">
            Infancy
        </label>
        @if ($undervalued)
            <button id="updateValuationsBtn" onclick="updateValuations()" style="background:#1c1e26;border:1px solid #2d2f3a;color:#e1e4e8;padding:3px 10px;border-radius:4px;font-size:12px;cursor:pointer;">Update Valuations</button>
        @endif
        <span class="scanned" id="breadthBadge" style="font-size:12px;font-weight:600;cursor:default;" title="% of S&P 500 in multi-TF uptrend">
            {{ isset($pct) ? $pct . '%' : '-' }}
            @if (isset($pct))
                <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{{ $color ?? '#8b949e' }};margin-left:2px;vertical-align:middle;"></span>
                <span style="color:{{ $color ?? '#8b949e' }};font-size:10px;">{{ $regime ?? '' }}</span>
            @endif
        </span>
        <div class="divider"></div>
        <button onclick="copyTickers()" style="background:#1c1e26;border:1px solid #2d2f3a;color:#e1e4e8;padding:3px 10px;border-radius:4px;font-size:12px;cursor:pointer;" title="Copy tickers to clipboard">📋 Copy</button>
        <div class="ticker-search">
            <input type="text" id="tickerSearch" placeholder="Ticker..." list="tickerList" autocomplete="off">
            <datalist id="tickerList"></datalist>
        </div>
        <span class="scanned">{{ number_format($total_scanned) }} tickers</span>
        <span class="signals">{{ $total_signals }} signals</span>
    </div>

    @if (count($results) > 0)
        <div class="table-wrap" id="tableWrap">
            @if ($weekly_crossover)
                {{-- Weekly EMA(10)/SMA(40) crossover table --}}
                <table id="scannerTable" style="width:auto; table-layout:auto;">
                    <colgroup>
                        <col style="width:44px;">
                        <col style="width:100px;">
                        <col style="width:48px;">
                        <col style="width:48px;">
                        <col style="width:48px;">
                        <col style="width:42px;">
                        <col style="width:40px;">
                        <col style="width:40px;">
                        <col style="width:54px;">
                        <col style="width:62px;">
                        <col style="width:30px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company</th>
                            <th style="text-align:right;">Close</th>
                            <th style="text-align:right;">EMA(10)</th>
                            <th style="text-align:right;">SMA(40)</th>
                            <th style="text-align:right;">Gap %</th>
                            <th style="text-align:right;">MACD</th>
                            <th style="text-align:right;">PPO</th>
                            <th>Status</th>
                            <th>Cross</th>
                            <th style="text-align:right;">Mom</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($results as $row)
                            <tr data-ticker="{{ $row->ticker }}">
                                <td class="ticker" style="color:{{ $row->status === 'Bullish' ? '#3fb950' : ($row->status === 'Neutral' ? '#d29922' : '#f85149') }};">{{ $row->ticker }}</td>
                                <td style="color:#8b949e;font-size:9px;">{{ $row->company_name ?? '-' }}</td>
                                <td class="num">{{ number_format((float)$row->close, 2) }}</td>
                                <td class="num {{ (float)$row->close >= (float)$row->ema10 ? 'pos' : 'neg' }}">{{ number_format((float)$row->ema10, 2) }}</td>
                                <td class="num {{ (float)$row->close >= (float)$row->sma40 ? 'pos' : 'neg' }}">{{ number_format((float)$row->sma40, 2) }}</td>
                                <td class="num {{ (float)$row->gap_pct >= 0 ? 'pos' : 'neg' }}">{{ number_format((float)$row->gap_pct, 1) }}%</td>
                                <td class="num {{ (float)$row->macd_hist >= 0 ? 'pos' : 'neg' }}">{{ number_format((float)$row->macd_hist, 2) }}</td>
                                <td class="num {{ (float)$row->ppo_hist >= 0 ? 'pos' : 'neg' }}">{{ number_format((float)$row->ppo_hist, 2) }}</td>
                                <td><span style="color:{{ $row->status === 'Bullish' ? '#3fb950' : ($row->status === 'Neutral' ? '#d29922' : '#f85149') }};font-size:10px;">{{ $row->status }}</span></td>
                                <td style="font-size:10px;color:#8b949e;">{{ $row->last_cross_date ? \Carbon\Carbon::parse($row->last_cross_date)->format('M j, Y') : '-' }}</td>
                                <td style="text-align:right;font-size:11px;color:{{ $row->momentum_score >= 7 ? '#3fb950' : ($row->momentum_score >= 4 ? '#d29922' : '#8b949e') }};">{{ $row->momentum_score }}</td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
            @elseif (isset($multitf_uptrend) && $multitf_uptrend)
                {{-- Multi-TF Uptrend: weekly + daily bullish, optionally 1-hour entry --}}
                <table id="scannerTable" style="width:auto; table-layout:auto;">
                    <colgroup>
                        <col style="width:44px;">
                        <col style="width:100px;">
                        <col style="width:48px;">
                        <col style="width:36px;">
                        <col style="width:46px;">
                        <col style="width:46px;">
                        <col style="width:50px;">
                        <col style="width:76px;">
                        <col style="width:76px;">
                        <col style="width:52px;">
                        <col style="width:52px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company</th>
                            <th style="text-align:right;">Close</th>
                            <th style="text-align:right;">Score</th>
                            <th style="text-align:right;">GapW%</th>
                            <th style="text-align:right;">ATR%</th>
                            <th>Fresh</th>
                            <th>Wkly Cross</th>
                            <th>Daily Cross</th>
                            <th>1H Entry</th>
                            <th>New Daily</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($results as $row)
                            @php $infancy = $row->infancy ?? false; @endphp
                            <tr data-ticker="{{ $row->ticker }}" class="{{ $infancy ? 'new-row' : '' }}">
                                <td class="ticker {{ $infancy ? 'ticker-bull' : (($row->gap_w ?? 0) >= 0 ? 'ticker-bull' : 'ticker-bear') }}">{{ $row->ticker }}</td>
                                <td style="color:#8b949e;font-size:9px;">{{ $row->company_name ?? '-' }}</td>
                                <td class="num pos">{{ number_format((float)$row->close, 2) }}</td>
                                <td class="num" style="color:{{ $row->score >= 5 ? '#c9a0ff' : ($row->score >= 3 ? '#d29922' : '#8b949e') }};">{{ $row->score }}</td>
                                <td class="num {{ (float)$row->gap_w >= 0 ? 'pos' : 'neg' }}">{{ $row->gap_w }}%</td>
                                <td class="num pos">{{ $row->atr_dist }}%</td>
                                <td style="font-size:10px;">
                                    @if ($infancy)
                                        <span class="new-badge" style="background:#3d1a1a;color:#ff7b72;">{{ $row->days_weekly }}d</span>
                                    @else
                                        <span style="color:#8b949e;">{{ $row->days_weekly }}d</span>
                                    @endif
                                </td>
                                <td style="font-size:10px;color:#8b949e;">{{ $row->weekly_cross_date ? \Carbon\Carbon::parse($row->weekly_cross_date)->format('M j, Y') : '-' }}</td>
                                <td style="font-size:10px;color:#8b949e;">{{ $row->daily_cross_date ? \Carbon\Carbon::parse($row->daily_cross_date)->format('M j, Y') : '-' }}</td>
                                <td>
                                    @if ($row->hourly_entry)
                                        <span class="new-badge" style="background:#2d1b4e;color:#c9a0ff;">ENTRY</span>
                                    @endif
                                </td>
                                <td>
                                    @if ($row->new_daily_uptrend)
                                        <span class="new-badge" style="background:#1a3322;color:#3fb950;">NEW</span>
                                    @endif
                                </td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
        @elseif (isset($long) && $long)
                {{-- Long signals: fresh MACD/PPO zero-line crossovers --}}
                <table id="scannerTable">
                    <colgroup>
                        <col style="width:44px;">
                        <col style="width:120px;">
                        <col style="width:48px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:46px;">
                        <col style="width:30px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company</th>
                            <th>Cross</th>
                            <th style="text-align:right;">Close</th>
                            <th style="text-align:right;">MACD</th>
                            <th style="text-align:right;">PPO</th>
                            <th style="text-align:right;">ATR Stop</th>
                            <th style="text-align:right;">Dist%</th>
                            <th style="text-align:right;">Scr</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($results as $row)
                            @php
                                $ruleLabels = [1 => 'Both', 2 => 'MACD Lead', 3 => 'PPO Lead'];
                                $ruleColors = [1 => '#3fb950', 2 => '#58a6ff', 3 => '#d29922'];
                                $rl = $ruleLabels[$row->rule] ?? '?';
                                $rc = $ruleColors[$row->rule] ?? '#8b949e';
                            @endphp
                            <tr data-ticker="{{ $row->ticker }}">
                                <td class="ticker ticker-bull">{{ $row->ticker }}</td>
                                <td style="color:#8b949e;font-size:9px;">{{ $row->company_name ?? '-' }}</td>
                                <td><span style="color:{{ $rc }};font-size:9px;font-weight:600;">{{ $rl }}</span></td>
                                <td class="num pos">{{ number_format((float)$row->close, 2) }}</td>
                                <td class="num {{ (float)$row->macd_hist >= 0 ? 'pos' : 'neg' }}">{{ number_format((float)$row->macd_hist, 2) }}</td>
                                <td class="num {{ (float)$row->ppo_hist >= 0 ? 'pos' : 'neg' }}">{{ number_format((float)$row->ppo_hist, 2) }}</td>
                                <td class="num">{{ number_format((float)$row->atr_stop, 2) }}</td>
                                <td class="num pos">{{ $row->stop_dist_pct }}%</td>
                                <td class="num" style="color:#3fb950;">{{ $row->score }}</td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
            @elseif (isset($short) && $short)
                {{-- Short signals: Rule 3 — Momentum Breaker --}}
                <table id="scannerTable">
                    <colgroup>
                        <col style="width:44px;">
                        <col style="width:120px;">
                        <col style="width:54px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:46px;">
                        <col style="width:30px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company</th>
                            <th>Rule</th>
                            <th style="text-align:right;">Close</th>
                            <th style="text-align:right;">MACD</th>
                            <th style="text-align:right;">PPO</th>
                            <th style="text-align:right;">ATR Stop</th>
                            <th style="text-align:right;">Dist%</th>
                            <th style="text-align:right;">Scr</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($results as $row)
                            <tr data-ticker="{{ $row->ticker }}">
                                <td class="ticker ticker-bear">{{ $row->ticker }}</td>
                                <td style="color:#8b949e;font-size:9px;">{{ $row->company_name ?? '-' }}</td>
                                <td><span style="color:#f85149;font-size:9px;font-weight:600;">PPO Break</span></td>
                                <td class="num">{{ number_format((float)$row->close, 2) }}</td>
                                <td class="num pos">{{ number_format((float)$row->macd_hist, 2) }}</td>
                                <td class="num neg">{{ number_format((float)$row->ppo_hist, 2) }}</td>
                                <td class="num">{{ (float)$row->atr_stop > 0 ? number_format((float)$row->atr_stop, 2) : '-' }}</td>
                                <td class="num {{ isset($row->stop_dist_pct) && $row->stop_dist_pct < 0 ? 'neg' : (isset($row->stop_dist_pct) && $row->stop_dist_pct > 0 ? 'pos' : '') }}">{{ $row->stop_dist_pct ?? '-' }}%</td>
                                <td class="num" style="color:#f85149;">{{ $row->score }}</td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
            @elseif ($undervalued)
                {{-- Stock Analyzer: undervalued table --}}
                <table id="scannerTable" style="width:auto; table-layout:auto;">
                    <colgroup>
                        <col style="width:44px;">
                        <col style="width:120px;">
                        <col style="width:68px;">
                        <col style="width:60px;">
                        <col style="width:52px;">
                        <col style="width:56px;">
                        <col style="width:56px;">
                        <col style="width:48px;">
                        <col style="width:56px;">
                        <col style="width:36px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company</th>
                            <th style="text-align:right;">Valuation</th>
                            <th style="text-align:right;">Close</th>
                            <th style="text-align:right;">Upside</th>
                            <th style="text-align:right;">Revenue</th>
                            <th style="text-align:right;">Net Income</th>
                            <th style="text-align:right;">EPS</th>
                            <th style="text-align:right;">Shares</th>
                            <th style="text-align:right;">PE</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($results as $row)
                            @php
                                $rev = (float)$row->db_revenue;
                                $revFmt = $rev >= 1e12 ? number_format($rev / 1e12, 1) . 'T'
                                        : ($rev >= 1e9 ? number_format($rev / 1e9, 1) . 'B'
                                        : number_format($rev / 1e6, 0) . 'M');
                                $ni = (float)$row->db_net_income;
                                $niFmt = $ni >= 1e12 ? number_format($ni / 1e12, 1) . 'T'
                                       : (abs($ni) >= 1e9 ? number_format($ni / 1e9, 1) . 'B'
                                       : number_format($ni / 1e6, 0) . 'M');
                                $shares = (float)$row->db_shares_outstanding;
                                $shrFmt = $shares >= 1e9 ? number_format($shares / 1e9, 2) . 'B'
                                        : number_format($shares / 1e6, 0) . 'M';
                                $eps = $row->db_eps !== null ? number_format((float)$row->db_eps, 2) : '-';
                                $pe = $row->db_pe_ratio !== null ? number_format((float)$row->db_pe_ratio, 1) : '-';
                            @endphp
                            <tr data-ticker="{{ $row->ticker }}">
                                <td class="ticker ticker-bull">{{ $row->ticker }}</td>
                                <td style="color:#8b949e;">{{ $row->db_company_name ?? '-' }}</td>
                                <td class="num pos">${{ number_format((float)$row->db_valuation_price, 2) }}</td>
                                <td class="num">{{ number_format((float)$row->db_close, 2) }}</td>
                                <td class="num pos">{{ number_format((float)$row->upside_pct, 1) }}%</td>
                                <td class="num">{{ $revFmt }}</td>
                                <td class="num">{{ $niFmt }}</td>
                                <td class="num">{{ $eps }}</td>
                                <td class="num">{{ $shrFmt }}</td>
                                <td class="num">{{ $pe }}</td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
            @else
                {{-- Scanner: signal table (original) --}}
                <table id="scannerTable" style="width:auto; table-layout:auto;">
                    <colgroup>
                        <col style="width:44px;">
                        <col style="width:120px;">
                        <col style="width:108px;">
                        <col style="width:52px;">
                        <col style="width:72px;">
                        <col style="width:48px;">
                    </colgroup>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Company</th>
                            <th>Crossovers</th>
                            <th style="text-align:right;">Stop</th>
                            <th style="text-align:right;">Dist</th>
                            <th style="text-align:right;">Close</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($results as $row)
                            @php
                                $fmt = $timeframe === '1hour' ? 'M j, g:ia' : 'M j';
                                $md = \Carbon\Carbon::parse($row->macd_cross_date)->format($fmt);
                                $pd = \Carbon\Carbon::parse($row->ppo_cross_date)->format($fmt);
                                $sd = \Carbon\Carbon::parse($row->sma_cross_date)->format($fmt);
                                $atr = $row->atr_stop !== null ? number_format((float)$row->atr_stop, 2) : '-';
                                $distD = $row->stop_dist_dollar !== null ? number_format($row->stop_dist_dollar, 2) : '-';
                                $distP = $row->stop_dist_pct !== null ? number_format($row->stop_dist_pct, 1) . '%' : '-';
                            @endphp
                            <tr data-ticker="{{ $row->ticker }}">
                                <td class="ticker {{ $row->cross_bullish ? 'ticker-bull' : 'ticker-bear' }}">{{ $row->ticker }}</td>
                                <td style="color:#8b949e;">{{ $row->company_name ?? '-' }}</td>
                                <td style="font-size:10px; line-height:1.5; letter-spacing:-0.2px;">
                                    <span class="cross-dot" style="background:#58a6ff;"></span>{{ $md }}
                                    <span class="cross-dot" style="background:#3fb950;margin-left:3px;"></span>{{ $pd }}
                                    <span class="cross-dot" style="background:#f0883e;margin-left:3px;"></span>{{ $sd }}
                                </td>
                                <td class="num">{{ $atr }}</td>
                                <td class="num">{{ $distD }} <span style="color:#8b949e;font-size:10px;">{{ $distP }}</span></td>
                                <td class="num {{ $row->close >= 0 ? 'pos' : 'neg' }}">{{ number_format($row->close, 2) }}</td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
            @endif
        </div>
    @else
        <div class="empty" style="padding:20px;text-align:center;color:#4a4d59;">
            @if ($weekly_crossover)
                No tickers with weekly crossover data found.
            @elseif (isset($multitf_uptrend) && $multitf_uptrend)
                @if (isset($infancy) && $infancy)
                    No infancy entries found (weekly cross < 60 days).
                @else
                    No tickers in multi-timeframe uptrend.
                @endif
            @elseif (isset($long) && $long)
                No long signals found for {{ $timeframe }} timeframe.
            @elseif (isset($short) && $short)
                No short signals found for {{ $timeframe }} timeframe.
            @elseif ($undervalued)
                No undervalued stocks found.
            @else
                No signals found for {{ $timeframe }} timeframe.
            @endif
        </div>
    @endif

    <div class="chart-wrap">
        <div class="chart-inner" id="chartBody">
            <div id="chartLoading" class="empty-chart">Click a ticker to view chart</div>
        </div>
    </div>

    <script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
    <script>
        if (history.scrollRestoration) history.scrollRestoration = 'manual';
        window.scrollTo(0, 0);
        const currentTimeframe = '{{ $timeframe }}';
        let chartInstance = null;
        let activeTicker = null;
        let selectedIndex = -1;

        function getRows() {
            return document.querySelectorAll('#scannerTable tbody tr');
        }

        function changeTimeframe(tf) {
            if (activeTicker) {
                // Chart is open — reload just the chart, not the whole page
                currentTimeframe = tf;
                document.querySelector('.top-bar select').value = tf;
                loadChart(activeTicker);
                return;
            }
            let url = '/scanner?timeframe=' + tf;
            if (document.getElementById('undervaluedToggle').checked) url += '&undervalued=1';
            if (document.getElementById('weeklyCrossoverToggle').checked) url += '&weekly_crossover=1';
            if (document.getElementById('multitfUptrendToggle').checked) url += '&multitf_uptrend=1';
            if (document.getElementById('infancyToggle').checked) url += '&infancy=1';
            if (document.getElementById('longToggle').checked) url += '&long=1';
            if (document.getElementById('shortToggle').checked) url += '&short=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        }

        function uncheckAllFilters() {
            document.getElementById('undervaluedToggle').checked = false;
            document.getElementById('weeklyCrossoverToggle').checked = false;
            document.getElementById('multitfUptrendToggle').checked = false;
            document.getElementById('infancyToggle').checked = false;
            document.getElementById('longToggle').checked = false;
            document.getElementById('shortToggle').checked = false;
        }

        document.getElementById('undervaluedToggle').addEventListener('change', function() {
            if (this.checked) uncheckAllFilters();
            this.checked = true;
            let url = '/scanner?timeframe=' + currentTimeframe;
            if (this.checked) url += '&undervalued=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        });

        document.getElementById('weeklyCrossoverToggle').addEventListener('change', function() {
            if (this.checked) uncheckAllFilters();
            this.checked = true;
            let url = '/scanner?timeframe=' + currentTimeframe;
            if (this.checked) url += '&weekly_crossover=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        });

        document.getElementById('multitfUptrendToggle').addEventListener('change', function() {
            if (this.checked) uncheckAllFilters();
            this.checked = true;
            let url = '/scanner?timeframe=' + currentTimeframe;
            if (this.checked) url += '&multitf_uptrend=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        });

        document.getElementById('infancyToggle').addEventListener('change', function() {
            let url = '/scanner?timeframe=' + currentTimeframe;
            if (document.getElementById('multitfUptrendToggle').checked) url += '&multitf_uptrend=1';
            if (this.checked) url += '&infancy=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        });

        document.getElementById('longToggle').addEventListener('change', function() {
            if (this.checked) uncheckAllFilters();
            this.checked = true;
            let url = '/scanner?timeframe=' + currentTimeframe;
            if (this.checked) url += '&long=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        });

        document.getElementById('shortToggle').addEventListener('change', function() {
            if (this.checked) uncheckAllFilters();
            this.checked = true;
            let url = '/scanner?timeframe=' + currentTimeframe;
            if (this.checked) url += '&short=1';
            if (activeTicker) url += '&ticker=' + activeTicker;
            window.location = url;
        });

        function selectRow(index) {
            const rows = getRows();
            if (index < 0) index = 0;
            if (index >= rows.length) index = rows.length - 1;
            rows.forEach(r => r.classList.remove('active'));
            const row = rows[index];
            if (!row) return;
            row.classList.add('active');
            selectedIndex = index;
            row.scrollIntoView({ block: 'center' });
            const ticker = row.dataset.ticker;
            if (ticker && ticker !== activeTicker) loadChart(ticker);
        }

        function loadChart(ticker) {
            activeTicker = ticker;
            const row = document.querySelector('tr[data-ticker="' + ticker + '"]');
            const company = row ? (row.children[1]?.textContent?.trim() || '') : '';
            const headerHtml = '<div id="chartHeader" style="color:#e1e4e8;font-size:13px;font-weight:600;padding:4px 8px;border-bottom:1px solid #2d2f3a;flex-shrink:0;">' + ticker + (company ? ' — ' + company : '') + '</div>';
            const body = document.getElementById('chartBody');
            body.innerHTML = headerHtml + '<div class="empty-chart">Loading ' + ticker + '...</div>';
            fetch('/scanner/data/' + ticker + '?timeframe=' + currentTimeframe)
                .then(r => r.json())
                .then(d => renderChart(d))
                .catch(e => body.innerHTML = headerHtml + '<div class="empty-chart" style="color:#f85149;">Error: ' + e.message + '</div>');
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
            const isSearchFocused = document.activeElement === tickerSearch;
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

        document.getElementById('scannerTable')?.addEventListener('click', e => {
            const row = e.target.closest('tr');
            if (!row || !row.dataset.ticker) return;
            const idx = Array.from(getRows()).indexOf(row);
            selectRow(idx);
        });

        const allTickers = @json($all_tickers);
        const tickerSearch = document.getElementById('tickerSearch');
        const tickerList = document.getElementById('tickerList');
        allTickers.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            tickerList.appendChild(opt);
        });
        let searchIndex = -1;

        function doSelectTicker(val) {
            val = val.toUpperCase();
            const rows = getRows();
            let found = false;
            for (let i = 0; i < rows.length; i++) {
                if (rows[i].dataset.ticker === val) {
                    selectRow(i);
                    found = true;
                    break;
                }
            }
            if (!found && allTickers.includes(val)) {
                getRows().forEach(r => r.classList.remove('active'));
                activeTicker = null;
                loadChart(val);
            }
        }

        tickerSearch.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                searchIndex = searchIndex < 0 ? 0 : Math.min(searchIndex + 1, allTickers.length - 1);
                this.value = allTickers[searchIndex];
                doSelectTicker(this.value);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                searchIndex = searchIndex < 0 ? allTickers.length - 1 : Math.max(searchIndex - 1, 0);
                this.value = allTickers[searchIndex];
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
            if (allTickers.includes(val)) doSelectTicker(val);
            this.value = '';
            searchIndex = -1;
        });

        const urlParams = new URLSearchParams(window.location.search);
        const urlTicker = urlParams.get('ticker');
        if (urlTicker) doSelectTicker(urlTicker.toUpperCase());

        function copyTickers() {
            const params = new URLSearchParams(window.location.search);
            let url = '/scanner/copy-tickers?' + params.toString();
            fetch(url)
                .then(r => r.json())
                .then(d => {
                    if (d.tickers) {
                        navigator.clipboard.writeText(d.tickers).then(() => {
                            const badge = document.getElementById('breadthBadge');
                            const orig = badge.innerHTML;
                            badge.innerHTML = '✔ Copied!';
                            setTimeout(() => badge.innerHTML = orig, 1500);
                        });
                    }
                })
                .catch(e => console.error('Copy failed:', e));
        }

        function updateValuations() {
            const btn = document.getElementById('updateValuationsBtn');
            btn.disabled = true;
            btn.textContent = 'Updating...';
            const body = document.getElementById('chartBody');
            body.innerHTML = '<div class="empty-chart">Updating valuations...</div>';
            fetch('/scanner/update-valuations', { method: 'POST', headers: { 'X-CSRF-TOKEN': '{{ csrf_token() }}' } })
                .then(r => r.json())
                .then(d => {
                    if (d.success) {
                        body.innerHTML = '<div class="empty-chart" style="color:#3fb950;">Valuations updated. Reloading...</div>';
                        setTimeout(() => window.location.reload(), 1500);
                    } else {
                        body.innerHTML = '<div class="empty-chart" style="color:#f85149;">Error: exit code ' + d.exit_code + '</div>';
                        btn.disabled = false;
                        btn.textContent = 'Update Valuations';
                    }
                })
                .catch(e => {
                    body.innerHTML = '<div class="empty-chart" style="color:#f85149;">Request failed: ' + e.message + '</div>';
                    btn.disabled = false;
                    btn.textContent = 'Update Valuations';
                });
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
            const header = document.getElementById('chartHeader');
            body.innerHTML = '';
            body.style.display = 'flex'; body.style.flexDirection = 'column'; body.style.gap = '2px';
            if (header) body.appendChild(header);

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

            if (d.latest && d.latest.atr_stop != null) {
                const atrLine = chart.addLineSeries({ color:'#f0883e', lineWidth:1, lineStyle:2, priceLineVisible:false, lastValueVisible:false, priceFormat:{ type:'price', precision:2, minMove:0.01 } });
                const atrVal = parseFloat(d.latest.atr_stop);
                atrLine.setData(candleData.map(c => ({ time: c.time, value: atrVal })));
                allLineSeries.push({ series:atrLine, color:'#f0883e' });
            }

            const ind = d.indicators;
            function nn(v) { return v != null && !isNaN(v); }
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
    </script>
</body>
</html>