# Study: IFVG Reversal — Step 1 Population

## Question
Run the model with loose defaults on the full 2018-2026 cohort. How many
candidate setups exist before any selectivity gates? What's the raw edge of
the unfiltered population? What does the joint distribution of factors look
like across the population?

## Methodology
Per [METHODOLOGY.md](../../ifvg_reversal/METHODOLOGY.md) Step 1. Loose-default
config drops all gates that are tuning hypotheses (P/D, chop, reaction
quality, equilibrium veto). Killzone, multi-TF detection, and sweep criterion
stay locked since they fix the universe.

Each emitted row carries metadata for every factor we'll later analyze in
Step 2.

## Completion criterion
N ≥ 100 trades in `results/population.csv`.

## Results
TBD — first run pending.

## Conclusions
TBD.
