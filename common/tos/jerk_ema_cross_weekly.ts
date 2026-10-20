# EMA CROSS (weekly) -- close crossing UP through a weekly EMA. LOAD ON A WEEKLY CHART.
#
# Simple uptrend-vicinity marker. Tested against the jerk rule on 16 volatile tickers
# (2022+, weekly; "near an uptrend" = flag from 3 weeks before a >=30% up-leg's low to
# halfway through the leg; a random week scores 33%):
#   close x up EMA10 : 355 flags, 41% near an uptrend, catches 82% of up-legs
#   close x up EMA20 : 230 flags, 47% near an uptrend, catches 63% of up-legs
#   jerk rule        : 167 flags, 45% near an uptrend, catches 50% of up-legs
# => about as good as the jerk rule, far simpler, but NOT exact: roughly half of the
#    flags are whipsaws, and it fires ~2 weeks after the low (median).
#
# Default is EMA20. Set fastLen to 10 for more (and noisier) flags.
declare upper;

input emaLen = 20;
input showLine = yes;

def e = ExpAverage(close, emaLen);
def crossUp = close > e and close[1] <= e[1];

plot EMALine = if showLine then e else Double.NaN;
EMALine.SetDefaultColor(Color.ORANGE);

plot CrossUp = if crossUp then low else Double.NaN;
CrossUp.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
CrossUp.SetDefaultColor(Color.GREEN);
CrossUp.SetLineWeight(4);

AddLabel(yes, if crossUp then "CROSS UP (this bar)" else if close > e then "above EMA" + AsText(emaLen) else "below EMA" + AsText(emaLen), if crossUp then Color.GREEN else if close > e then Color.GRAY else Color.RED);
