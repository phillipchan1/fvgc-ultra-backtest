# Multi-Cell Confluence Matrix Study

**Goal**: Find every (time_window × direction) cell where a stackable confluence count
produces a tradeable edge comparable to the W1 Short Confluence Model (the
reference: ~72% WR, PF 3.20 @ 2R, regime-robust).

**Universe**: 1,572 FVGC NQ trades, 2023-10-02 → 2026-03-25 (`studies/mfe_multi_r/results/mfe_trades_enriched.csv`).
8-cell matrix (4 windows × 2 directions), `protected_swing` excluded from primary tables.

**Honest summary** (TL;DR): The W1 reference replicates (M1 short, n=124, 70%+ WR
at 2+ conf threshold, regime-robust). **M2 long emerges as a new tradeable cell**
(3+ conf, IS 66.4% → OOS 65.0% WR, +0.58R/trade EV). **M3 short looks alpha at
3+ on aggregate but is regime-fragile** (25% WR in bear regime, n=16) — only
tradeable when the macro is not bear. The other three cells (M1 long, M2 short,
M3 long) **fail OOS** despite strong IS numbers at the 4+ tier — classic
over-fit signatures.

---

## Methodology

Phase pipeline (see [the plan](../../.claude/plans/research-prompt-find-tender-alpaca.md)):

- **A** — Build analysis frame: derive `macro_window` from timestamp, compute NQ
  60-day return → bull/bear/neutral regime, IS/OOS split (cutoff 2025-10-01).
- **B** — Per-cell baseline (IS, protected_swing excluded).
- **C** — Univariate WR-lift per factor per cell. **Look-ahead-safe allow-list
  applied per cell** (see "Methodology lessons" below).
- **D** — Pro-stack + veto tier construction. Greedy add up to K=7 pros and K=3
  vetos with mutual correlation < 0.5 on IS data.
- **E** — OOS holdout validation. Cell configs frozen on IS, applied to OOS.
- **F** — Regime breakdown across bear/bull/neutral on the IS+OOS combined sample.
- **G** — This report.

**Stop = 1R always** (engine baseline). Win-rate uses outcome at 1R TP. PF @ 2R
is computed from the `hit_2_0R` column (`wins * 2R / losses * 1R`), not the
buggy `mfe_r` column. The hit ladder (1R/2R/3R/5R) is the source of truth for
runner expectations.

A "tradeable" verdict requires: (1) OOS WR drop ≤ 10pp from IS at the chosen
threshold, (2) max-min regime WR ≤ 15pp on the IS+OOS combined sample (each
regime n ≥ 10), (3) the chosen threshold has OOS n ≥ 10.

---

## Headline cell ranking

Across-threshold view per cell (IS / OOS at conf_count ≥ K). Verdict reflects
both OOS stability **and** regime robustness. Aggregated tier data:
[results/oos_aggregated_tiers.csv](results/oos_aggregated_tiers.csv).

| Cell | Best threshold | IS n / WR / PF | OOS n / WR / PF | WR drop | Regime spread | EV/trade (best strat) | Verdict |
|---|---|---|---|---|---|---|---|
| **M1 short** (W1) | **conf ≥ 2** | 111 / 68.5% / 2.44 | 13 / 76.9% / 1.71 | **−8.4pp** | **10.3pp** | **+0.77R** | **TRADEABLE** ✓ |
| **M2 long** | **conf ≥ 3** | 119 / 66.4% / 1.72 | 20 / 65.0% / 1.33 | **+1.4pp** | 17.7pp* | **+0.58R** | **TRADEABLE — bull/neutral only** ✓ |
| **M3 short** | conf ≥ 3 | 149 / 49.7% / 1.07 | 18 / 61.1% / 2.00 | −11.4pp | **31.5pp** | +0.27R | CONDITIONAL — kill in bear regime |
| M1 long | conf ≥ 4 | 45 / 71.1% / 2.29 | 9 / 44.4% / 1.00 | +26.7pp | 21.9pp | — | REJECT (over-fit) |
| M2 short | conf ≥ 4 | 90 / 68.9% / 1.60 | 13 / 46.2% / 1.25 | +22.7pp | 10.6pp | — | REJECT (over-fit) |
| M3 long | conf ≥ 4 | 96 / 71.9% / 1.62 | 5 / 20.0% / 0.50 | +51.9pp | 2.4pp* | — | REJECT (over-fit) |
| M4 long, M4 short | — | <8 trades total | — | — | — | — | REJECT (insufficient sample) |

