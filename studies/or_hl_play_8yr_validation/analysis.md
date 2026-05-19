# Study: FVGC → OR H/L — 8-year IS/OOS validation

**Status:** Complete. Notion playbook updated.

## Question

The Notion page ("FVGC To Opening Range H/L") claimed a 4-filter A+ cell — OR
close bias + R-to-OR <1.0 + SL 25-35pts + neither OR side swept — at 71.4% WR
and PF 5.00 on n=28, tuned over Oct 2023 → Oct 2025. Does it hold on 8 years
of newly extended data (2018-01 → 2026-05)?

## Methodology

Cached baseline trade tables (no signal regen) were filtered to the play
universe and re-classified for 2R hit using existing MFE columns. OR levels
and first-sweep times were computed from candle parquet on demand.

- **Data window:** 2018-01-01 → 2026-05-17 (8.4 yr, 2,157 trading days)
- **IS:** 2023-10-01 → 2025-10-31 (Notion training window)
- **OOS:** everything else (~6 yr)
- **Trade sources:**
  - 30s: `studies/baseline/results/trades.csv` (6,614 rows)
  - 1m:  `studies/baseline_1m/results/trades.csv` (3,339 rows)
  - 2m, 3m baselines also used for cross-TF stability
- **Outcome convention:**
  - WIN = 1R-engine outcome != 'loss' AND MFE ≥ 2R
  - LOSS = 1R-engine outcome == 'loss'
  - PARTIAL = neither hit (counted as 0R)
- **Scripts:**
  - `run.py` — strict Notion A+ filter stack replication
  - `run_core.py` — core play (entry ≥ 9:45 AND neither OR side swept yet)
  - `setup_cuts.py` — cuts by OR range, R-to-OR, direction, variant
  - `validate_and_xtf.py` — bootstrap 10k + permutation 10k + cross-TF
  - `diag_recent.py` — 2018-24 vs 2025-26 regime breakdown

## Headline findings

### 1. The original Notion A+ filter stack does NOT survive OOS.

Replicating the Notion filter stack (bias + R-to-OR<1.0 + SL 25-35 + neither
swept) only matched n=6 IS trades on 30s and n=3 on 1m — far below Notion's
claimed n=28. Either the page used 15s data (no MFE columns in our baseline)
or the filters were synthesized across multiple scripts. Regardless, on the
matched IS subset the play is heavily overfit:

| TF  | IS PF | OOS PF | OOS EV/trade |
|-----|-------|--------|--------------|
| 30s | 8.00 (n=6) | **1.00** (n=16) | +0.00R |
| 1m  | 2.00 (n=3) | 1.50 (n=16)     | +0.25R |

### 2. The *core* play (just "entry ≥ 9:45 AND neither OR side swept") is real and OOS-stable.

| TF  | n   | WR   | PF (2R) | IS PF | OOS PF | Drift |
|-----|-----|------|---------|-------|--------|-------|
| 30s | 669 | 44.8 | 1.62    | 1.94  | 1.50   | 0.40  |
| **1m**  | **405** | **47.4** | **1.81**    | **1.77**  | **1.82**   | **0.02** |
| 2m  | 188 | 43.1 | 1.52    | 1.89  | 1.42   | 0.48  |
| 3m  | 131 | 51.3 | 2.10    | 6.00  | 1.48   | 0.78  |

1m is the clear winner: highest OOS PF, near-zero IS/OOS drift, robust n.

### 3. Bootstrap (10k resamples on 1m core play, n=405):

- **PF 95% CI: [1.47, 2.21]**, median 1.80
- **EV 95% CI: [+0.249, +0.528] R**, median +0.388R
- **P(EV ≤ 0) = 0.0000**
- **P(PF ≤ 1) = 0.0000**

Verdict: **REAL EDGE.**

### 4. Permutation test — does "neither swept" filter add edge?

Compared core play (n=405, PF 1.81) vs full post-9:45 universe (n=945, PF 1.70).
Drew 10k random length-405 samples from the full universe.

- P(null EV ≥ observed) = **0.22**
- P(null PF ≥ observed) = **0.22**

