# LinkedIn Posts - Vibe Coding: Scaling a Trading System from 503 to 1,500 Stocks

## Post 1: When Your Database Becomes the Bottleneck - And AI Helps You Fix It
**Category: Engineering with AI | Word count: ~400**

---

I hit a wall.

My trading system's `compute_indicators.py` was taking **1 hour 47 minutes** to process 503 stocks. Every. Single. Night.

The root cause? Row-level lock contention. Ten workers hammering the same PostgreSQL table with 5,260 individual UPDATE statements per ticker. Ten workers fighting each other for the same rows. The database was spending more time waiting than computing.

I needed to expand to 1,500+ stocks. At the current pace, that would mean **5+ hours** of lock contention. Unacceptable.

So I opened my AI coding assistant and described the problem: "I need partition-aware workers that each own specific data segments, and bulk writes instead of individual UPDATEs."

What happened next was pure vibe coding.

**The Vibe Coding Session:**

I didn't write the partition DDL. I described what I needed:
- "Hash-partition the hourly table by ticker_id into 16 buckets"
- "Each worker should own specific partitions so there's zero contention"
- "Use PostgreSQL COPY to bulk update instead of individual UPDATEs"

The AI generated the partition migration SQL. I reviewed it, caught that it was missing the INCLUDE clause on the composite index (critical for index-only scans), and we iterated. The entire session felt like explaining architecture to a colleague who never gets tired and remembers every constraint you mentioned three conversations ago.

**What Actually Got Built:**

1. **Hash-partitioned `tbl_scanner_tickers_1hour`** into 16 buckets (`ticker_id % 16`)
2. **Migrated 2.8M rows** from the old table
3. **Dropped 3 redundant indexes** (saved 347 MB)
4. **Rewrote `compute_indicators.py`** with partition-aware workers + COPY bulk UPDATEs

**The Result:**

| Metric | Before | After |
|--------|--------|-------|
| Runtime | 1h 47min | **8.5 min** |
| Lock contention | Severe | **Zero** |
| Index size | 968 MB | **621 MB** |
| Partition pruning | N/A | **0.7ms per query** |

**The Vibe Coding Reality Check:**

This wasn't "AI writes perfect code." Here's what actually happened:

- The AI suggested `INSERT ... ON CONFLICT DO UPDATE` for bulk writes. I tested it. It didn't work with the partitioned table's unique constraint. We pivoted to `UPDATE ... FROM temp_table` approach. The AI adapted.
- The AI generated temp table creation with `ON COMMIT DROP`. Concurrent workers were dropping each other's temp tables. I caught this in testing, described the race condition, and we fixed it with per-worker temp table names.
- The AI forgot to cast date types between the temp table (timestamp) and target table (date). PostgreSQL silently failed to detect conflicts. I traced through the error logs, identified the type mismatch, and we added explicit casting.

**The Pattern:**

Vibe coding isn't about the AI getting it right. It's about:
1. **Describing architecture clearly** — "partition by hash, 16 workers, one per partition"
2. **Testing immediately** — run the code, see what breaks
3. **Feeding failures back** — "the ON CONFLICT isn't matching, here's the error"
4. **Iterating fast** — each cycle takes minutes, not hours

