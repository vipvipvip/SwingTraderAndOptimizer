<script>
  export let strategy
  export let onClick = undefined

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

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
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

<div class="card" on:click={onClick} role="button" tabindex="0" on:keydown={(e) => e.key === 'Enter' && onClick?.()}>
  <div class="header">
    <div class="symbol">{strategy.symbol}</div>
    <div class="badge">ACTIVE</div>
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
      <div class="metric-value">-</div>
    </div>
  </div>

  <div class="params">
    <div class="param-row">
      <span>MACD:</span>
      <span>
        ({strategy.params?.macd_fast}, {strategy.params?.macd_slow}, {strategy.params?.macd_signal})
      </span>
    </div>
    <div class="param-row">
      <span>SMA:</span>
      <span>({strategy.params?.sma_short}, {strategy.params?.sma_long})</span>
    </div>
    <div class="param-row">
      <span>BB:</span>
      <span>({strategy.params?.bb_period}, {strategy.params?.bb_std})</span>
    </div>
  </div>
</div>
