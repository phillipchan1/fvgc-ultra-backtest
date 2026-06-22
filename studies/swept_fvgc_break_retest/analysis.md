# Swept-Level FVGC Break-&-Retest — Cohort Mining

**Status:** COMPLETE (Phase 0 → F). **Verdict: thesis not confirmed — reject as standalone play;**
retain §4.6 HTF-position + R0-distance factors as confluence inputs. See Verdict at bottom.
**Date:** 2026-05-27

## Question

Does an FVG that forms **at a recently-swept level**, then **breaks and retests** that level
as new structure, with an **untested magnet within reach** as a target, have materially
higher continuation expectancy than baseline FVGC — and is that edge strongest when
**aligned with the prevailing regime**? Headline metric is **R / PF**, not win rate.

## Thesis (to falsify or confirm)

Trapped stops (the sweep) + reclaimed structure (break-&-retest) + open runway to a magnet
= higher continuation expectancy. Mechanism before metric.

---

## Phase 0 — Prior-art diagnosis (why the v1 isn't tier-1)

`studies/breakout_continuation/` is the v1 of this thesis. Verdict: **rejected, reproduction
failure.** It tested: liquidity sweep (non-reclaiming close-through) → opposing-FVG inversion
within 10 bars → first FVGC signal in the **break direction** within 40 bars.

| Metric | Notion claim | Re-run actual |
|---|---|---|
| n | 40 | 47 |
| WR @ 1R | 93.3% | **31.9%** |
| Median MFE | 8.7R | **0.57R** |

All four grid cells (reclaims × locality) scored **25–38% WR vs a 51.7% baseline** — i.e. the
mechanic *underperformed* plain FVGC. The script was sanity-checked (the unflipped direction
reproduces the original 124-trade reversal cohort exactly), so the failure is the *thesis as
defined*, not a bug. The original n=40 / 93% cohort was almost certainly post-hoc curation on a
small sample ("discovered accidentally while building the reversal study").

**Why this study is different (the four salvage paths the v1 author flagged, now built in):**
1. The FVG must **sit at** the swept level (locality), not just appear somewhere after an inversion.
2. A **structural break precedes the retest** (`bars_break_to_retest`), not "any FVGC within 40 bars".
3. The sweep is a **reclaim/grab** (close-back), the mechanism that traps stops — not a clean break-through.
4. Conditioning on **magnet reachability, clean runway, level state, HTF nesting, and regime**, then
   ranking factors and OOS-validating — instead of reporting one hand-filtered cell.

---

## Method & reuse

No signal regeneration. We build on the cached **6,614 FVGC signals (2018-01 → 2026-05, 8.3 yr)**
in `logs/baseline_trades.csv` (each row carries `entry_idx`, FVG zone, structure SL, `sl_dist`,
MFE/MAE, fixed-R `hit_XR`). `entry_idx` indexes the canonical 30s file and **aligned for 100% of
signals** (0 misaligned, 0 `created_idx` fallbacks) — confirming the cache is consistent with the
current 30s data.

Reused infrastructure: `fvgc.data.load_candles`, `fvgc.volume_profile.compute_volume_profile`,
`shared.vwap.session_vwap`, `data.levels.level_registry` + `liquidity_levels.csv` (per-date level
universe: session levels + HTF FVGs with `bars_old`/`swept_pre_rth`/`available_time`),
`data.levels.enrich_trades_with_levels.filter_trade_date_levels` (causal availability gate),
`daily_volume_profile.csv` (lag-1 VP), `trading_days.csv` (regime). Significance gating
(`analysis/permutation_test.py`) and the train/test split harness are wired in for Phase E.

> **Engineering note:** new per-signal features live in this study's `features.py` (not the shared
> `enrich_trades_with_levels.py`) to keep the study self-contained and avoid disturbing the
> production `trades_with_levels.csv` pipeline that other studies consume. The brief suggested the
> shared file; this is a deliberate, scoped deviation.

### Exit model (§7) — dynamic-magnet simulator (`magnet_sim.py`)

