---
name: etf-ytd-allocation
description: Turn a screenshot of a largest-ETFs table (ticker plus YTD %) into a classified ETF CSV and a return-weighted equity allocation CSV (versions A and B plus a combined final version), building the fund list fresh from the image each time.
---

# ETF YTD allocation from a screenshot

**Input:** a screenshot of an ETF performance table, such as WSJ/Barron's "Largest 100 exchange-traded funds" (columns ETF, Symbol, Closing Price, Chg %, YTD %).

**Output:** three CSVs: `etf_classified.csv`, `equity_allocation.csv` (versions A and B) and `equity_allocation_combined.csv` (the final output). Send all three to the user, and also save them to the attached Project if there is one.

**Never assume the fund list:** build it from the image every time. The set of funds changes between snapshots, so there is no stored list to rely on.

## Step 1: Extract every row from the image, then verify by zooming in
1. Note the date shown on the table.
2. Transcribe every row: the **Symbol**, the **ETF name as printed** (usually abbreviated), and the **YTD (%)**. Count the rows and make sure the count matches what the table claims (for example 100).
3. Always verify, because small digits and minus signs are easy to misread. In the first run of this workflow, about 30 of 100 YTD values and one ticker were wrong on the first pass. Crop the image into quadrants, enlarge each one 3x, and Read each crop. Re-check every Symbol and YTD, especially minus signs. Use more crops if the table is long.
   ```python
   from PIL import Image
   im=Image.open(PATH); w,h=im.size
   for i,(a,b) in enumerate([(0,.5),(.5,1)]):
     for j,(x0,x1) in enumerate([(0,.5),(.5,1)]):
       c=im.crop((int(x0*w),int(a*h),int(x1*w),int(b*h))); c.resize((c.width*3,c.height*3)).save(f"crop{j}{i}.png")
   ```

## Step 2: Look up and classify each fund
For every ticker, determine its full official name and the fields below.
- **When to look it up:** if you are not certain what a ticker is, run a web search before classifying it. This applies to new launches, renamed tickers, and active or niche funds. The issuer's fund page is the best source. Do not guess from the abbreviated name alone.
- **Use the printed name as a cross-check:** for example, "VangdMstarGrw" printed next to VUG. If the printed name and the ticker disagree, re-read the ticker in the zoomed crop.
- **Batch the searches:** run lookups for several unknown tickers in parallel.

The fields:

| Field | Allowed values | Rules |
|---|---|---|
| AssetClass | Equity, Bond, Commodity, Crypto, Leveraged, Other | **Leveraged** means any 2x/3x/inverse/daily-reset fund (ProShares Ultra/UltraPro/Short, Direxion Daily, "Bull/Bear 3X", T-Rex 2X, etc.). It always takes priority, so a 3x Nasdaq fund is Leveraged, not Equity. Gold, silver and broad-commodity trusts are **Commodity**. Bitcoin and ether funds are **Crypto**. Use **Other** for multi-asset, alternatives or anything that does not fit. |
| MarketCap (equity) | Large, Mid, Small, Total Market | Use **Total Market** for multi-cap or all-cap funds (VTI, VXUS, VT, VEA, IEFA, IEMG). Use **Large** for large+mid index funds (S&P 500, Russell 1000, EFA, EEM, ACWI, VEU) and for single-sector funds, which are large-cap weighted. Use **Mid** for mid-cap and extended-market funds, and **Small** for small-cap funds. |
| Style (equity) | Growth, Value, Blend | Follow the fund's index or Morningstar category. Dividend and covered-call income funds are usually **Value**, unless they are clearly blend (for example VIG) or Nasdaq-based (for example JEPQ, which is **Growth**). |
| Sector (equity) | Broad Market, Broad Market (Dividend), Tech-Heavy (Nasdaq-100), or a sector name | Use a sector name for single-sector funds: Technology, Technology - Semiconductors, Energy, Financials, Health Care, Industrials, Real Estate, Utilities, Consumer Staples, Consumer Discretionary, Communication Services, Materials. Use one consistent spelling. |
| Region (equity and bond) | US, Developed ex-US, Emerging Markets, Europe, Global ex-US, Global, or a single country name | Use a single country name (for example Japan or India) for country-specific funds. |
| Duration (bond) | Ultra-Short, Short, Intermediate, Long-Intermediate, Long | **Ultra-Short** means T-bills, 0-3 month, floating-rate CLO, or ultra-short funds. **Short** means 1-3 or 1-5 year funds. **Intermediate** means aggregate funds, 3-10 year funds, and most munis. **Long-Intermediate** means an effective duration of about 8 years or more, such as long investment-grade corporates. **Long** means 20+ year funds. |