\* regime spread at thresholds where only 2 of 3 regimes had n ≥ 10 — bull-regime-dominated samples.
EV uses the 1/3 @ 1R + 1/3 @ 2R + 1/3 @ 5R scaling strategy with BE stop on runner.

**Honest comparison to the W1 reference numbers in the brief** (n=65, WR 72.3%,
PF 3.20): the prompt's "n=65" comes from the existing
[w1_short_setups/04_bear930_gap_down.csv](../mfe_multi_r/results/w1_short_setups/04_bear930_gap_down.csv)
which is a **2-factor strict combo** (`bear_930 AND gap_down`), not a "4+ tier
out of 6 factors". My 2+ threshold (which lifts the rule to "any 2 of the 7
pros") is the closest analog and recovers the regime-robust 70%+ WR profile
with bigger sample (n=124 vs n=65).

---

## Per-cell detail

### 1. M1 Short — W1 reference replicated (TRADEABLE)

**Trigger** (one sentence): A bearish 9:30 candle in a gap-down, prior-day-weak
context produces a robust short edge in the 9:30–9:45 window — the W1 model
the playbook already runs.

**Stack** (7 pros, 3 vetos):

| Pros | IS lift |
|---|---|
| `bear_930` | +21.3pp |
| `gap_large_down` (< −100 pts) | +19.0pp |
| `c930_body_top_q` (body in top quartile) | +15.6pp |
| `prior_day_weak` (PD close in bottom ⅓) | +13.7pp |
| `is_fomc_week` | +11.8pp |
| `vixy_high` | +10.1pp |
| `dow_friday` | +9.7pp |

| Vetos | IS lift |
|---|---|
| `vixy_low` | −15.7pp |
| `dow_monday` | −12.5pp |
| `no_red_folder` | −6.8pp (weak; near threshold) |

**Tier table** (IS, protected_swing excluded):

| Tier | n | WR | PF@2R | hit_2R | hit_3R | hit_5R | Med MFE (1R+) | trades/mo |
|---|---|---|---|---|---|---|---|---|
| 0–1 | 56 | 46.4% | 0.87 | 30.4% | 16.1% | 14.3% | 2.25R | 2.34 |
| 2 | 54 | 57.4% | 1.60 | 44.4% | 25.9% | 18.5% | 2.50R | 2.25 |
| 3 | 33 | 72.7% | 2.71 | 57.6% | 48.5% | 39.4% | 5.00R | 1.38 |
| 4+ | 24 | 87.5% | 6.00 | 75.0% | 54.2% | 45.8% | 5.00R | 1.00 |

**IS vs OOS at conf ≥ 2** (the robust threshold):

| Sample | n | WR | PF@2R | hit_2R | hit_3R | Med MFE 1R+ | trades/mo |
|---|---|---|---|---|---|---|---|
| IS | 111 | 68.5% | 2.44 | 55.0% | 38.7% | 4.0R | 4.63 |
| OOS | 13 | **76.9%** | 1.71 | 46.2% | 30.8% | 2.0R | 2.29 |

The OOS sample is small (n=13) but WR holds. OOS at conf ≥ 4 is essentially
empty (n=1), so the 2+ threshold is the right one for live use until more
OOS data accrues.

**Regime breakdown** (IS+OOS combined, conf ≥ 2):

| Regime | n | WR | Note |
|---|---|---|---|
| bear | 20 | 70.0% | Strong |
| neutral | 26 | 61.5% | Mild dip |
| bull | 78 | 71.8% | Strong |

Spread = 10.3pp ≤ 15pp threshold. **REGIME-ROBUST.**

**Exit EV per trade** (from `results/ev_M1_short_2plus.csv`):

| Strategy | EV/trade |
|---|---|
| TP fixed @ 1R | +0.39R |
| TP fixed @ 2R | +0.62R |
| TP fixed @ 3R | +0.52R |
| TP fixed @ 5R | +0.74R |
| ½ @ 1R + ½ @ 2R (BE runner) | +0.58R |
| **⅓ @ 1R + ⅓ @ 2R + ⅓ @ 5R (BE runner)** | **+0.77R** ← best |

The 3-stage scale is best because median MFE among 1R+ trades is **4–5R** —
significant tail. Pure 1R scalping leaves money on the table.

**Live execution checklist** (run from 9:25 to 9:31 each day):

