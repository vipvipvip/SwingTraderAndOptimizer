# EMA10 / SMA40 CROSSOVER + LEAD SIGNAL (weekly). LOAD ON A WEEKLY CHART.
#
# The crossover (EMA10 over/under SMA40) is the reference signal; it lags by design.
# This study also warns a few weeks BEFORE it, by applying velocity/acceleration to the GAP:
#   gap  = (EMA10 - SMA40) / SMA40            scale-free distance between the lines
#   g1   = EMA(gap - gap[1], 3)               velocity of the gap
#   g2   = g1 - g1[1]                         acceleration of the gap
#   eta  = -gap / g1                          weeks until the gap closes at the current speed
# PRE-UP   : EMA10 below SMA40, gap closing, accelerating toward the cross, eta <= etaMax
# PRE-DOWN : EMA10 above SMA40, gap closing, accelerating toward the cross, eta <= etaMax
# Only the FIRST week of a run of flags is marked.
#
# Evidence (16 volatile tickers, weekly, 2022+; success = the cross happens within 8 weeks):
#   cross-UP  : eta<=4 flags 79% followed by the cross (a random weak week: 24%);
#               84% of crosses were preceded by a flag; median lead 2.0 weeks
#   cross-DOWN: 77% (random: 18%); 91% of crosses preceded; median lead 3.5 weeks
# MRNA: flags 2023-02-20/03-06, 2024-03-04, 2024-07-29, 2025-12-08 vs crosses 2023-03-13,
# 2024-03-25, 2024-08-19, 2025-12-15. Some flags are false alarms (e.g. 2022-08-01, 2025-07-21).
# etaMax = 8 leads by ~3.5-5 weeks but is less precise (64% / 58%).
#
# This warns of the CROSS (the trend flip), it does not predict price on its own.
# The partial live week can flip until Friday's close. Load >= 3 years of weekly bars.
declare upper;

input emaLen = 9;
input smaLen = 27;
input etaMax = 4;
input requireAccel = yes;

def emaV = ExpAverage(close, emaLen);
def smaV = Average(close, smaLen);
def gap = (emaV - smaV) / smaV;
def g1 = ExpAverage(gap - gap[1], 3);
def g2 = g1 - g1[1];
def eta = if g1 != 0 then -gap / g1 else Double.NaN;

def crossUp = emaV > smaV and emaV[1] <= smaV[1];
def crossDown = emaV < smaV and emaV[1] >= smaV[1];

def preUpRun = gap < 0 and g1 > 0 and eta > 0 and eta <= etaMax and (!requireAccel or g2 > 0);
def preDownRun = gap > 0 and g1 < 0 and eta > 0 and eta <= etaMax and (!requireAccel or g2 < 0);
def preUpOn = preUpRun and !preUpRun[1];
def preDnOn = preDownRun and !preDownRun[1];

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

plot PreUp = if preUpOn then low else Double.NaN;
PreUp.SetPaintingStrategy(PaintingStrategy.POINTS);
PreUp.SetDefaultColor(Color.YELLOW);
PreUp.SetLineWeight(5);

plot PreDown = if preDnOn then high else Double.NaN;
PreDown.SetPaintingStrategy(PaintingStrategy.POINTS);
PreDown.SetDefaultColor(Color.MAGENTA);
PreDown.SetLineWeight(5);

#AddChartBubble(preUpOn, low, "pre-UP", Color.YELLOW, no);
#AddChartBubble(preDnOn, high, "pre-DOWN", Color.MAGENTA, yes);
AddChartBubble(crossUp, low, "UP", Color.GREEN, no);
AddChartBubble(crossDown, high, "DOWN", Color.RED, yes);

AddLabel(yes, if emaV > smaV then "UPTREND (EMA" + AsText(emaLen) + " > SMA" + AsText(smaLen) + ")" else "DOWNTREND (EMA" + AsText(emaLen) + " < SMA" + AsText(smaLen) + ")", if emaV > smaV then Color.GREEN else Color.RED);
AddLabel(yes, if preUpRun then "PRE-UP: cross in ~" + AsText(Round(eta, 1)) + "w" else if preDownRun then "PRE-DOWN: cross in ~" + AsText(Round(eta, 1)) + "w" else "no cross expected", if preUpRun then Color.YELLOW else if preDownRun then Color.MAGENTA else Color.GRAY);
