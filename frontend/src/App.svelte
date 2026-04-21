<script>
  import { onMount } from 'svelte'
  import AccountBalance from './lib/components/AccountBalance.svelte'
  import StrategyCard from './lib/components/StrategyCard.svelte'
  import EquityCurveChart from './lib/components/EquityCurveChart.svelte'
  import LivePositionsPanel from './lib/components/LivePositionsPanel.svelte'
  import PnlTable from './lib/components/PnlTable.svelte'
  import TradesHistoryTable from './lib/components/TradesHistoryTable.svelte'

  let strategies = []
  let loading = true
  let error = ''
  let selectedSymbol = 'SPY'
  let optimizerRunning = false
  let tradesRunning = false
  let optimizerMessage = ''
  let tradesMessage = ''

  async function triggerOptimizer() {
    optimizerRunning = true
    optimizerMessage = 'Running optimizer...'
    try {
      const res = await fetch('/api/v1/admin/optimize/trigger', { method: 'POST' })
      const data = await res.json()
      optimizerMessage = res.ok ? '✓ Optimizer completed' : `✗ Error: ${data.error}`
    } catch (e) {
      optimizerMessage = `✗ Error: ${e instanceof Error ? e.message : 'Unknown error'}`
    } finally {
      optimizerRunning = false
      setTimeout(() => optimizerMessage = '', 3000)
    }
  }

  async function triggerTrades() {
    tradesRunning = true
    tradesMessage = 'Executing trades...'
    try {
      const res = await fetch('/api/v1/admin/trades/trigger', { method: 'POST' })
      const data = await res.json()
      tradesMessage = res.ok ? '✓ Trade executor completed' : `✗ Error: ${data.error}`
    } catch (e) {
      tradesMessage = `✗ Error: ${e instanceof Error ? e.message : 'Unknown error'}`
    } finally {
      tradesRunning = false
      setTimeout(() => tradesMessage = '', 3000)
    }
  }

  onMount(async () => {
    try {
      const res = await fetch('/api/v1/strategies')
      if (!res.ok) throw new Error('Failed to load strategies')
      strategies = await res.json()
      if (strategies.length > 0) {
        selectedSymbol = strategies[0].symbol
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Unknown error'
    } finally {
      loading = false
    }
  })
</script>

<style>
  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    margin: 0;
    padding: 16px;
    background: #f5f5f5;
  }

  .container {
    max-width: 1400px;
    margin: 0 auto;
  }

  .header {
    margin-bottom: 32px;
  }

  .header h1 {
    margin: 0 0 8px 0;
    font-size: 32px;
    color: #333;
  }

  .header p {
    margin: 0;
    color: #666;
  }

  .error {
    background: #fee;
    color: #c33;
    padding: 16px;
    border-radius: 4px;
    margin-bottom: 16px;
  }

  .loading {
    text-align: center;
    padding: 32px;
    color: #666;
  }

  .dashboard {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .top-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }

  .strategies-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
  }

  .chart-section {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }

  .chart-section h2 {
    margin: 0 0 16px 0;
    font-size: 18px;
    color: #333;
  }

  .control-panel {
    display: flex;
    gap: 24px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }

  .control-buttons {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .control-btn {
    padding: 12px 20px;
    font-size: 14px;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }

  .optimizer-btn {
    background: #4f46e5;
    color: white;
  }

  .optimizer-btn:hover:not(:disabled) {
    background: #4338ca;
    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3);
  }

  .trades-btn {
    background: #059669;
    color: white;
  }

  .trades-btn:hover:not(:disabled) {
    background: #047857;
    box-shadow: 0 4px 12px rgba(5, 150, 105, 0.3);
  }

  .control-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .status-message {
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 4px;
    background: #dcfce7;
    color: #166534;
  }

  .status-message.error {
    background: #fee2e2;
    color: #991b1b;
  }

  @media (max-width: 768px) {
    .top-row {
      grid-template-columns: 1fr;
    }

    .control-panel {
      flex-direction: column;
      gap: 16px;
    }

    .control-buttons {
      width: 100%;
    }
  }
</style>

<div class="container">
  <div class="header">
    <h1>Trading Dashboard</h1>
    <p>Live trading with SPY, QQQ, IWM</p>
  </div>

  {#if error}
    <div class="error">Error: {error}</div>
  {/if}

  {#if loading}
    <div class="loading">Loading...</div>
  {:else}
    <div class="dashboard">
      <div class="control-panel">
        <div class="control-buttons">
          <button on:click={triggerOptimizer} disabled={optimizerRunning} class="control-btn optimizer-btn">
            {optimizerRunning ? 'Running...' : '⚙️ Trigger Optimizer'}
          </button>
          {#if optimizerMessage}
            <div class="status-message" class:error={optimizerMessage.startsWith('✗')}>
              {optimizerMessage}
            </div>
          {/if}
        </div>
        <div class="control-buttons">
          <button on:click={triggerTrades} disabled={tradesRunning} class="control-btn trades-btn">
            {tradesRunning ? 'Executing...' : '📈 Execute Trades'}
          </button>
          {#if tradesMessage}
            <div class="status-message" class:error={tradesMessage.startsWith('✗')}>
              {tradesMessage}
            </div>
          {/if}
        </div>
      </div>

      <div class="top-row">
        <AccountBalance />
        <div style="background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
          <h3 style="margin: 0 0 16px 0;">Next Trade Execution</h3>
          <p style="margin: 0 0 8px 0; color: #666;">Monday 9:35 AM ET</p>
          <p style="margin: 0; font-size: 12px; color: #999;">Market opens at 9:30 AM ET</p>
        </div>
      </div>

      <div>
        <h2 style="margin: 0 0 16px 0; color: #333;">Strategies</h2>
        <div class="strategies-row">
          {#each strategies as strategy (strategy.id)}
            <StrategyCard {strategy} onClick={() => selectedSymbol = strategy.symbol} />
          {/each}
        </div>
      </div>

      {#if selectedSymbol}
        <div class="chart-section">
          <h2>Equity Curve - {selectedSymbol}</h2>
          <EquityCurveChart symbol={selectedSymbol} />
        </div>
      {/if}

      <div class="chart-section">
        <h2>Live Positions</h2>
        <LivePositionsPanel />
      </div>

      <div class="chart-section">
        <h2>P&L Summary</h2>
        <PnlTable />
      </div>

      <div class="chart-section">
        <h2>Trade History</h2>
        <TradesHistoryTable />
      </div>
    </div>
  {/if}
</div>