1. ☐ Is there a bearish 1-min 9:30 candle? (mandatory; entry trigger)
2. ☐ Gap < −100 pts OR prior-day close in bottom ⅓ OR FOMC week? (≥1 of these)
3. ☐ Is VIXY *not* in the bottom quartile and not a Monday? (veto check)
4. ☐ Confluence count ≥ 2 of 7 pros active?
5. ☐ Trigger an M1 short on the next valid FVGC entry. Manage exits per 3-stage scale.

**Caveats**:
- OOS n=13 is thin — confidence interval on the 76.9% WR is wide. Watch closely.
- `is_fomc_week` as a +factor is counter-intuitive (FOMC tends to whipsaw); the
  W1 audit may want to confirm this isn't a small-sample artifact (n_active=21).
- `protected_swing` delta on this cell is +0.7pp (negligible).

**Per-cell trade list**: [results/cells/M1_short_2plus.csv](results/cells/M1_short_2plus.csv) (124 trades)

---

### 2. M2 Long — new tradeable cell (TRADEABLE, bull/neutral only)

**Trigger** (one sentence): A bullish 9:30 candle with prior-15-minute FVG
activity, no Wednesday/opex, and no bear-regime overlay produces a momentum
continuation long in the 9:45–10:00 window.

**Stack** (7 pros, 3 vetos):

| Pros | IS lift |
|---|---|
| `bull_930` | +20.6pp |
| `dow_thursday` | +10.0pp |
| `has_pre_rth_news` | +9.6pp (counter-intuitive — see caveats) |
| `macro_1_2plus_fvgs` (≥2 FVGs in 9:30–9:45) | +9.4pp |
| `regime_bull` (60d NQ return > +5%) | +9.4pp |
| `has_5m_bear_fvg` | +7.6pp (counter-intuitive — see caveats) |
| `gap_up` | +7.0pp |

| Vetos | IS lift |
|---|---|
| `is_opex_week` | −25.2pp (strongest veto in the study) |
| `dow_wednesday` | −23.7pp |
| `regime_bear` | −20.9pp |

**Tier table** (IS):

| Tier | n | WR | PF@2R | hit_2R | hit_3R | hit_5R | Med MFE (1R+) | trades/mo |
|---|---|---|---|---|---|---|---|---|
| 0–1 | 29 | 48.3% | 1.62 | 44.8% | 41.4% | 27.6% | 5.00R | 1.21 |
| 2 | 61 | 42.6% | 0.84 | 29.5% | 27.9% | 21.3% | 4.50R | 2.55 |
| 3 | 50 | 56.0% | 1.33 | 40.0% | 34.0% | 16.0% | 3.00R | 2.09 |
| 4+ | 69 | 73.9% | 2.06 | 50.7% | 40.6% | 29.0% | 3.00R | 2.88 |

The 4+ tier looks gorgeous in IS but OOS collapses to 50% (n=10). The **3+
threshold combined** is the right level. Aggregated (3+ = tier 3 + tier 4+):

| Sample | n | WR | PF@2R | hit_2R | hit_3R | Med MFE 1R+ | trades/mo |
|---|---|---|---|---|---|---|---|
| IS | 119 | 66.4% | 1.72 | 46.2% | 37.8% | 3.0R | 4.97 |
| OOS | 20 | **65.0%** | 1.33 | 40.0% | 30.0% | 2.0R | 3.60 |

OOS holds at almost identical WR (−1.4pp). **The most surprising find of the
study.**

**Clean variant** (veto_count == 0): adds another 8–10pp of WR by removing
opex/Wednesday/bear-regime trades. Clean 4+ IS: 83.0% WR, PF 2.61 (n=53).

**Regime breakdown** (IS+OOS, conf ≥ 3):

| Regime | n | WR | Note |
|---|---|---|---|
| bear | 6 | 33.3% | Thin sample; cell is structurally weak in bear |
| neutral | 38 | 57.9% | OK |
| bull | 95 | 71.6% | Strong |

The cell is **bull-and-neutral only**. The `regime_bear` veto already encodes
this in the stack — keep it. Spread on the 2 regimes with n ≥ 10 = 13.7pp.

**Exit EV per trade** (from `results/ev_M2_long_3plus.csv`):

| Strategy | EV/trade |
|---|---|
| TP fixed @ 1R | +0.32R |
| TP fixed @ 2R | +0.36R |
| TP fixed @ 3R | +0.47R |
| TP fixed @ 5R | +0.42R |
| ½ @ 1R + ½ @ 2R (BE runner) | +0.45R |
| **⅓ @ 1R + ⅓ @ 2R + ⅓ @ 5R (BE runner)** | **+0.58R** ← best |