Each signal exits at the **next untested magnet** (target) **or structure invalidation**
(stop = the model's structure-based SL, the opposite FVG edge) — whichever 30s bar hits first,
walking forward to EOD.

- **R denominator = `sl_dist`** (the model's clamped structure-stop distance). Keeps every signal
  on one R scale and comparable to the cached fixed-R `hit_XR`.
- target hit → `+magnet_dist_R`; stop hit → `−1.0`; both in one bar → `ambiguous`, take the stop;
  neither by EOD → exit at day's last close (`eod`, flagged `no_magnet` when there was no magnet).
- **BE variant** (`sim_realized_r_be`): the validated VWAP-play nuance — move stop to break-even
  once +1R favorable is reached.

---

## Phase A — Baseline (must-beat) + regime-matched baselines

4,548 tradeable signals, 8.3 yr, ~549 trades/yr. **Dynamic-magnet exit, unconditioned:**

| Cohort | n | /yr | WR | fixedWR | E[R] | PF |
|---|---|---|---|---|---|---|
| **ALL (baseline)** | 4548 | 549 | 0.449 | 0.496 | **−0.032** | **0.94** |
| long | 2284 | 276 | 0.431 | 0.497 | −0.065 | 0.89 |
| short | 2264 | 273 | 0.466 | 0.494 | +0.001 | 1.00 |
| macro_up | 2178 | 263 | 0.447 | — | −0.049 | 0.91 |
| macro_down | 1041 | 126 | 0.443 | — | +0.017 | 1.03 |
| long × macro_up (aligned) | 1100 | 133 | 0.417 | — | **−0.103** | **0.82** |
| short × macro_down (aligned) | 523 | 63 | 0.472 | — | **+0.084** | **1.16** |
| short × macro_up (counter) | 1078 | 130 | 0.477 | — | +0.006 | 1.01 |
| aligned (diagonal) | 1623 | 196 | 0.435 | — | −0.043 | 0.92 |
| counter (diagonal) | 1596 | 193 | 0.456 | — | −0.013 | 0.98 |
| variant=bos | 1361 | 164 | 0.530 | — | −0.023 | 0.95 |
| variant=protected_swing | 632 | 76 | 0.312 | — | −0.035 | 0.95 |

Full table: `results/phase_a_baseline.csv`.

**Baseline reads as ~breakeven-negative (PF 0.94)** — a true must-beat bar. Early signal worth
flagging for Phase E: the **§9 alignment diagonal looks inverted** — long-in-uptrend is the worst
cell (PF 0.82) while short-in-downtrend is the best (PF 1.16). Naive "trade with the trend" is not
free; the short side carries the regime edge in this 2018–2026 (mostly-up) tape. We'll demand the
alignment effect against **same-regime** baselines and in **both** regimes before crediting it.

---

## §4 Feature catalog — AS-OF availability (lookahead audit table)

Every feature is computed strictly as-of the entry bar. Columns in `results/signals_enriched.csv`.

| Feature(s) | § | As-of window read | Lookahead risk & mitigation |
|---|---|---|---|
| `swept`, `bars_since_sweep[_bucket]`, `swept_level_provenance`, `swept_level_price`, `sweep_reclaim` | 4.1 | RTH bars **[9:30, fvg_created)** only | Sweep must precede FVG formation; scan ends at `created_idx`. Stop-liquidity levels only (§6). |
| `has_break`, `bars_break_to_retest[_bucket]` | 4.2 | bars **[fvg_created, entry]** | Break = first close beyond FVG far edge (displacement leg); ≤ entry by construction. **Proxy for BOS tempo — flag for review.** |
| `magnet_*` (price/group/dist_pts/dist_R/per_fvg/per_atr), `clean_runway` | 4.3 | untested check uses RTH **[9:30, entry)**; all level prices known ≤ entry | "Untested" = no RTH bar through it before entry. Magnet universe = stop-liquidity + VWAP/POC/VA. |
| `vwap`, `vwap_dist_pts/_signed`, `vwap_above`, `r0_ge_10pt` | 4.4 | `session_vwap` cumulative **[9:30, entry]** | VWAP is cumulative, naturally causal; value taken at entry bar. |
| `va_pos_prior` | 4.4 | **lag-1** prior-day VP (shifted) | Prior session only. |
| `va_pos_dev`, `dev_poc/vah/val` | 4.4 | developing VP, RTH **[9:30, entry]** | Windowed to entry; no full-session VP (the `vp_targets` lookahead trap). |
| `level_touch_count`, `level_virgin` | 4.5 | RTH **[9:30, entry)** | Touches counted before entry. |
| `confluence_stack` | 4.5 | levels available ≤ entry | Distinct groups within ±10 pt of FVG mid. |
| `inside_htf_fvg`, `htf_nest_tf`, `htf_position_within_gap`, `htf_aligned` | 4.6 | HTF FVG bounds pre-session/pre-entry; entry price known | Position within gap from entry price; HTF gaps pre-exist (per `htf_nesting` study). |
| `macro_trend`, `ema20/50`, `atr14` | 4.7 | daily series **shifted 1** (through prior close) | EMAs/ATR use prior sessions only — no today's-close leakage (the `higher_R_targets` trap). |
| `regime_alignment` | 4.7/9 | derived from `macro_trend` (prior) + direction | Causal. |
| `open_vs_prior_va` | 4.7 | today's 9:30 open vs lag-1 VA | Open is known at 9:30. |
| `or_width_asof` | 4.7 | **availability-gated**: 5m@9:35 / 15m@9:45 / 45m@10:15 ≤ entry | Prevents the `or_45min_range` pre-availability leak (the `win_loss_discriminator` trap). |
| `price_above_dev_vwap`, `price_above_dev_poc` | 4.7 | entry vs developing VWAP/POC ≤ entry | Causal. |
| `vixy_regime`, `prior_day_type`, `gap_from_prior_close` | 4.7 | `trading_days` (vixy = prior_close; NaN for ~141 warmup days early-2018) | Lagged in source. |

### Known definitional choices to confirm at checkpoint
1. **`bars_break_to_retest`** is anchored to *first close beyond the FVG far edge* (displacement),
   not a swing-based BOS. Faithful to "displacement→retest tempo," simpler than re-deriving swings.
   Confirm this proxy or switch to a swing-based break.
2. **"FVG sits at a level"** tolerance = `max(3.0 pt, 0.5×fvg_size)`. Will be swept in Phase B.
3. **Sweep = reclaim/grab only** (wick past + close back). The clean-breakout ("reject") case is
   not currently treated as a separate swept-level event. Confirm.
4. **Round-number magnets** = 50 & 100-pt grid within the session range, treated as stop-liquidity.

---

## Checkpoint adjustments (applied per Phil)

1. **Break→retest** now also carries a time dimension: `break_to_retest_min` + `retest_within_10min`
   (≤20×30s bars). 2. **"FVG sits at a level"** pad loosened to **20 pt** default (still sweepable).
   3. **Sweep** no longer requires a strict wick-past-and-close-back — any *reach* of the level counts,
   with `sweep_type ∈ {reclaim, tag}` recording the close-back quality. 4. Round-number magnets kept.

Effect: `swept` becomes near-universal (96%), so discrimination moves into `sweep_type` (reclaim
3576 / tag 2781), provenance, break-retest tempo, and location — exactly what the ranking tests.

> **Data note:** the shared `logs/baseline_trades.csv` is periodically regenerated by a background
> job against a *rolling* (shorter) candle set, which breaks `entry_idx` alignment with the full 8yr
> 30s file. The study is pinned to a frozen, alignment-verified 8yr snapshot
> (`baseline_signals_8yr.frozen.csv`, 0/6614 misaligned) for reproducibility.

---

## Phase B–C — factor ranking (in-sample / train: 3,029 signals, 6.3 yr, baseline PF 0.93 / E[R] −0.040)

Single-factor sweeps → each factor's best actionable bucket (N≥30, degenerate `none/na` excluded),
expectancy-R lift over baseline, and a label-permutation p-value. **Ordered factor-importance table**
(survivor = lift>0, p<0.05, mechanism present):

| Rank | Factor | Best bucket | n | WR | E[R] | PF | lift | perm p | survivor |
|---|---|---|---|---|---|---|---|---|---|
| 1 | htf_position | mid | 64 | 0.55 | +0.252 | 1.56 | +0.292 | 0.044 | ✅ |
| 2 | provenance | bsl_ssl | 74 | 0.54 | +0.149 | 1.33 | +0.190 | 0.114 | — |
| 3 | level_touch | 3–5 | 170 | 0.65 | +0.086 | 1.25 | +0.126 | 0.114 | — |
| 4 | prior_day_type | trend_up | 366 | 0.46 | +0.067 | 1.12 | +0.108 | 0.055 | — |
| 5 | magnet_R | >3R | 531 | 0.20 | +0.061 | 1.08 | +0.101 | 0.034 | ✅ |
| 6 | open_vs_prior_va | above | 988 | 0.45 | +0.039 | 1.07 | +0.080 | 0.016 | ✅ |
| 7 | va_pos_prior | above | 1008 | 0.44 | +0.022 | 1.04 | +0.063 | 0.035 | ✅ |
| 8 | vixy_regime | normal | 1163 | 0.46 | +0.012 | 1.02 | +0.053 | 0.043 | ✅ |
| 9 | below VWAP (vwap_above=F ≈ price_above_dev_vwap=F) | — | 1559 | 0.46 | +0.010 | 1.02 | +0.050 | 0.018 | ✅ |
| 10 | direction | short | 1555 | 0.46 | +0.001 | 1.00 | +0.041 | 0.041 | ✅ |

**Mechanism-consistent anti-signals** (reproduce known mechanics): `htf_position=far` & `magnet_group=htf`
(trading *into* HTF resistance — the §4.6/§6 split works), `r0_ge_10pt=False` (reproduces the VWAP-play
R0≥10 rule), `btr_timing=0-1` (too-fast retest, no pullback structure), `variant=ifvg`.

Most surviving lifts are **small and several are beta** (short / macro-down / vixy in a chop-prone tape).
Full table: `results/phase_c_factor_ranking.csv`.

## Phase D — tiered cohort mining (in-sample). Three families (292 combos, N≥40):

| Family | Best cohort | n | /yr | WR | E[R] | PF |
|---|---|---|---|---|---|---|
| `htf_mid` (survivors-only) | htf_mid & not_target_htf & not_ifvg | 42 | 6.6 | 0.62 | +0.426 | 2.12 |
| `far_magnet` runners (max E[R]) | far_magnet & btr_4_6 & reclaim | 61 | 9.6 | 0.30 | +0.776 | 2.10 |
| `level_touch_3_5` (high-WR, exploratory) | short & below_vwap & level_touch_3_5 | 67 | 10.6 | 0.72 | +0.238 | 1.84 |

## Phase E — OOS validation (held-out test: 1,519 signals, 2024-06 → 2026-05, 1.9 yr; baseline PF 0.97)

**No cohort passes.** Bonferroni α = 0.05/16 = 0.0031.

| Cohort | test n | WR | E[R] | PF | early PF | late PF | perm p | regime excess | PASS |
|---|---|---|---|---|---|---|---|---|---|
| short & below_vwap & level_touch_3_5 | 57 | 0.68 | +0.038 | 1.12 | 0.98 | 1.34 | 0.38 | +0.036 | ❌ |
| far_magnet & r0_ge_10 & btr_4_6 | 25 | 0.16 | +0.045 | 1.05 | 0.84 | 1.29 | 0.39 | +0.060 | ❌ |
| far_magnet & btr_4_6 & reclaim | 23 | 0.13 | −0.151 | 0.83 | 0.93 | 0.73 | 0.67 | −0.137 | ❌ |
| **htf_mid & not_target_htf & not_ifvg** | 33 | 0.39 | **−0.209** | **0.66** | 0.56 | 0.72 | 0.80 | −0.194 | ❌ |

The clean `htf_mid` family (train PF 2.12) **reverses to PF 0.66 OOS** — overfit. The high-E[R]
`far_magnet` runners do not hold (PF 0.83–1.05, fail robustness). The best OOS performer
(`short & below_vwap & level_touch_3_5`) is mildly positive but **not robust** (early-test half
breakeven 0.98) and **not significant** (p=0.38 ≫ 0.003). Full table: `results/phase_e_oos.csv`.

## Phase F — breakdown of the best candidate (`short & below_vwap & level_touch_3_5`, full-sample n=124)

Positive E[R] in **7 of 9 years** but tiny per-year n (2–25), and **heavily concentrated in the first
15 min** (0930–0945: n=85, PF 1.69; later windows flat). A plausible opening-drive tilt — but
sub-threshold. `results/phase_f_*` + `trades_best_candidate.csv`.

---

## Verdict

**The thesis is not confirmed.** No conditioned cohort beats the ~breakeven baseline on PF/E[R] in a
way that survives out-of-sample, the early/late robustness check, and a Bonferroni-corrected
permutation null. The single factors that *do* carry directional, mechanism-consistent signal
in-sample are **(ranked)** `htf_position=mid` vs `far` (open runway inside a nested HTF gap vs trading
into its far edge), the **R0≥10-pt distance-from-VWAP** rule, **magnet type** (mean-reversion magnets
pull / HTF gaps obstruct), and **break→retest tempo** (a window, not an instant) — all of which
reproduce known FVGC/VWAP mechanics and validate the §4.6/§6 design. But their lifts are small, and
the rest of the surviving factors (short, macro-down, vixy-normal, above-prior-VA, below-VWAP) are
largely **beta** of a chop-prone 2018–2026 tape: regime-matched excess is ≤ +0.06 R and not
significant. Combinations that looked strong in-sample (`htf_mid` PF 2.12, `far_magnet` runners
E[R] +0.78) are **overfit** — they collapse on the 1.9-yr holdout. The one mild survivor is a
first-15-min short tilt (~15/yr, OOS PF 1.12) that is **not frequent or significant enough to trade**.
Recommendation: **reject as a standalone play**; retain the §4.6 HTF-position and R0-distance factors
as confluence inputs to existing validated plays rather than as a primary entry model. The negative is
clean — lookahead-audited features, OOS-gated, multiple-testing-corrected.
