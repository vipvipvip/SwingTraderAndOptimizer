# EMA10 / SMA40 CROSSOVER (weekly) -- trend flips, any ticker. LOAD ON A WEEKLY CHART.
#
# Same pairing as the MTF engine (EMA=10, SMA=40), evaluated on weekly closes.
#   green up-arrow   : EMA10 crosses ABOVE SMA40  -> uptrend begins
#   red down-arrow   : EMA10 crosses BELOW SMA40  -> drawdown / downtrend begins
# On MRNA weekly these land exactly on 2023-03-13 (down), 2024-03-25 (up),
# 2024-08-19 (down), 2025-12-15 (up).
#
# The cross is only confirmed at the weekly close; the live (partial) week can flip until
# Friday. SMA40 needs 40 bars, so load at least ~3 years of weekly bars (5 is better).
declare upper;

input emaLen = 10;
input smaLen = 40;

def emaV = ExpAverage(close, emaLen);
def smaV = Average(close, smaLen);

def crossUp = emaV > smaV and emaV[1] <= smaV[1];
def crossDown = emaV < smaV and emaV[1] >= smaV[1];

plot EMAline = emaV;
EMAline.SetDefaultColor(Color.ORANGE);
plot SMAline = smaV;
SMAline.SetDefaultColor(Color.CYAN);

plot UpCross = if crossUp then low else Double.NaN;
UpCross.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
UpCross.SetDefaultColor(Color.GREEN);
UpCross.SetLineWeight(5);

plot DownCross = if crossDown then high else Double.NaN;
DownCross.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
DownCross.SetDefaultColor(Color.RED);
DownCross.SetLineWeight(5);

AddChartBubble(crossUp, low, "UP", Color.GREEN, no);
AddChartBubble(crossDown, high, "DOWN", Color.RED, yes);

AddLabel(yes, if emaV > smaV then "UPTREND (EMA" + AsText(emaLen) + " > SMA" + AsText(smaLen) + ")" else "DOWNTREND (EMA" + AsText(emaLen) + " < SMA" + AsText(smaLen) + ")", if emaV > smaV then Color.GREEN else Color.RED);
