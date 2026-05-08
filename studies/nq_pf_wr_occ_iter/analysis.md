# Study: NQ PF/WR/Occurrence Iterative Search

## Question
Can simple post-hoc filter combinations on `trades_with_levels.csv` improve the trade-off between:
- profit factor (PF),
- win rate (WR),
- occurrence (sample size)?

This study does not modify entry logic. It searches for filter subsets that can be used as confluence overlays.

## Methodology
- Data source: `data/levels/trades_with_levels.csv` (win/loss trades only).
- Search framework:
  - Start with single conditions (`variant`, `direction`, magnet groups, boolean gates, proximity and confluence thresholds).
  - Build 2-condition AND combinations.
  - In later iterative scripts, expand to 3-way and 4-way combinations with tighter focus.
- Robustness design:
  - Time-based split train/test (about 70/30 by unique dates).
  - Additional late-period validation in iterative runs.
  - Minimum sample-size gates applied per split.
- Key scripts:
  - `search_pf_wr_occ.py` (base sweep)
  - `search_pf_wr_occ_iter2.py` ... `search_pf_wr_occ_iter12_pf_late_k3.py` (focused iterations)
- Key artifacts:
  - `results/top_single_candidates.csv`
  - `results/top_combo_candidates.csv`
  - `results/best_by_objective.json`
  - Iteration snapshots: `iter*_*.json`, `iter*_*.csv`

## Results
### Base pass (`best_by_objective.json`)
Top PF objective:
- `(path_clear=True) AND (nearest_magnet_group=htf_fvg_15m)`
  - test n=38, WR=63.16%, PF=1.90
  - train n=101, WR=62.38%, PF=1.67

Top WR objective:
- `(direction=long) AND (magnet_within_1R=True)`
  - test n=39, WR=64.10%, PF=1.56
  - train n=84, WR=50.00%, PF=1.04

Top occurrence objective:
- `(path_clear=True) AND (level_swept_before_entry=True)`
  - test n=344, WR=51.74%, PF=1.10
  - train n=870, WR=51.03%, PF=1.09

### Iterative rounds
Later iterations repeatedly converged on a family of long-side magnet-valid combinations:
- `magnet_valid=True AND magnet_within_3R=True AND direction=long`
- plus nearby variants including `level_swept_before_entry=True`

Representative snapshot (`iter10_top_by_objective.json`):
- test n=124, WR=57.26%, PF=1.33
- late n=54, PF=1.52

Earlier broad pick (`iter5_best_of_all.json`) showed:
- `level_swept_before_entry=True AND magnet_valid=True AND magnet_within_3R=True`
  - test n=230, WR=55.65%, PF=1.31
  - late n=100, WR=55.0%, PF=1.28

Late strict rounds (`iter11`, `iter12`) produced no passing combos under tighter gates, which suggests the strongest cells are sensitive to stricter out-of-sample constraints.

## Conclusions
- The search found moderate, repeatable lift candidates, but no extremely robust, high-PF/high-WR/high-occurrence combination that remains dominant under the strictest late-period gates.
- Most promising pattern family is long-direction + magnet-valid proximity (`within_3R`, sometimes `within_2R`) with level-swept context.
- High-occurrence candidates stay near baseline quality (small PF/WR lift), while higher-PF/WR candidates usually come with lower n.
- This work is best interpreted as hypothesis generation and shortlist creation for a properly pre-registered confirmation study (permutation/FDR or a strict walk-forward protocol).

## Recommended follow-up
- Freeze 3-5 non-overlapping candidate rules from this search.
- Re-test only those candidates on a clean holdout window with no additional tuning.
- Add multiple-comparison control (at least BH-FDR) before any playbook promotion.
- Prefer one rule with slightly lower PF but materially higher occurrence if live deployability is the objective.
