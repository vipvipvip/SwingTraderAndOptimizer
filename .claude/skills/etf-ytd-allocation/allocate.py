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
