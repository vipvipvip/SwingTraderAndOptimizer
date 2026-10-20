# DRAWDOWN / TROUGH / BASE (weekly) -- any ticker. LOAD ON A WEEKLY CHART.
#
# Scale-free and walk-forward (no price-unit thresholds). Mirrors the weekly prototype
# that gave sensible phases on MRNA / ZS / CAT.
#   peak   = highest close in the last `memory` weeks (stale peaks age out)
#   low    = lowest close since that peak
#   DRAWDOWN significant when  ln(peak/low) / (sigma*sqrt(weeks peak->low)) >= zCrit
#          (deeper than a random walk with this stock's own volatility at the 95% level)
#   TROUGH CONFIRMED when drawdown is significant AND price rebounded off the low by more
#          than noise:  ln(close/low) / (sigma*sqrt(weeks since low)) >= zCrit.
#          Confirmation is LATER than the actual low (no lookahead); the bubble says how many
#          weeks later. Then locked as BASE until close < locked low, new peak, or low ages out.
#
#   red background    significant drawdown, no trough yet
#   blue background   BASE (trough confirmed and holding)
#   yellow dot        trough confirmed
#   gray dashed line  rolling peak
#
# The labels print the raw numbers (weeks since peak/low, depth z, rebound z) so a blank
# chart can be diagnosed.
declare upper;

input memory = 52;
input sigLen = 26;
input zCrit = 1.645;
input showBackground = yes;

def r = Log(close / close[1]);
def sig = StDev(r, sigLen);

def pk = Highest(close, memory);
def nPk = fold iP = 0 to memory with accP = Double.NaN do
    if IsNaN(accP) and GetValue(close, iP, memory) == pk then iP else accP;

# lowest close since the peak (fold: window length must be constant in ToS)
def lo = fold iLo = 0 to memory with accLo = Double.POSITIVE_INFINITY do
    if iLo <= nPk and !IsNaN(GetValue(close, iLo, memory)) then Min(accLo, GetValue(close, iLo, memory)) else accLo;
def nLo = fold iN = 0 to memory with accN = Double.NaN do
    if IsNaN(accN) and iN <= nPk and GetValue(close, iN, memory) == lo then iN else accN;
def nAt = nPk - nLo;

def ddZ = if nPk > 0 and sig > 0 then Log(pk / lo) / (sig * Sqrt(Max(nAt, 1))) else 0;
def dd = ddZ >= zCrit;
def rbZ = if sig > 0 then Log(close / lo) / (sig * Sqrt(Max(nLo, 1))) else 0;
def tCond = dd and nLo >= 1 and rbZ >= zCrit;

rec lockLow = if IsNaN(lockLow[1]) or lockLow[1] == 0
    then (if tCond then lo else Double.NaN)
    else (if close < lockLow[1] or close >= pk or lockLow[1] < Lowest(close, memory)
          then Double.NaN else lockLow[1]);
def inBase = !IsNaN(lockLow);
def confirmed = inBase and !inBase[1];

plot Peak = pk;
Peak.SetDefaultColor(Color.GRAY);

plot TroughConf = if confirmed then close else Double.NaN;
TroughConf.SetPaintingStrategy(PaintingStrategy.POINTS);
TroughConf.SetDefaultColor(Color.YELLOW);
TroughConf.SetLineWeight(5);

AddChartBubble(confirmed, close, "TROUGH low " + AsText(Round(lo, 2)) + " (" + AsText(nLo) + "w ago)", Color.YELLOW, no);

AssignBackgroundColor(if !showBackground then Color.CURRENT
    else if inBase then CreateColor(20, 40, 90)
    else if dd then CreateColor(90, 25, 25)
    else Color.CURRENT);

AddLabel(yes, if inBase then "BASE (locked @ " + AsText(Round(lockLow, 2)) + ")" else if dd then "DRAWDOWN (no trough yet)" else "no drawdown", if inBase then Color.CYAN else if dd then Color.RED else Color.GRAY);
AddLabel(yes, "off peak " + AsText(Round((close / pk - 1) * 100, 0)) + "%  ddZ=" + AsText(Round(ddZ, 1)) + "  rbZ=" + AsText(Round(rbZ, 1)), Color.GRAY);
AddLabel(yes, "wks since peak=" + AsText(nPk) + " low=" + AsText(nLo) + "  lo=" + AsText(Round(lo, 2)), Color.GRAY);
