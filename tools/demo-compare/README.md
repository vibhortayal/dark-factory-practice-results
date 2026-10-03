# Demo VM comparison script

`compare.sh` compares the apps built by Run 2, Run 3 and Run 5 on the demo VM `nightshift-demo-app`.
Written by Claude on 2026-10-02 for Instinct to read and run (BAND Bridge `819ce581`, `7e8e1041`).
Untested before its first run: it was only syntax-checked.

    bash compare.sh 64-181-239-158.sslip.io all      # checks, then sites
    bash compare.sh 64-181-239-158.sslip.io undo     # remove the three sites and containers


Moved here on 2026-10-03 from the separate branch `nightshift-demo-compare-script` (commit `d7b84a2`), which this folder replaces. The script is unchanged.
