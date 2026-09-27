# CoreEG100 — the LIVE CoreEW gate, visualised on any chart.
#
# EG100 = a synthetic equal-weight index of QQQ/VTI/VTV compared against its own
# EMA(100) as a PURE crossover. LONG (all three at equity/N) while the index is
# above the EMA; all-flat when it is below. This is the gate that actually runs
# live via `trades:execute-EW-gate100` on the 5-min cron (acct #PA3GKZYLVO68),
# and it replaced the old per-leg weekly ratchet (variant S) on 2026-09-27.
#
# LOAD IT ON A DAILY CHART. The live gate decides on settled DAILY closes, so on
# a weekly or hourly chart this is a genuinely different series, not a different
# view of the same thing.
#
# How the index is built — deliberately identical to the backtest:
#   idx = cumprod(1 + mean(pct_change(QQQ), pct_change(VTI), pct_change(VTV)))
# The three RETURNS are averaged, never the prices (they live on different
# scales), and compounded into a dimensionless index seeded at 1.0 with the
# first bar's return treated as 0. The average is ewm(span=100, adjust=False),
# i.e. alpha = 2/101, seeded with the first index value — so there is no
# warm-up gap here the way a simple MA would have.
#
# ⚠ HISTORY-SENSITIVITY (read before trusting a signal off this chart) — MEASURED:
# the live gate always replays the FULL settled history in the database, whose
# first bar is 2016-01-04 (2698 bars to 2026-09-25). thinkScript seeds idx at 1.0
# on the FIRST BAR YOUR CHART LOADS, and the EMA inherits that seed, so the seed
# only matches if your chart starts on that same bar.
#   chart start 2016-01-04 -> 0 mismatches, the lines are identical to the gate
#   chart start 2016-09-16 -> 12 wrong bars, last at +0.1y
#   chart start 2017-08-04 -> 20 wrong bars, last at +0.7y
#   chart start 2019-03-11 -> 11 wrong bars, last at +1.1y
#   chart start 2025-07-22 ->  6 wrong bars, last at +0.3y
# So loading MORE history is not what makes it match — loading from the RIGHT
# bar is. On any other start, only a handful of crossovers inside roughly the
# first year of the chart differ, and everything after reconverges as the
# original seed washes out. If a crossover here contradicts a trade in the log,
# check the chart's load start before suspecting a bug.
#
# thinkScript API notes (these are the traps this script deliberately avoids):
#   - There is NO SMA()/EMA()/WSMA() function. The moving averages are:
#       Average(close, n)          = simple MA  (TOS "SMA" study)
#       ExpAverage(close, n)       = exponential MA
#       WildersAverage(close, n)   = Wilder's / RMA
#       WMA(close, n)              = weighted MA
#     "SMA" is only a NAMED PARAMETER (Average(data = close, length = 50)).
#   - Curve constants are FIRM / LONG_DASH / MEDIUM_DASH / SHORT_DASH / POINTS.
#     There is no Curve.SOLID; the solid line is Curve.FIRM.
#   - Never name anything `length` / `count` / `value` / `index` / `type` — they
#     collide with built-in functions (Length, Count, Value, Index...). The index
#     def here is named `ewIdx` for exactly that reason.
#   - Identifiers are case-insensitive: a def `inBand` and a plot `InBand`
#     collide ("Identifier Already Used").
#   - `on` is a KEYWORD (plot <data> on close), so `def on` is a parse error.
#   - A BARE `def x;` is inferred as a DOUBLE. Declare-empty-then-assign is safe
#     only for numeric defs; giving such a def a string reports "Incompatible
#     parameter" plus "Expected double". Keep string literals inline in the call.
#   - A top-level `if` STATEMENT always needs braces, whether it assigns or calls
#     AddLabel/AddBackgroundColor. Brace-free `if cond` / newline / call is
#     rejected with "Invalid statement: if".
#   - But do NOT nest one if inside another's braces: that is what produces
#     "An 'else' block expected" / "Semicolon expected" at the outer `if`. Keep
#     every if/else chain FLAT and pre-compute the extra conditions as defs,
#     exactly as the coreew_ratchet_stop-*.ts scripts do.
#   - There is no Text() function, and no C-style `a ? b : c`. Use
#     `if cond then a else b`, and `+` for string/number concatenation.
#
# Notes
#   - bandPct only DRAWS the +/- pct lines as a visual reference. The live gate
#     is a pure crossover, so LONG/CASH below follows the crossover exactly;
#     no hysteresis is applied. The band-HYSTERESIS variant is a research option
#     in the backtest and is NOT what the account trades.
#   - Everything is recomputed on the live (in-progress) bar like any indicator,
#     so the last value can drift until the bar closes. The gate only ever reads
#     settled closes, so treat the current bar as provisional.

