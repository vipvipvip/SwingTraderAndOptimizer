# STEP 1 -- smoke test. If this shows a label on your chart, studies load fine and the
# problem is inside the real study. If it shows nothing, the study is not being applied.
declare upper;
AddLabel(yes, "jerk test OK  close=" + AsText(Round(close, 2)), Color.GREEN);