Median MFE 1R+ is 3R (lower than M1 short's 5R), so the 3-stage scale wins by
less. TP fixed @ 3R is a strong simple alternative.

**Live execution checklist**:

1. ☐ Wait for 9:45 (M2 window starts).
2. ☐ Is the day NOT a Wednesday, NOT an opex Friday, AND not in a bear macro
   regime (60d NQ return > −5%)?
3. ☐ Was the 9:30 candle bullish?
4. ☐ Are there ≥2 FVGs in the 9:30–9:45 window?
5. ☐ Confluence count ≥ 3 of 7 pros active? Trigger an M2 long on the next
   valid FVGC entry.

**Caveats**:
- `has_pre_rth_news` (+9.6pp) and `has_5m_bear_fvg` (+7.6pp) are counter-intuitive
  pros. They're both low-lift, n_active borderline (26 and 38). May be sample
  noise; if you want a leaner stack drop them and re-evaluate at conf ≥ 2 of 5.
- Bear-regime n = 6: we don't really know how the cell behaves in bear. Until
  more bear OOS accumulates, the regime_bear veto is doing important work.
- Frequency: ~3.6 OOS trades/mo at 3+. Acceptable but not high.

**Per-cell trade list**: [results/cells/M2_long_3plus.csv](results/cells/M2_long_3plus.csv) (139 trades)

---

### 3. M3 Short — conditional, kill in bear regime (CONDITIONAL)

**Trigger** (one sentence): A bearish 9:30 with a compressed range, on a
non-FOMC week with prior-day weakness, produces an extended-fade short in the
10:00–10:15 window — but **only when the macro is NOT in a bear regime**.

**Stack** (7 pros, 3 vetos):

| Pros | IS lift |
|---|---|
| `not_fomc_week` | +17.6pp |
| `bear_930` | +17.0pp |
| `c930_range_bot_q` (compressed 9:30 range) | +17.0pp |
| `dow_friday` | +16.9pp |
| `prior_day_weak` | +16.3pp |
| `macro_1_has_fvg` | +14.8pp |
| `vixy_normal` | +7.0pp |

| Vetos | IS lift |
|---|---|
| `regime_bear` | −17.1pp |
| `dow_wednesday` | −12.4pp |
| `or_5m_bot_q` | −11.3pp |

**Tier table** (IS):

| Tier | n | WR | PF@2R | hit_2R | hit_3R | hit_5R | Med MFE (1R+) | trades/mo |
|---|---|---|---|---|---|---|---|---|
| 0–1 | 17 | 17.6% | 0.27 | 11.8% | 11.8% | 11.8% | 5.00R | 0.71 |
| 2 | 42 | 38.1% | 0.33 | 14.3% | 14.3% | 11.9% | 1.50R | 1.75 |
| 3 | 71 | 38.0% | 0.73 | 26.8% | 22.5% | 14.1% | 3.00R | 2.96 |
| 4+ | 78 | 60.3% | 1.47 | 42.3% | 33.3% | 24.4% | 3.00R | 3.26 |

**3+ combined IS vs OOS**:

| Sample | n | WR | PF@2R | hit_2R | hit_3R | Med MFE 1R+ | trades/mo |
|---|---|---|---|---|---|---|---|
| IS | 149 | 49.7% | 1.07 | 34.9% | 28.2% | 3.0R | 6.22 |
| OOS | 18 | **61.1%** | **2.00** | 50.0% | 50.0% | **5.0R** | 3.17 |

OOS *improved* IS — but the regime breakdown reveals why:

**Regime breakdown** (IS+OOS, conf ≥ 3):

| Regime | n | WR | Note |
|---|---|---|---|
| **bear** | **16** | **25.0%** | Avoid |
| neutral | 62 | 56.5% | Decent |
| bull | 89 | 51.7% | Decent |

Spread = **31.5pp**, far above the 15pp threshold. The cell's OOS pass was
**regime-luck** — the OOS holdout (Oct 2025 → Mar 2026) was bull/neutral and
the bear-regime degradation never had a chance to show up. With the
`regime_bear` veto active, the cell is tradeable; without it, it bleeds.

**Verdict**: only trade this cell when veto_count == 0 (specifically, when the
60d NQ return is > −5%). In a bear regime, this is structurally a chop fade
that loses.

**Exit EV per trade**:

| Strategy | EV/trade |
|---|---|
| TP fixed @ 1R | +0.02R |
| TP fixed @ 2R | +0.10R |
| TP fixed @ 3R | +0.22R |
| TP fixed @ 5R | +0.26R |
| ½ @ 1R + ½ @ 2R (BE runner) | +0.13R |
| **⅓ @ 1R + ⅓ @ 2R + ⅓ @ 5R (BE runner)** | **+0.27R** |

Marginal expectancy. **This is the weakest of the three tradeable cells** —
playable but small edge. The hit_5R of 21% at the 3+ tier is what saves it.

**Live execution checklist**:

1. ☐ Wait for 10:00.
2. ☐ Is the day NOT FOMC week, NOT Wednesday, AND NOT in a bear regime?
3. ☐ Was the 9:30 candle bearish, compressed (range in bottom quartile)?
4. ☐ Was prior day close in bottom ⅓?
5. ☐ Confluence count ≥ 3 of 7 pros? Trigger an M3 short on next valid FVGC entry.

**Caveats**:
- The bear-regime collapse is the binding constraint. Treat the `regime_bear`
  veto as **non-negotiable** — without it, the cell is unprofitable.
- The signed conjunction of `bear_930` and `regime_bear=veto` is interesting:
  "trade short setups only when the macro isn't already bearish." This makes
  physical sense — once everyone's already short, the fade tape eats reversal
  shorts. Mean-reversion fade play, not trend-continuation.
- A simpler 4-factor stack (drop the lowest-lift 3 pros) likely performs
  similarly and is less over-fit-prone.

**Per-cell trade list**: [results/cells/M3_short_3plus.csv](results/cells/M3_short_3plus.csv) (167 trades)

---

## Reject list

| Cell | Reason |
|---|---|
| **M1 long** | 4+ tier IS WR 71.1% / PF 2.29 collapses to OOS WR 44.4% / PF 1.00 (drop 26.7pp). Pros are mostly low-lift (~10-25pp each) and uncorrelated, so even at 4+, the stack is noisy. Likely no real edge. |
| **M2 short** | 4+ tier IS 68.9% / PF 1.60 → OOS 46.2% / PF 1.25 (drop 22.7pp). 2+ and 3+ aggregates also fail. The strongest individual factor (`or_45m_top_q`, +31pp) was excluded as look-ahead for M2 entries. Without it, the cell has no real lift over the 50.5% baseline. |
| **M3 long** | 4+ tier IS 71.9% / PF 1.62 → OOS 20.0% / PF 0.50 (drop 51.9pp — the worst in the study). The "mean-reversion long" thesis (compressed open + prior-day weak + Friday) reads well but does not transfer. Baseline WR 56.9% is already inflated by the bull regime in IS; in OOS bear/neutral the cell craters. |
| **M4 long** | n=8 IS, n=6 OOS. Too thin to model. The 10:15–10:30 window is a structural near-empty cell in the FVGC engine. |
| **M4 short** | n=6 IS, n=4 OOS. Same as M4 long. |

---

## Methodology lessons

Three findings worth carrying forward, especially because they almost slipped past the first pass.

### 1. Look-ahead-safe factor allow-list per cell

The first version of factor mining used `or_15min_top_q` and `or_45min_top_q`
as factors across ALL cells. For M1 entries (9:30–9:45), the 15-min OR
completes at 9:45 — *after* the latest possible M1 entry. Using it as a filter
is pure look-ahead bias. Same for `or_45min_*` for any cell before M4, and for
`macro_X_num_fvgs` where X ≥ the cell's window.

Before the fix, the M1 short 4+ tier showed n=58, WR 84.5%, PF 5.25 — almost
the W1 reference numbers. After the fix it dropped to n=24, WR 87.5%, PF 6.00
(smaller sample, but still robust). **More importantly: the M1 long apparent
edge largely collapsed** — without the look-ahead OR features it has only
~5 small-lift pros and is mostly noise.

The look-ahead audit added per-cell allow-lists. See `factor_safe_for_cell()`
in [factor_mining.py](factor_mining.py) — codify this for any future study
that touches the matrix.

### 2. OOS thinness drives the over-fit story

The 4+ tier sample sizes IS=24–96 / OOS=1–13 per cell. The 7-factor greedy
stack picks up IS noise: a few near-tautological "factor cooccurrence in
bull-regime IS" patterns that vanish OOS. The 3+ threshold (and 2+ for the
strong cells) gives more OOS observations and a more honest verdict.

