<script>
  export let strategy
  export let onClick = undefined

  $: isPortfolio = strategy.params?.is_portfolio ?? false

  const fmt = {
    sharpe: (v) => (v == null ? '-' : (+v).toFixed(2)),
    pct:    (v) => (v == null ? '-' : (+v * 100).toFixed(1) + '%'),
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

  .allocation {
    font-size: 16px;
    font-weight: 600;
    color: #666;
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
    {#if !isPortfolio}
      <div class="allocation">({strategy.allocation_weight ?? 0}%)</div>
    {/if}
    <div class="badge" class:portfolio-badge={isPortfolio}>{isPortfolio ? 'PORTFOLIO' : 'ACTIVE'}</div>
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
        <span>QQQ (14, 3.0) / VTI (14, 3.5) / VTV (14, 3.5)</span>
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
        <span>Chandelier({strategy.params?.macd_fast}, {strategy.params?.bb_std})</span>
      </div>
      <div class="param-row">
        <span>ATR:</span>
        <span>({strategy.params?.bb_period})</span>
      </div>
      <div class="param-row">
        <span>Re-entry:</span>
        <span>Always (next bar open)</span>
      </div>
      <div class="param-row">
        <span>Trades:</span>
        <span>{strategy.params?.total_trades ?? '-'}</span>
      </div>
    </div>
  {/if}
</div>