The AI handles the boilerplate (DDL, temp table creation, COPY logic). I handle the judgment (which approach fits PostgreSQL's partition model, why the type mismatch matters, when to pivot from INSERT to UPDATE).

**What I Actually Spent:**
- 30% describing what I needed
- 40% testing and catching failures
- 20% explaining failures to the AI
- 10% architectural decisions (which partition count, which bulk strategy)

**The Honest Take:**

Without vibe coding, this refactor would've taken me 2-3 days of careful PostgreSQL tuning. With it, I did it in a single afternoon. But I still needed to understand partition pruning, COPY mechanics, and transaction isolation to catch the issues the AI missed.

**The constraint isn't coding speed anymore. It's knowing what to build and catching what goes wrong.**

---

## Post 2: Expanding a Trading Universe from 503 to 1,500 Stocks — The Data Engineering Problem Nobody Talks About
**Category: Data Engineering | Word count: ~400**

---

Everyone talks about building trading algorithms. Nobody talks about the data engineering required to feed them.

I had a working system scanning 503 S&P 500 stocks. But S&P 500 is a lagging indicator — TSLA grew 757% *before* S&P inclusion. I needed to catch stocks earlier. So I expanded the universe to 1,500+ stocks using a VTI-like filter (Price > $50, non-OTC, common stocks only).

Here's the boring-but-critical work nobody tells you about:

**The Problem:**

Alpaca's free tier gives you IEX feed data. IEX captures maybe 5% of market volume. When I tried to filter 9,600 stocks by average dollar volume using IEX bars, only 97 stocks returned any volume data. The rest had bars with zero volume.

I spent an hour debugging this before realizing: **the data source itself is the bottleneck, not my code.**

**The Vibe Coding Solution:**

I described the problem to my AI assistant: "IEX feed doesn't have reliable volume data. I need a different approach."

We iterated through options:
- Yahoo Finance batch API (returned 0 quotes — API deprecated)
- Alpaca screener endpoint (404 — not available on free tier)
- Batch bar requests with smaller sizes (still sparse IEX data)

The breakthrough came from simplifying: skip volume filtering entirely. Just filter by price ($50+) and exchange (exclude OTC). The MTF scoring system naturally filters low-quality stocks — they don't generate momentum signals.

The AI generated `get_vti_universe.py`: a script that fetches all 13,000 active US equities from Alpaca's Trading API, gets latest prices via the snapshot API, and inserts qualifying stocks into `tbl_stock_tickers`.

**What I Learned About Data Engineering with AI:**

1. **AI is great at API integration** — The Alpaca Trading API, Data API, batch processing, rate limiting. The AI knew the SDK version, the correct request format, the pagination pattern. I described "get all US equities with prices above $50," and it generated working code.

2. **AI is bad at knowing when data sources fail** — The AI didn't know IEX feed has 5% volume coverage. I had to discover that, test it, and explain: "IEX doesn't work for volume. Let's use price-only filtering."

3. **The iteration loop matters** — First draft: filter by volume. Broke. Second draft: filter by price only. Worked. Each iteration took 5 minutes with AI, would've taken 30 minutes alone.

**The Numbers:**

| Metric | Before | After |
|--------|--------|-------|
| Universe | 503 (S&P 500) | **1,534 (VTI-like)** |
| New stocks added | — | **1,031** |
| Exchange breakdown | — | NYSE: 798, NASDAQ: 596, ARCA: 51 |
| Price range | $50-$477K | $50-$477K |

**The Architecture Decision:**

I initially planned to filter by "average dollar volume > $10M." But after discovering IEX's limitations, I pivoted to "price > $50" with no volume filter. Here's why this works:

- **Volume changes over time** — A stock at $8M today might be $15M next month
- **MTF scoring filters quality** — Low-volume stocks don't generate momentum signals
- **Storage is cheap** — The extra ~1,000 tickers add ~3GB to the hourly table
- **False positives are filtered** — The scoring system picks the top 10, not all 1,500

**The Vibe Coding Efficiency:**

The entire universe expansion — from Alpaca API exploration to DB insertion — took about 2 hours. Without AI, I'd estimate 6-8 hours (API documentation reading, error handling, pagination logic, ETF filtering heuristics).

The real time-saver wasn't code generation. It was **rapid prototyping**. "Try this approach" → test → "that didn't work, try this" → test → "this works." Each cycle: 3-5 minutes with AI, 15-30 minutes alone.

**The Honest Tradeoff:**

I traded thoroughness for speed. A "proper" approach would use a premium data feed with reliable volume data. My approach uses price-only filtering and relies on the scoring system to handle quality. This is fine for a paper trading system. For real money, I'd invest in better data.

**If you're building data pipelines with AI: describe the constraint, test immediately, and be ready to pivot when the data source doesn't cooperate.**

---

## Post 3: The 12x Speedup — What "Vibe Coding" Actually Looks Like for Database Optimization
**Category: Performance Engineering | Word count: ~400**

---

My trading system had a performance problem that would make any DBA cringe.

**The Problem:**

`compute_indicators.py` — the script that calculates MACD, PPO, and ATR indicators for every stock — was taking **1 hour 47 minutes** to process 503 tickers on a PostgreSQL table with 2.8M rows.

The bottleneck wasn't computation. It was **lock contention**.

10 workers × 5,260 individual UPDATE statements per ticker = 52,600 rows being updated simultaneously across the same table. PostgreSQL was spending more time managing locks than executing queries.

**The Plan:**

I needed to:
1. Partition the table so workers don't touch each other's data
2. Replace individual UPDATEs with bulk COPY operations
3. Match workers to partitions (1 worker per partition = zero contention)

**The Vibe Coding Session:**

I opened my AI assistant and said: "Rewrite compute_indicators.py with partition-aware workers. Each worker owns specific partitions. Use PostgreSQL COPY for bulk updates instead of individual UPDATEs."

The AI generated the skeleton. I reviewed it. Here's what happened:

**Round 1:** AI generated `INSERT ... ON CONFLICT DO UPDATE` with a temp table. I tested it. PostgreSQL couldn't detect conflicts — the unique constraint wasn't matching.

I traced the issue: the temp table had `date` as `timestamp`, but the target table had `date` as `date`. PostgreSQL's conflict detection failed silently.

I told the AI: "The date type mismatch is preventing conflict detection. Switch to `UPDATE ... FROM temp_table` instead."

**Round 2:** AI generated the UPDATE FROM approach. I tested it. Workers were dropping each other's temp tables (`ON COMMIT DROP`).

I told the AI: "Concurrent workers share temp table names. Use per-worker names like `_ind_w0`, `_ind_w1`."

**Round 3:** AI generated per-worker temp tables. I tested it. The COPY was writing boolean values as `True`/`False` instead of PostgreSQL's `t`/`f` format.

I told the AI: "COPY text format expects `t`/`f` for booleans, not Python's `True`/`False`."

**Round 4:** It worked.

**Four iterations. Each took 5 minutes with AI. Would've taken 30-60 minutes alone.**

**The Architecture:**

```
Worker 0 → tickers where ticker_id % 16 == 0 → Partition 0
Worker 1 → tickers where ticker_id % 16 == 1 → Partition 1
...
Worker 15 → tickers where ticker_id % 16 == 15 → Partition 15
```

Each worker:
1. Opens one DB connection
2. Bulk-loads all its tickers' data in a single query
3. Computes indicators in-memory (pandas + numpy)
4. COPYs results to a per-worker temp table
5. Runs a single `UPDATE ... FROM` to apply all changes

**The Results:**

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Hourly (532 tickers) | 1h 47min | **8.5 min** | **12x** |
| Daily (532 tickers) | ~15min | **84s** | **10x** |
| Weekly (532 tickers) | ~2min | **19.7s** | **6x** |
| Lock contention | Severe | **Zero** | — |
| Query latency | Full table scan | **0.7ms** (index-only) | — |

**What Vibe Coding Enabled:**

The AI handled the mechanical parts:
- PostgreSQL partition DDL (hash partitioning syntax)
- COPY bulk write logic (StringIO buffer, text format)
- Worker scheduling (ThreadPoolExecutor, partition assignment)
- Temp table lifecycle (create, populate, update, drop)

I handled the judgment:
- Why hash partitioning over range (even distribution, no hot spots)
- Why UPDATE FROM over INSERT ON CONFLICT (constraint compatibility)
- Why per-worker temp tables (concurrent access)
- Why boolean formatting matters (COPY text format vs Python repr)

**The Honest Assessment:**

Without vibe coding, this refactor would've been 2-3 days of careful PostgreSQL tuning, type system debugging, and concurrent programming. With it, I did it in an afternoon.

But here's what vibe coding didn't do:
- It didn't know IEX feed has 5% volume coverage (I discovered that)
- It didn't know the temp table type mismatch would silently fail conflict detection (I traced that)
- It didn't know concurrent workers would race on temp table names (I caught that)

**Vibe coding amplifies your ability to implement. It doesn't replace your ability to debug.**

The 12x speedup came from:
1. **Knowing the problem** — lock contention, not computation
2. **Knowing the solution** — partitioning + bulk writes
3. **Having a partner to implement fast** — AI handled the boilerplate
4. **Catching what went wrong** — I traced the type mismatch and concurrency bugs

**If you're doing performance engineering with AI: describe the constraint, test every iteration, and be the one who catches what the AI misses. That's where the 12x comes from.**

---

*Follow for more on building trading systems, database optimization, and what vibe coding actually looks like in practice.*
