# JERK IMMINENT (weekly) -- "week-of" imminent-explosion flag, any ticker. LOAD ON A WEEKLY CHART.
#
# Same rule as weekly_experiment.py 'pasted rule':
#   v = EMA((close-close[vSpan])/vSpan, smooth)   velocity
#   a = EMA(v-v[1], smooth)                       acceleration
#   j = a-a[1]                                    jerk
#   FLAG when a>aMin and j>jMin and v rising and j rising and vLo<v<vHi
# aMin/jMin/vLo/vHi are in PRICE UNITS -- retune per ticker.
#
# Noise gates: `cooldown` (default 2 weeks) shows only the first flag of back-to-back flags
# (3+ hid MRNA's 2026-05-25 hit). `emaLen` (default 0 = off) can require close above an EMA;
# it cut clutter on MRNA but also dropped true early hooks.
#
# Drawdown / trough / base is a SEPARATE study: jerk_drawdown_weekly.ts
#
# CHART RANGE: needs roughly 25+ bars of warm-up, so a 2-year weekly chart is fine
# (the first ~6 months are warm-up). Last bar is a live partial week until the Friday
# close. thinkScript EMA seeding differs slightly from pandas.
declare upper;

input vSpan = 4;
input smooth = 4;
input aMin = 0.01;
input jMin = 0.01;
input vLo = -1.0;
input vHi = 0.6;
input emaLen = 0;
input cooldown = 2;

def v = ExpAverage((close - close[vSpan]) / vSpan, smooth);
def a = ExpAverage(v - v[1], smooth);
def j = a - a[1];

def raw = a > aMin and j > jMin and v > v[1] and j > j[1] and v < vHi and v > vLo;
def emaVal = ExpAverage(close, Max(emaLen, 1));
def gated = raw and (emaLen == 0 or close > emaVal);
def gatedNum = if gated then 1 else 0;
def recent = Sum(gatedNum, Max(cooldown, 1))[1];
def sigImm = gated and (cooldown == 0 or recent == 0);

plot Imminent = if sigImm then low else Double.NaN;
Imminent.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
Imminent.SetDefaultColor(Color.MAGENTA);
Imminent.SetLineWeight(5);

AddChartBubble(sigImm, high, "IMMINENT", Color.MAGENTA, yes);

AddLabel(yes, if sigImm then "IMMINENT (this bar)" else "no imminent", if sigImm then Color.MAGENTA else Color.GRAY);
AddLabel(yes, "v=" + AsText(Round(v, 2)) + " a=" + AsText(Round(a, 3)) + " j=" + AsText(Round(j, 3)), Color.GRAY);
