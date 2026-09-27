# MA200 percentage band — plots the upper and lower line at +/- pct of the 200
# moving average of the CURRENT chart aggregation. Works unchanged on DAILY,
# WEEKLY and HOURLY charts: every value below is derived from the chart's own
# bars, so "200MA" means 200 daily / 200 weekly / 200 hourly bars depending on
# the aggregation you load it on (there is no separate per-timeframe file).
#
# ⚠ THIS IS RESEARCH SCAFFOLDING, NOT A LIVE STRATEGY. The live CoreEW gate is
# EG100 (synthetic QQQ/VTI/VTV index vs its own EMA100, pure crossover) — see
# `eg100_index_ema.ts`. This file stays for the MA(n) ± band family that the
# backtest compares variants against (`backtest_trio_ew.py --sma-gate/--sma-band`):
# the ±3% band beat pure crossover out of sample and lost in sample, so it is a
# documented data point, not something the account trades.
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
#   - Never name an input `length` / `count` / `value` / `index` / `type` — they
#     collide with built-in functions (Length, Count, Value, Index...).
#   - Identifiers are case-insensitive: a def `inBand` and a plot `InBand`
#     collide ("Identifier Already Used").
#   - `on` is a KEYWORD (plot <data> on close), so `def on` is a parse error.
#   - A BARE `def x;` is inferred as a DOUBLE. Declare-empty-then-assign is only
#     safe for numeric defs; giving such a def a string reports "Incompatible
#     parameter" on the literal plus "Expected double", whether the strings come
#     from a chained ternary or from a plain block. Either annotate the type
#     (`def String s = "a";`) or keep string literals inline in the call.
#   - A BRACED `if ... { }` is the ASSIGNMENT form (see the
#     coreew_ratchet_stop-*.ts scripts). A STATEMENT-level if — one wrapping
#     AddLabel calls — must be brace-free, otherwise the
#     compiler reports "An 'else' block expected" and "Semicolon expected" at
#     the `if` line.
#   - There is no Text() function. String + number concatenation with `+` is
#     valid and needs no conversion helper.
#   - There is no C-style `a ? b : c` ternary; use `if cond then a else b`.
#
# Notes
#   - maKind selects the MA base: 0 = simple (matches TOS's own MA study),
#     1 = exponential, 2 = Wilder's, 3 = weighted.
#   - Bands are recomputed on the live (in-progress) bar like any indicator, so
#     the last line value can drift until the bar closes.

input maLen         = 200;  # MA length in CHART BARS (200 = 200d/200w/200h)
input bandPct       = 3.0;  # band distance from the MA, in percent
input maKind        = 0;    # 0 = simple, 1 = exponential, 2 = Wilder's, 3 = weighted
input showMa        = yes;  # plot the base moving average
input showBand      = yes;  # plot the +/- pct lines
input startBarsBack = 0;    # 0 = whole chart; N = only plot the last N bars

# Declared with no value, then assigned in EVERY branch of the if/else chain —
# the pattern the CoreEW ratchet scripts use (a def must be declared empty
# before it can be assigned inside a block). Valid here only because every
# branch is numeric; a bare `def x;` is typed DOUBLE and would reject a string.
def maBase;
if maKind == 1 {
    maBase = ExpAverage(close, maLen);
} else if maKind == 2 {
    maBase = WildersAverage(close, maLen);
} else if maKind == 3 {
    maBase = WMA(close, maLen);
} else {
    maBase = Average(close, maLen);
}

def upperLine = maBase * (1 + bandPct / 100);
def lowerLine = maBase * (1 - bandPct / 100);

# NOT named `on` — that is a thinkScript KEYWORD (plot <data> on close), so a
# `def on` is a parse error even though the compiler only reports it once the
# earlier errors are cleared.
def showBar = BarNumber() >= (HighestAll(BarNumber()) - startBarsBack);

plot UpperBand = if showBand and showBar then upperLine else Double.NaN;
UpperBand.SetStyle(Curve.LONG_DASH);
UpperBand.SetDefaultColor(Color.GREEN);
UpperBand.SetLineWeight(2);

plot LowerBand = if showBand and showBar then lowerLine else Double.NaN;
LowerBand.SetStyle(Curve.LONG_DASH);
LowerBand.SetDefaultColor(Color.RED);
LowerBand.SetLineWeight(2);

plot MaLine = if showMa and showBar then maBase else Double.NaN;
MaLine.SetStyle(Curve.FIRM);
MaLine.SetDefaultColor(Color.WHITE);
MaLine.SetLineWeight(3);

# Axis labels (values read off the current bar).
#
# The MA name is selected with an if/else chain of AddLabel calls rather than a
# `def maName` string variable: a bare `def x;` is inferred as a DOUBLE, so a
# later `maName = "EMA";` fails with "Incompatible parameter" / "Expected
# double" no matter how it is nested. Keeping the literals inline as call
# arguments sidesteps the type question completely. `+` concatenation of a
# string literal with a number is valid (there is no Text() function).
if maKind == 1
    AddLabel(showMa, "EMA" + maLen + " " + AsDollars(maBase), Color.WHITE);
else if maKind == 2
    AddLabel(showMa, "Wilder" + maLen + " " + AsDollars(maBase), Color.WHITE);
else if maKind == 3
    AddLabel(showMa, "WMA" + maLen + " " + AsDollars(maBase), Color.WHITE);
else
    AddLabel(showMa, "SMA" + maLen + " " + AsDollars(maBase), Color.WHITE);

AddLabel(showBand, "U +" + bandPct + "% " + AsDollars(upperLine), Color.GREEN);
AddLabel(showBand, "L -" + bandPct + "% " + AsDollars(lowerLine), Color.RED);