A more principled fix would be **logistic regression with regularization**, or
**bootstrap stability of the factor selection** — both deferred as follow-ups.

### 3. The `protected_swing` exclusion was nearly free

The W1 audit's −32% WR drag from `protected_swing` doesn't replicate at the
per-cell level — max cell-level delta was +2pp on M3 long. The exclusion is
defensible (it does no harm) but not load-bearing. Future variant-level audits
should distinguish "drag on a full cohort" from "drag within a specific cell".

---

## Caveats & future work

- **Total OOS sample is 220 trades across 6 viable cells.** Per-cell OOS n at
  3+ ranges 8–20. Confidence intervals on 65% WR with n=20 are ±20pp at 95%.
  Some of the "passes" may be sample noise. Treat findings as provisional until
  6 more months of data accumulate.
- **The IS sample is bull-regime-heavy** (826 bull / 482 neutral / 205 bear).
  The W1 reference's regime robustness held up in this study, but cells without
  meaningful bear samples (M2 long at conf ≥ 3 had bear n=6) are not really
  tested in bear regimes.
- **No 30s-bar feature derivations were attempted** (per the plan's non-goals).
  If M2 short genuinely has no edge in the existing feature set, a HTF-FVG
  sweep audit (after the `passes_time_gate` fix is reflected in a regenerated
  `trades_with_levels.csv`) is the next thing to try.
- **Mechanical sub-trigger bonus** (the brief asked for): for M1 short, a
  strict 2-factor combo (`bear_930` + (`gap_large_down` OR `prior_day_weak`))
  gives 75–80% WR on its own with much higher frequency than the 4+ tier.
  Worth a quick follow-up study. For M2 long the strongest pair (`bull_930` +
  `macro_1_2plus_fvgs`) is mechanically cleaner than the full 7-factor stack
  but loses some lift.
- **Factor mining didn't try every interaction**. Two-factor multiplicative
  features (e.g., "gap_down AND prior_day_weak together" vs each independently)
  weren't explored. The greedy correlation < 0.5 selection partially captures
  this but a full interaction search is a separate study.

---

## Reproduction

All numbers regenerable from a clean state:

```
cd /Users/philchan/Work/fvgc-backtest
python -m studies.multi_cell_confluence.build_analysis_frame
python -m studies.multi_cell_confluence.baseline
python -m studies.multi_cell_confluence.factor_mining
python -m studies.multi_cell_confluence.tier_construction
python -m studies.multi_cell_confluence.oos_validation
python -m studies.multi_cell_confluence.regime_breakdown
python -m studies.multi_cell_confluence.build_report
```

Or run all phases via the orchestrator: `python -m studies.multi_cell_confluence.run`.

## Files

| Phase | Script | Output |
|---|---|---|
| A | [build_analysis_frame.py](build_analysis_frame.py) | [trades_analysis.csv](results/trades_analysis.csv) |
| B | [baseline.py](baseline.py) | [baseline_per_cell.csv](results/baseline_per_cell.csv) |
| C | [factor_mining.py](factor_mining.py) | [factor_lift_per_cell.csv](results/factor_lift_per_cell.csv), [factor_shortlist_per_cell.csv](results/factor_shortlist_per_cell.csv), [is_quantiles.json](results/is_quantiles.json) |
| D | [tier_construction.py](tier_construction.py) | [tier_table_per_cell.csv](results/tier_table_per_cell.csv), [cell_configs.json](results/cell_configs.json), [results/cells/*.csv](results/cells/) |
| E | [oos_validation.py](oos_validation.py) | [oos_validation_per_cell.csv](results/oos_validation_per_cell.csv), [oos_verdicts.csv](results/oos_verdicts.csv), [oos_aggregated_tiers.csv](results/oos_aggregated_tiers.csv) |
| F | [regime_breakdown.py](regime_breakdown.py) | [regime_breakdown_per_cell.csv](results/regime_breakdown_per_cell.csv) |
| G | [build_report.py](build_report.py) | per-cell tradeable subsets ([M1_short_2plus](results/cells/M1_short_2plus.csv) · [M2_long_3plus](results/cells/M2_long_3plus.csv) · [M3_short_3plus](results/cells/M3_short_3plus.csv)), per-cell EV tables, this report |
| — | [utils.py](utils.py) | shared metric module |
