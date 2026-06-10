# Phase 3 — Diagnostic addendum (requested by Phil at the Phase-4 gate)

## (1) What was the comparison target?

Each factor was tested against **its own cohort's IS base rate** — longs vs IS-longs base (47.95%), shorts vs IS-shorts base (47.39%), benchmark cells vs IS-benchmark base (56.10%). NOT the pooled 49.5% 8-yr baseline. Marginal-lift over the opening-window-short benchmark was a separate pass (vacuous — no survivors to test). Below, top factors are shown BOTH ways: vs cohort base, and intersected with the IS benchmark cohort (n=41) vs its 56.1% base.

## (2) Top 10 factors by |raw effect| (n>=30 cells)

| factor | cohort | n | WR | base | effect pp | PF | raw p | q (m=174) | q (m=121) |
|---|---|---|---|---|---|---|---|---|---|
| fvg_large | longs | 59 | 59.3% | 47.95% | +11.3 | 1.57 | 0.0903 | 0.93 | 0.88 |
| fvg_stale | longs | 93 | 59.1% | 47.95% | +11.1 | 1.46 | 0.0374 | 0.80 | 0.77 |
| or_break_against | longs | 253 | 56.9% | 47.95% | +8.9 | 1.44 | 0.0046 | 0.66 | 0.47 |
| near_miss_c1 | longs | 96 | 56.2% | 47.95% | +8.2 | 1.38 | 0.1250 | 0.95 | 0.88 |
| target_aligned | benchmark | 30 | 63.3% | 56.1% | +7.2 | 1.75 | 0.4667 | 0.98 | 0.97 |
| macro_w3 | longs | 477 | 54.1% | 47.95% | +6.1 | 1.27 | 0.0078 | 0.66 | 0.47 |
| near_miss_c1 | shorts | 85 | 52.9% | 47.39% | +5.5 | 1.09 | 0.3291 | 0.96 | 0.91 |
| no_draw_dir | longs | 213 | 53.1% | 47.95% | +5.1 | 1.22 | 0.1497 | 0.95 | 0.88 |
| htf15_toward_1atr | benchmark | 36 | 61.1% | 56.1% | +5.0 | 1.49 | 0.6163 | 0.98 | 0.97 |
| asym_pos | shorts | 607 | 52.2% | 47.39% | +4.8 | 1.08 | 0.0183 | 0.80 | 0.74 |

Same factors intersected with the IS benchmark cohort (n=41, descriptive only):

| factor | n in bench | WR | bench base |
|---|---|---|---|
| fvg_large | 3 | 33.3% | 56.1% |
| fvg_stale | 6 | 33.3% | 56.1% |
| or_break_against | 0 | nan% | 56.1% |
| near_miss_c1 | 2 | 50.0% | 56.1% |
| macro_w3 | 4 | 25.0% | 56.1% |
| near_miss_c1 | 2 | 50.0% | 56.1% |
| asym_pos | 16 | 56.2% | 56.1% |

## (3) Positive control: the benchmark condition itself

- FULL sample (harness verification): 69.9% (n=83) vs pooled base 49.48% -> exact p = 2.44e-04. **Fires decisively** — and it is the only q<0.10 survivor in the global ledger. The harness and features are not broken.
- IS ONLY: 56.1% (n=41) vs IS-shorts base 47.39% -> exact p = 0.278. **Does NOT fire on IS** — pre-registered in Phase 1: the benchmark's pooled 8-yr strength is concentrated in the 2024+ OOS window (IS 56.1% / OOS portion implies ~83%).
- **Screen power for benchmark-sized cohorts**: to survive BH rank-1 at m=174 needs p <= 5.75e-04, i.e. >= 31/41 wins (76% WR). A factor with TRUE 70% WR and IS n=41 reaches that with probability 27%. 
  80% power for a true-70% factor requires IS n >= ~95. **The negative result is strong for common factors (n>=200) and weak for rare benchmark-like cohorts (n~40)** — those are structurally undetectable under this screen's correction.

## (4) FDR family sizes and the minimal pre-registered family

- Phase-3 screen family: **174 tests** (58 factors x 3 cohorts); 53 cells had n<30. Clean family excluding those: **121 tests** (min q = 0.47).
- Global ledger at gate time: **197 tests**.
- `or_break_against` (longs, p=0.0046) survives q=0.10 as rank-1 only in a family of **m <= 21** pre-registered tests.
- `macro_w3` (longs, p=0.0078) survives q=0.10 as rank-1 only in a family of **m <= 12** pre-registered tests.
- `asym_pos` (shorts, p=0.0183) survives q=0.10 as rank-1 only in a family of **m <= 5** pre-registered tests.
  Even a one-cohort-per-factor pre-registration (m=58) requires p<=0.0017 — none of the top factors reach it. The null is not an artifact of family bloat.

## (5) Spot-check: draw_asym_dir and need_v2 vs raw bars (3 trades, seed 7)

### 2025-07-31 10:10:00 short @ 23677.75
- untaken above=5 below=2 -> draw_asym_dir want -3, got -3 -> PASS
  - untaken levels: prev_day_low@23356.50(below), london_high@23845.00(above), overnight_high@23845.00(above), 6am_high@23826.25(above), bsl_level@23845.00(above), daily_50pct_low@23522.75(below), or_high@23752.00(above)
- need_v2: leg origin 09:30:00, other unmitigated same-dir FVGs after origin: 0 (none) -> want True, got True -> PASS
### 2022-03-22 09:43:00 short @ 14465.75
- untaken above=0 below=6 -> draw_asym_dir want 6, got 6 -> PASS
  - untaken levels: prev_day_low@14183.75(below), london_low@14324.00(below), asia_low@14293.50(below), overnight_low@14293.50(below), ssl_level@14324.00(below), daily_50pct_low@14325.25(below)
- need_v2: leg origin 09:39:30, other unmitigated same-dir FVGs after origin: 0 (none) -> want True, got True -> PASS
### 2025-12-17 10:08:30 short @ 25299.5
- untaken above=5 below=1 -> draw_asym_dir want -4, got -4 -> PASS
  - untaken levels: prev_day_low@25171.75(below), london_high@25508.50(above), overnight_high@25508.50(above), 6am_high@25508.50(above), bsl_level@25499.00(above), or_high@25447.75(above)
- need_v2: leg origin 09:31:30, other unmitigated same-dir FVGs after origin: 1 (09:36:00) -> want False, got False -> PASS

**Spot-check result: 6/6 PASS**