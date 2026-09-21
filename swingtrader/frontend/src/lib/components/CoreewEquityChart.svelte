<script>
  import { onMount } from 'svelte'
  import { apiFetch } from '../api'
  import { Chart, registerables } from 'chart.js'

  Chart.register(...registerables)

  let canvas
  let chart = null
  let loading = true
  let error = ''
  let hasData = false
  let meta = null

  const COLORS = {
    portfolio: '#1f78b4',
    QQQ: '#e6194b',
    VTI: '#3cb44b',
    VTV: '#f58231',
  }

  async function loadChart() {
    loading = true
    try {
      const data = await apiFetch('/strategies/coreew-equity', {}, 30000)
      const labels = data.dates?.map((d) => new Date(d).toLocaleDateString())
      hasData = !!(data.portfolio?.length || (data.symbols && data.symbols.QQQ?.length))

      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx || !hasData) return

      const datasets = [
        { label: 'Portfolio (EW trio)', data: data.portfolio, borderColor: COLORS.portfolio },
        ...Object.entries(data.symbols || {}).map(([sym, arr]) => ({
          label: `${sym} (isolated)`,
          data: arr,
          borderColor: COLORS[sym],
        })),
      ].filter((ds) => ds.data?.length)

      const chartData = { labels, datasets }
      meta = {
        window: `${data.window_start} → ${data.window_end}`,
        mult: data.mult,
        returnPct: data.portfolio?.length
          ? ((data.portfolio[data.portfolio.length - 1] / 100000 - 1) * 100).toFixed(1)
          : null,
      }

      if (chart) {
        chart.data.labels = chartData.labels
        chart.data.datasets = chartData.datasets.map((d) => ({
          ...d,
          borderDash: [5, 5],
          fill: false,
          tension: 0.1,
        }))
        chart.update('none')
      } else {
        chart = new Chart(ctx, {
          type: 'line',
          data: {
            labels,
            datasets: chartData.datasets.map((d) => ({
              ...d,
              borderDash: [5, 5],
              fill: false,
              tension: 0.1,
            })),
          },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            animation: false,
            plugins: {
              legend: { display: true, position: 'top' },
            },
            scales: {
              y: {
                beginAtZero: false,
                title: { display: true, text: 'Equity ($)' },
              },
            },
          },
        })
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load'
    } finally {
      loading = false
    }
  }

  onMount(() => {
    loadChart()
    const interval = setInterval(loadChart, 300000)

    const resizeObserver = new ResizeObserver(() => {
      if (canvas && canvas.parentElement) {
        const rect = canvas.parentElement.getBoundingClientRect()
        canvas.width = rect.width
        canvas.height = 300
      }
      if (chart) chart.resize()
    })
    if (canvas?.parentElement) {
      resizeObserver.observe(canvas.parentElement)
    }

    return () => {
      clearInterval(interval)
      resizeObserver.disconnect()
    }
  })
</script>

<style>
  .container {
    position: relative;
    width: 100%;
    height: 300px;
    display: block;
  }

  .overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #999;
    background: white;
    margin: 0;
  }

  canvas {
    width: 100% !important;
    height: 300px !important;
    max-width: 100%;
    display: block;
  }

  .meta {
    display: flex;
    gap: 16px;
    font-size: 12px;
    color: #666;
    margin-bottom: 4px;
  }
</style>

<div class="container">
  {#if meta}
    <div class="meta">
      <span>Window: {meta.window}</span>
      <span>ATR mult: {meta.mult}x</span>
      {#if meta.returnPct}
        <span style="font-weight:600;color:#1f78b4">Variant-B portfolio: +{meta.returnPct}%</span>
      {/if}
    </div>
  {/if}
  <canvas bind:this={canvas} style:visibility={hasData ? 'visible' : 'hidden'}></canvas>
  {#if loading}
    <p class="overlay">Loading...</p>
  {:else if error}
    <p class="overlay">Error: {error}</p>
  {:else if !hasData}
    <p class="overlay">No equity data available yet</p>
  {/if}
</div>