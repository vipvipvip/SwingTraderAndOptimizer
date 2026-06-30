# Stats Helper — Plain‑English Guide

**Goal:** Determine whether a strategy's outperformance vs Buy‑Hold (BH) is real or just luck.

## Tests We Use

### 1. Paired t‑test (Strategy vs BH)
- **What:** For each stock, compute `strategy_return - BH_return`. Feed the 500+ differences into a t‑test.
- **Why paired?** Same stock, same time period — each stock is its own control. Pairing removes stock‑to‑stock variation (some stocks just go up more) and isolates the *strategy* effect.
- **What it answers:** "Is the average difference between the two strategies likely real, or could it be random noise?"
- **Output:** `t` (test statistic), `p` (probability). p < 0.05 → we reject "no difference" — the strategy is statistically different from BH.
- **Example:** t = 4.31, p = 0.00002 — that's a 2‑in‑100,000 chance the difference is random.

### 2. One‑sample t‑test (excess ≠ 0)
- **What:** Same math as paired t‑test, but framed as "is the excess return (strategy − BH) different from zero?"
- **What it answers:** "Is the strategy, on average, adding or destroying value vs BH?"
- **Example:** t = 4.31, p = 0.00002 → the +422% excess is not zero.

### 3. Binomial test (Does the strategy beat BH on >50% of stocks?)
- **Why?** The t‑test can be driven by a few massive winners. This checks *consistency* — does the strategy win on most stocks regardless of magnitude?
- **What it answers:** "If the strategy were no better than BH, you'd expect ~50% of stocks to win. Is our observed win rate higher than 50%?"
- **How:** Count wins (excess > 0). Calculate: "If true win rate were 50%, what's the chance of seeing ≥ X wins out of N stocks?"
- **Example:** 485/502 = 96.6%, binom p ≈ 0 → it's not just outliers, it wins on almost every stock.

### 4. Bootstrap confidence intervals
- **Why?** t‑tests assume a bell‑curve shape. Bootstrapping makes *no assumptions* — it resamples our actual data.
- **How:** Take the list of 502 excess returns. Pick 502 of them *with replacement* (some appear multiple times, some not at all). Compute the average. Repeat 10,000 times. The middle 95% of those 10,000 averages = your 95% CI.
- **What it answers:** "Given the data we have, what range of average excess is plausible?"
- **Example:** 95% CI = [+279%, +646%] → we're 95% confident the true average excess is somewhere in that range.

### 5. One‑sample t‑test on Sharpe (Sharpe > 0)
- **Why?** High returns alone don't mean the strategy is good — it could come with gut‑wrenching drawdowns. Sharpe = return ÷ risk. We need to know if it's *reliably* positive.
- **What it answers:** "If the true Sharpe were 0 (no risk‑adjusted edge), what's the chance we'd observe a Sharpe of 1.286?"
- **Example:** t = 78.9, p ≈ 0 → the Sharpe is massively positive, not a fluke.

### 6. Cohen's d (effect size)
- **Why?** With 500+ observations, t‑tests can detect *tiny* differences as "statistically significant." Cohen's d tells you *how big* the difference actually is.
- **Interpretation:**
  - d < 0.2 → negligible
  - 0.2 ≤ d < 0.5 → small
  - 0.5 ≤ d < 0.8 → medium
  - d ≥ 0.8 → large
- **What it answers:** "The edge is real, but how big is it in practical terms?"
- **Example:** d = 0.19 → the edge is consistent but there's lots of stock‑to‑stock variation (small effect).

## Cheat Sheet — What's Useful When

| You want to know... | Use... |
|---|---|
| "Is the average return difference real?" | Paired t‑test |
| "I need a range, not a single number" | Bootstrap CI |
| "Does it win consistently, or is it a few home runs?" | Binomial test |
| "Is the risk‑adjusted return real?" | Sharpe t‑test |
| "How big is the edge in practical terms?" | Cohen's d |

## Key Distinctions

| Concept | Plain English |
|---|---|
| **Statistical significance** (p < 0.05) | "Unlikely to be luck" |
| **Effect size** (Cohen's d) | "How big is the edge?" |
| **Confidence interval** | "A plausible range" |
| **Consistency** (binomial) | "Does it work most of the time?" |

A strategy can be statistically significant (p = 0.00002) but have a small effect size (d = 0.19). Both matter — significance says it's real, effect size says whether it's worth your money.
