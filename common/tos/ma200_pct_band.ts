# MA200 percentage band — plots the upper and lower line at +/- pct of the 200
# moving average of the CURRENT chart aggregation. Works unchanged on DAILY,
# WEEKLY and HOURLY charts: every value below is derived from the chart's own
# bars, so "200MA" means 200 daily / 200 weekly / 200 hourly bars depending on
# the aggregation you load it on (there is no separate per-timeframe file).
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
# before it can be assigned inside a block).
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

def maName = if maKind == 1 then "EMA" else if maKind == 2 then "Wilder" else if maKind == 3 then "WMA" else "SMA";

def upperLine = maBase * (1 + bandPct / 100);
def lowerLine = maBase * (1 - bandPct / 100);

def on = BarNumber() >= (HighestAll(BarNumber()) - startBarsBack);

plot UpperBand = if showBand and on then upperLine else Double.NaN;
UpperBand.SetStyle(Curve.LONG_DASH);
UpperBand.SetDefaultColor(Color.GREEN);
UpperBand.SetLineWeight(2);

plot LowerBand = if showBand and on then lowerLine else Double.NaN;
LowerBand.SetStyle(Curve.LONG_DASH);
LowerBand.SetDefaultColor(Color.RED);
LowerBand.SetLineWeight(2);

plot MaLine = if showMa and on then maBase else Double.NaN;
MaLine.SetStyle(Curve.FIRM);
MaLine.SetDefaultColor(Color.WHITE);
MaLine.SetLineWeight(3);

# Axis labels (values read off the current bar)
AddLabel(showMa, maName + maLen + " " + AsDollars(maBase), Color.WHITE);
AddLabel(showBand, "U +" + bandPct + "% " + AsDollars(upperLine), Color.GREEN);
AddLabel(showBand, "L -" + bandPct + "% " + AsDollars(lowerLine), Color.RED);