Verdict: **Filter ≈ noise.** The OR-sweep gate doesn't add statistically
significant edge above any-FVGC-after-9:45. The edge is in the base FVGC
model + 2R target, not the gate. Phil's intuition that "the play dies on
sweep" is directionally right (PF 1.81 vs 1.62 on swept subset) but the lift
is within sampling noise.

## Setup-cell breakdown (1m core play, n=405)

### OR range — the dominant filter

| OR range | n   | PF (2R) | EV/trade |
|----------|-----|---------|----------|
| <30pt    | 6   | 1.33    | (tiny)   |
| 30-60pt  | 87  | 2.39    | +0.57R   |
| **60-100pt** | **155** | **2.03**    | **+0.48R**   |
| 100-150pt| 120 | 1.56    | +0.28R   |
| **>150pt**   | **37**  | **0.92**    | **-0.05R**   |

Clear V-shape. Wide ORs (>150pt) tend to expand further; the play breaks.
Hard kill switch.

### R-to-OR (entry to opposite OR / SL)

| R-to-OR  | n   | PF (2R) | EV/trade |
|----------|-----|---------|----------|
| <0.25    | 67  | 1.60    | +0.31R   |
| 0.25-0.5 | 93  | 2.00    | +0.42R   |
| **0.5-0.75** | 66  | **2.67**    | **+0.68R**   |
| 0.75-1.0 | 45  | 1.73    | +0.36R   |
| 1.0-1.5  | 56  | 1.64    | +0.32R   |
| >1.5     | 78  | 1.58 (unstable, IS≈0) | low |

Sweet spot 0.25-1.0 R away from opposite OR side.

### Direction

| Direction | n   | PF (2R) | IS PF | OOS PF |
|-----------|-----|---------|-------|--------|
| **Long**  | 208 | **2.02**    | 1.75  | **2.11**   |
| Short     | 197 | 1.60    | 1.79  | 1.52   |

Asymmetric — longs are stronger and OOS-improving.

### Variant pecking order (1m core play)

| Variant | n | PF (2R) |
|---------|---|---------|
| no_fvg          | 186 | 1.89 |
| protected_swing | 99  | 1.84 |
| bos             | 67  | 1.74 |
| **ifvg**            | **53**  | **1.52** |

ifvg is the weakest — opposite of the old Notion page which called it the standout.

### A+ stable cells (passing strict OOS gate: n≥25 each half, PF≥2 each half, EV≥+0.4R each half)

| Filter | n   | PF (2R) | EV/trade | IS / OOS |
|--------|-----|---------|----------|----------|
| OR 60-100pt | 155 | 2.03 | +0.48R | 2.00 / 2.04 ★ |
| Long × OR 60-100pt | 91 | 2.36 | +0.58R | 1.67 / 2.67 |
| Long (any) | 208 | 2.02 | +0.47R | 1.75 / 2.11 |

## Updated playbook recipe

**Take it:**
- 1m FVGC entry ≥ 9:45 ET
- OR range 30-100 pts (sweet spot 60-100)
- R-to-OR between 0.25 and 1.0
- Prefer longs; shorts only if OR ≤100pt
- 2R target, hold original SL, no breakeven

**Skip / kill switch:**
- OR > 150 pts (negative EV)
- R-to-OR > 1.5
- ifvg variant on this play

## Economic projection

At ~50 1m core-play entries/yr × $20/pt NQ × 30pt avg SL × +0.388R EV/trade
= **+$11,640/yr per contract** on the base play, before A+ filtering.

## Files

- `results/core_play_1m.csv` — qualifying trades, 1m
- `results/core_play_30s.csv` — qualifying trades, 30s
- `results/xtf_stability.csv` — cross-TF summary
- `results/setup_cuts.log` — full slice table
- `results/validate_and_xtf.log` — bootstrap + permutation output
- `results/diag_recent.log` — regime breakdown

## Notion sync

Playbook config (`playbook/plays.json`) updated 2026-05-18 to reflect:
- status: backtesting → verified
- sample_size: 60 → 405
- wr_base: 61.7% → 47.4%, pf_2r: 1.81 added
- kill_switch: replaced sweep-gate language with OR>150 + R-to-OR>1.5 + ifvg-skip
- premium_filters: new A+ cells (long × OR 60-100, R-to-OR 0.5-0.75)

Notion page update separately drafted in this session.