input emaLen        = 100;  # EMA length in CHART BARS (100 daily bars on a daily chart)
input bandPct       = 3.0;  # draw +/- pct reference lines (visual only, non-live)
input showIndex     = yes;  # plot the synthetic equal-weight index
input showMa        = yes;  # plot the index EMA
input showBand      = yes;  # draw the +/- pct lines
input showBackdrop  = yes;  # shade the bars where the gate is LONG vs CASH
input startBarsBack = 0;    # 0 = whole chart; N = only show the last N bars

# --- Synthetic equal-weight QQQ/VTI/VTV index -----------------------------
# The tickers are hard-wired on purpose: close() takes a literal symbol and will
# not accept one supplied through an input. The live gate is trio-only.
def rQQQ = close("QQQ") / close("QQQ")[1] - 1;
def rVTI = close("VTI") / close("VTI")[1] - 1;
def rVTV = close("VTV") / close("VTV")[1] - 1;
def ewRet = (rQQQ + rVTI + rVTV) / 3;

# Running product, declared empty and assigned once. Referencing its own [1] is
# the standard thinkScript recursion idiom (and is why this must stay numeric).
def ewIdx;
ewIdx = if BarNumber() == 0 then 1.0 else ewIdx[1] * (1 + ewRet);

# ewm(span, adjust=False): alpha = 2/(span+1), seeded with the first index value.
def ewEma = ExpAverage(ewIdx, emaLen);

def upperLine = ewEma * (1 + bandPct / 100);
def lowerLine = ewEma * (1 - bandPct / 100);
def gapPct    = if ewEma > 0 then (ewIdx / ewEma - 1) * 100 else 0;

# The live rule, verbatim: long while the index is above its EMA. No recursion,
# no hysteresis, nothing that could drift out of step with the gate.
def isLong = if ewIdx > ewEma then 1 else 0;

def showBar = BarNumber() >= (HighestAll(BarNumber()) - startBarsBack);

# --- Plots ----------------------------------------------------------------
plot Index = if showIndex and showBar then ewIdx else Double.NaN;
Index.SetStyle(Curve.FIRM);
Index.SetDefaultColor(Color.CYAN);
Index.SetLineWeight(2);

plot Ema100 = if showMa and showBar then ewEma else Double.NaN;
Ema100.SetStyle(Curve.FIRM);
Ema100.SetDefaultColor(Color.WHITE);
Ema100.SetLineWeight(3);

plot UpperBand = if showBand and showBar then upperLine else Double.NaN;
UpperBand.SetStyle(Curve.LONG_DASH);
UpperBand.SetDefaultColor(Color.GREEN);
UpperBand.SetLineWeight(1);

plot LowerBand = if showBand and showBar then lowerLine else Double.NaN;
LowerBand.SetStyle(Curve.LONG_DASH);
LowerBand.SetDefaultColor(Color.RED);
LowerBand.SetLineWeight(1);

# The long/cash backdrop, repainted on each state change.
def flipped = isLong != isLong[1];
def turnedOn  = flipped and isLong == 1;
def turnedOff = flipped and isLong == 0;

if showBackdrop and turnedOn {
    AddBackgroundColor(Color.DARK_GREEN);
}

if showBackdrop and turnedOff {
    AddBackgroundColor(Color.DARK_RED);
}

# --- Axis labels ----------------------------------------------------------
# String literals stay inline in the call; a bare `def x;` is typed DOUBLE and
# would reject a string, and the if/else chain is what selects the wording.
if isLong == 1 {
    AddLabel(showMa, "EG100 GATE: LONG (all 3)", Color.GREEN);
} else {
    AddLabel(showMa, "EG100 GATE: CASH (all flat)", Color.RED);
}

AddLabel(showMa, "EMA" + emaLen + " crossover", Color.WHITE);
AddLabel(showIndex, "Index " + ewIdx, Color.CYAN);

if gapPct >= 0 {
    AddLabel(showMa, "+" + gapPct + "% vs EMA", Color.WHITE);
} else {
    AddLabel(showMa, gapPct + "% vs EMA", Color.WHITE);
}
