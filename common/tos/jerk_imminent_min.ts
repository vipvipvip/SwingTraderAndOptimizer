# STEP 2 -- minimal imminent: no inputs, no cooldown, no string math beyond one label.
# Same rule as weekly_experiment.py 'pasted rule'. Use on a WEEKLY chart.
declare upper;

def v = ExpAverage((close - close[4]) / 4, 4);
def a = ExpAverage(v - v[1], 4);
def j = a - a[1];
def sig = a > 0.01 and j > 0.01 and v > v[1] and j > j[1] and v < 0.6 and v > -1.0;

plot Imminent = if sig then low else Double.NaN;
Imminent.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
Imminent.SetDefaultColor(Color.MAGENTA);
Imminent.SetLineWeight(5);

AddLabel(yes, if sig then "IMMINENT" else "no imminent", if sig then Color.MAGENTA else Color.GRAY);
