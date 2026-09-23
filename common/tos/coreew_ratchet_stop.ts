# Ratchet-ATR stop — matches the CoreEW monotone weekly ratchet gate (variant B)
# IMPORTANT: set chart aggregation to WEEKLY (the gate is weekly-only).
# Mirrors the live gate exactly:
#   - scanner ATR = SIMPLE mean of True Range over 14 weeks (compute_indicators
#     uses tr.rolling(14).mean(), NOT TOS's Wilder-smoothed ATR())
#   - peak = highest SETTLED weekly close since entry
#   - stop = Max(stop, peak - mult*ATR), monotone (reset=False): re-entry only
#     above the OLD stop (stop never resets on re-entry)
#   - the in-progress week never moves peak/stop (its bar is overridden with
#     last-completed-week state), matching the gate's date < this-week-Monday
#     settled-bar filter
declare upper;

input mult          = 2.0;   # match COREEW_GATE_MULT
input atrLength     = 14;    # match scanner ATR_PERIOD
input startBarsBack = 0;     # 0 = whole chart; N = track/plot from N bars ago

def isLast = BarNumber() == HighestAll(BarNumber());

# Scanner ATR: True Range -> SIMPLE 14-week mean (atr_stop = close - 2*ATR)
def tr  = Max(high - low, Max(AbsValue(high - close[1]), AbsValue(low - close[1])));
def atr = if IsNaN(Average(tr, atrLength)) then 0 else Average(tr, atrLength);

# Monotone weekly-ratchet state machine (variant B, reset=False), evaluated on
# each week's own settled data.
def rawLong;
def rawEntries;
def rawPeak;
def rawStop;
if atr <= 0 {
    rawLong    = rawLong[1];
    rawEntries = rawEntries[1];
    rawPeak    = rawPeak[1];
    rawStop    = rawStop[1];
} else if !rawLong[1] and rawEntries[1] == 0 {
    # first gauge: enter, anchor peak/stop at this week's close
    rawLong    = 1;
    rawEntries = 1;
    rawPeak    = close;
    rawStop    = close - mult * atr;
} else if rawLong[1] {
    # while long: ratchet peak/stop up, exit on settled weekly close <= stop
    rawPeak    = Max(rawPeak[1], close);
    rawStop    = Max(rawStop[1], rawPeak - mult * atr);
    rawLong    = if close <= rawStop then 0 else 1;
    rawEntries = rawEntries[1];
} else {
    # flat: re-enter only when close climbs back above the OLD stop (monotone,
    # no ratchet reset) — peak re-anchors, stop stays unchanged
    rawLong    = if close > rawStop[1] then 1 else 0;
    rawPeak    = if rawLong then close else rawPeak[1];
    rawStop    = rawStop[1];
    rawEntries = if rawLong then rawEntries[1] + 1 else rawEntries[1];
}

# Display state: freeze the current (in-progress) forming week onto the last
# completed week's state so partial data never advances peak/stop/entries.
def long    = if isLast then rawLong[1]    else rawLong;
def entries = if isLast then rawEntries[1] else rawEntries;
def peak    = if isLast then rawPeak[1]    else rawPeak;
def stop    = if isLast then rawStop[1]    else rawStop;

def on = BarNumber() >= (HighestAll(BarNumber()) - startBarsBack);

plot RatchetStop = if on then stop else Double.NaN;
RatchetStop.SetStyle(Curve.LONG_DASH);
RatchetStop.SetDefaultColor(Color.RED);
RatchetStop.SetLineWeight(2);

# Axis labels (value frozen to the last SETTLED week)
AddLabel(on, "Ratchet " + AsDollars(stop), Color.RED);
AddLabel(on and long, "LONG", Color.GREEN);
AddLabel(on and !long and entries > 0, "FLAT (re-entry > " + AsDollars(stop) + ")", Color.RED);
# live (in-progress week) price warning — gate only exits on SETTLED close <= stop
AddLabel(on and close < stop, "BELOW STOP (intraweek)", Color.RED);