Write `classified.csv` with the columns `Ticker,Name,YTD,AssetClass,MarketCap,Style,Sector,Region,Duration`, one row per fund in the image, using the full official names. Leave fields that don't apply blank.

## Step 3: Run the script
Save the script at the end of this skill as `allocate.py` and run `python3 allocate.py classified.csv .`

The script first validates the file: duplicate tickers, missing YTD values, equity funds without a market cap or sector, and bond funds without a duration all stop it with an error. Fix the file and re-run.

It then applies these rules:
1. **Removals:** keep only Equity and Bond funds. Leveraged, Commodity, Crypto and Other funds are removed and listed.
2. **Categories:** equity funds are grouped by MarketCap, with Multi-Cap counted as Total Market. Bond funds are grouped by Duration.
3. **Ranking:** rank every fund by YTD within its category.
4. **Category weights (equity only, summing to 100% of equity):** each category's weight is proportional to its median YTD. A negative median counts as 0. If every median is 0 or below, the categories are weighted equally.
5. **ETF picks:** within each category, take the top 2 ETFs by YTD (ties broken alphabetically). Split the category's weight between them in proportion to their YTD.
   - **Version A** picks from all funds.
   - **Version B** excludes single-sector funds, so it picks only Broad Market and Broad Market (Dividend) funds.
6. **Combined (the final output):** Mid, Small and Total Market use the picks above (A and B are normally identical there). Large uses the union of the A and B Large picks, with the Large category weight split across them in proportion to YTD. Category weights and the YTD-proportional split are unchanged. Written to `equity_allocation_combined.csv`; the script prints the combined picks as a comma-delimited list on its last line.

## Step 4: Report
Send all three CSVs. Keep the reply short, and cover:
- the table date and how many funds were read;
- which funds were removed and why;
- any funds you looked up, and any classification you were unsure about;
- a table of category weights with the picks for A, B and the combined version;
- any sector bets that version A put into a category;
- near-duplicate picks (for example IWR and VO);
- that this is a rules-based output, not investment advice;
- **last line of the reply:** the combined picks as a comma-delimited list of tickers (e.g. `SOXX,XLE,SCHD,IWD,...`), taken from the script's last output line.

