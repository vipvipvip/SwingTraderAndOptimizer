<script>
  export let strategy
  export let strategies = []
  export let onClick = undefined

  $: isPortfolio = strategy.params?.is_portfolio ?? false
  $: inPosition = strategy.in_position ?? false

  $: subTickers = strategies
    .filter(s => s.symbol !== 'BLENDED')
    .map(s => {
      const p = s.params
      const exit = `${p?.chandelier_period ?? '?'}, ${p?.chandelier_mult ?? '?'}`
      const entry = p?.chandelier_entry_mult != null ? `, e=${p.chandelier_entry_mult}` : ''
      return `${s.symbol} (${exit}${entry})`
    })
    .join(' / ')

  const fmt = {
    sharpe: (v) => (v == null ? '-' : (+v).toFixed(2)),
    pct:    (v) => (v == null ? '-' : (+v * 100).toFixed(1) + '%'),
    dec2:   (v) => (v == null ? '-' : (+v).toFixed(2)),
  }
</script>

<style>
  .card {
    background: white;
    padding: 16px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .card:hover {
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
    transform: translateY(-2px);
  }

  .card.portfolio {
    border: 2px solid #3b82f6;
    background: linear-gradient(135deg, #eff6ff 0%, #fff 100%);
  }

  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .symbol {
    font-size: 20px;
    font-weight: 600;
    color: #333;
  }

  .price {
    font-size: 18px;
    font-weight: 500;
    color: #555;
    margin-left: auto;
  }

  .badge {
    display: inline-block;
    padding: 2px 8px;
    background: #e8f5e9;
    color: #2e7d32;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
  }

  .badge.portfolio-badge {
    background: #dbeafe;
    color: #1e40af;
  }

  .metrics {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .metric {
    font-size: 12px;
  }

  .metric-label {
    color: #999;
    margin-bottom: 4px;
  }

  .metric-value {
    font-size: 16px;
    font-weight: 600;
    color: #333;
  }

  .params {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #eee;
    font-size: 12px;
    color: #666;
  }

  .param-row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 4px;
  }
</style>

<div class="card" class:portfolio={isPortfolio} on:click={onClick} role="button" tabindex="0" on:keydown={(e) => e.key === 'Enter' && onClick?.()}>
  <div class="header">
    <div class="symbol">{isPortfolio ? 'PORTFOLIO' : strategy.symbol}</div>
    <div class="badge" class:portfolio-badge={isPortfolio}>{isPortfolio ? 'PORTFOLIO' : 'ACTIVE'}</div>
    <div class="price">${fmt.dec2(strategy.price)}</div>
  </div>

  <div class="metrics">
    <div class="metric">
      <div class="metric-label">Sharpe Ratio</div>
      <div class="metric-value">{fmt.sharpe(strategy.params?.sharpe_ratio)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Win Rate</div>
      <div class="metric-value">{fmt.pct(strategy.params?.win_rate)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Return</div>
      <div class="metric-value">{fmt.pct(strategy.params?.total_return)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value">{fmt.pct(strategy.params?.max_drawdown)}</div>
    </div>
  </div>

  {#if isPortfolio}
    <div class="params">
      <div class="param-row">
        <span>Strategy:</span>
        <span>Chandelier Exit (shared pool)</span>
      </div>
      <div class="param-row">
        <span>Tickers:</span>
        <span>{subTickers}</span>
      </div>
      <div class="param-row">
        <span>Trades:</span>
        <span>{strategy.params?.total_trades ?? '-'}</span>
      </div>
      <div class="param-row">
        <span>Capital:</span>
        <span>Shared pool ($100k)</span>
      </div>
    </div>
  {:else}
    <div class="params">
      <div class="param-row">
        <span>Exit:</span>
        <span>CHAND({strategy.params?.chandelier_period}, {(+strategy.params?.chandelier_mult).toFixed(1)}× ATR)</span>
      </div>
      <div class="param-row">
        <span>Entry:</span>
        {#if strategy.params?.chandelier_entry_mult != null}
          <span>Price &gt; High − {(+strategy.params.chandelier_entry_mult).toFixed(1)}× ATR{strategy.entry_level != null ? ` [$${fmt.dec2(strategy.entry_level)}]` : ''}</span>
        {:else}
          <span>Always (next bar open)</span>
        {/if}
      </div>
      <div class="param-row">
        <span>ATR:</span>
        <span>{fmt.dec2(strategy.atr)}</span>
      </div>
      {#if inPosition}
        <div class="param-row">
          <span>High since entry:</span>
          <span>{fmt.dec2(strategy.high)}</span>
        </div>
        <div class="param-row">
          <span>Stop level:</span>
          <span style="color: #d32f2f">${fmt.dec2(strategy.stop)}</span>
        </div>
        <div class="param-row">
          <span>Entry price:</span>
          <span>${fmt.dec2(strategy.price)}
            {#if strategy.pnl_unrealized != null}
              <span style="color: {strategy.pnl_unrealized >= 0 ? '#2e7d32' : '#d32f2f'}">
                ({strategy.pnl_unrealized >= 0 ? '+' : ''}{strategy.pnl_unrealized}%)
              </span>
            {/if}
          </span>
        </div>
      {:else if strategy.entry_level != null}
        <div class="param-row">
          <span>Entry level:</span>
          <span style="color: #1565c0">${fmt.dec2(strategy.entry_level)}</span>
        </div>
      {/if}
      <div class="param-row">
        <span>Trades:</span>
        <span>{strategy.params?.total_trades ?? '-'}</span>
      </div>
    </div>
  {/if}
</div>