## allocate.py
```python
"""Usage: python3 allocate.py classified.csv OUTDIR
classified.csv columns: Ticker,Name,YTD,AssetClass,MarketCap,Style,Sector,Region,Duration
  YTD in percent (e.g. 12.4 or -3.1). AssetClass: Equity|Bond|Commodity|Crypto|Leveraged|Other
Writes OUTDIR/etf_classified.csv, equity_allocation.csv and equity_allocation_combined.csv
"""
import sys, pandas as pd

src, out = sys.argv[1], sys.argv[2]
d = pd.read_csv(src)
for c in ["MarketCap", "Style", "Sector", "Region", "Duration"]:
    d[c] = d[c].fillna("")
d["Ticker"] = d.Ticker.str.strip().str.upper()

# validation
problems = []
if d.Ticker.duplicated().any(): problems.append(f"duplicate tickers: {d[d.Ticker.duplicated()].Ticker.tolist()}")
if d.YTD.isna().any(): problems.append(f"missing YTD: {d[d.YTD.isna()].Ticker.tolist()}")
eq = d.AssetClass == "Equity"; bd = d.AssetClass == "Bond"
bad = d[eq & ~d.MarketCap.isin(["Large", "Mid", "Small", "Total Market", "Multi-Cap"])].Ticker.tolist()
if bad: problems.append(f"equity without valid MarketCap: {bad}")
bad = d[eq & (d.Sector == "")].Ticker.tolist()
if bad: problems.append(f"equity without Sector: {bad}")
bad = d[bd & (d.Duration == "")].Ticker.tolist()
if bad: problems.append(f"bond without Duration: {bad}")
if problems: sys.exit("Fix classified.csv first:\n- " + "\n- ".join(problems))

removed = d[~d.AssetClass.isin(["Equity", "Bond"])]
d = d[d.AssetClass.isin(["Equity", "Bond"])].copy()
d["MarketCap"] = d.MarketCap.replace({"Multi-Cap": "Total Market"})
d["Category"] = d.apply(lambda s: s.MarketCap if s.AssetClass == "Equity" else s.Duration, axis=1)
d["RankInCategory"] = d.groupby(["AssetClass", "Category"]).YTD.rank(ascending=False, method="min").astype(int)
d["CategoryMedianYTD"] = d.groupby(["AssetClass", "Category"]).YTD.transform("median").round(1)
d.sort_values(["AssetClass", "Category", "RankInCategory"], ascending=[False, True, True]).to_csv(
    f"{out}/etf_classified.csv", index=False)

e = d[d.AssetClass == "Equity"]
cats = [c for c in ["Large", "Mid", "Small", "Total Market"] if c in set(e.Category)]
med = e.groupby("Category").YTD.median().reindex(cats)
pos = med.clip(lower=0)
cw = pos / pos.sum() if pos.sum() > 0 else pd.Series(1 / len(cats), index=cats)

def weights(vals, total):
    v = vals.clip(lower=0)
    return (v / v.sum() * total) if v.sum() > 0 else pd.Series(total / len(vals), index=vals.index)

broad = {"Broad Market", "Broad Market (Dividend)"}
rows = []
for tag, pool in [("A: Top 2 per category (all funds)", e),
                  ("B: Sector funds excluded", e[e.Sector.isin(broad)])]:
    for c in cats:
        top = pool[pool.Category == c].sort_values(["YTD", "Ticker"], ascending=[False, True]).head(2)
        if top.empty:
            continue
        w = weights(top.YTD, cw[c] * 100)
        for (_, s), wi in zip(top.iterrows(), w):
            rows.append(dict(Version=tag, Category=c, CategoryMedianYTD=round(med[c], 1),
                             CategoryWeightPct=round(cw[c] * 100, 1), Ticker=s.Ticker, Name=s.Name,
                             Sector=s.Sector, YTD=s.YTD, ETFWeightPct=round(wi, 1)))
o = pd.DataFrame(rows)
o.to_csv(f"{out}/equity_allocation.csv", index=False)

# Combined: Large = union of A and B picks (category weight split by YTD); other categories as in A
a = o[o.Version.str.startswith("A")]; b = o[o.Version.str.startswith("B")]
lg = pd.concat([a[a.Category == "Large"], b[b.Category == "Large"]]).drop_duplicates("Ticker").copy()
if not lg.empty:
    lg["ETFWeightPct"] = (weights(lg.YTD, lg.CategoryWeightPct.iloc[0])).round(1)
comb = pd.concat([lg, a[a.Category != "Large"]])
comb["Version"] = "Combined (Large = A+B picks)"
comb.to_csv(f"{out}/equity_allocation_combined.csv", index=False)
print(o.drop(columns=["Name"]).to_string(index=False))
print(f"\nRemoved {len(removed)}: " + ", ".join(f"{t} ({a})" for t, a in zip(removed.Ticker, removed.AssetClass)))
print(f"Kept {len(d)} funds ({(d.AssetClass=='Equity').sum()} equity, {(d.AssetClass=='Bond').sum()} bond)")
print(",".join(comb.Ticker))  # last line: combined picks
```
