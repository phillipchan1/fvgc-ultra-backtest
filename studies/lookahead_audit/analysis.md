# Lookahead Audit — Verify Prior Studies for Causal-Correctness

**Date:** 2026-05-21 (Pass 1) / 2026-05-22 (Pass 2)
**Status:** Pass 1 + Pass 2 complete. All studies in scope have a verdict.
**Trigger:** [composite_vp](../composite_vp/analysis.md) discovered that `daily_volume_profile.csv` joined on `date` exposes 9:30-10:15 trades to 9:30-16:00 full-session aggregates. Under strictly causal lag-1 VP, the Phase A "n_vp ≥ 2 magnet" headline +19.93pp OOS lift **collapses to -1.10pp**. The bug is mechanical and likely repeated across other studies.

## TL;DR

| Severity | Studies | What changes |
| --- | --- | --- |
| **INVALIDATED** | `vp_targets`, `discovery_2R_hits` (n_vp_targets + range_regime), `higher_R_targets`, **`win_loss_discriminator` (Pass 2)** | Published headlines were artefacts. n_vp_targets is noise under causal VP. range_regime is uncomputable causally (uses today's full-session rth_range). Win/loss discriminator: 3 OOS survivors collapse to n=4/1/1 under causal masking. |
| **PARTIALLY CONTAMINATED — core survives, derived cells die** | `htf_nesting`, `speed_of_move`, `candle_930_anatomy` | Core finding (HTF nesting / bars_to_1R / range_z) is independent. Any "× n_vp_targets" cross-cell inherits the parent VP bug. |
| **VERDICT UNCHANGED — kill reinforced** | `va_width_regime`, `naked_vp`, `sweep_fvgc` | Already concluded null; contamination present but the kill stands (often more strongly). |
| **CLEAN** | `composite_vp` (it *found* the bug), `ifvg_reversal_baseline`, `ifvg_reversal_data_wick`, `ifvg_reversal_population`, `or_hl_play_8yr_validation`, `or_width_predictor`, `low_sweep_confluence`, `ath_availability`, `pd_50pct_level`, `prior_day_type`, **`morning_narrative` + `tools/morning_briefing.py` (Pass 2)**, **`turtle_soup_reversal` v0.3 (Pass 2)**, **`ufvg_first_touch` (Pass 2)**, **`ifvg_reversal/` package (Pass 2)** | No contamination found. |

## Pass 2 — the 5 previously-unaudited studies (2026-05-22)

Source for these 5 studies lived only in their original Claude Code worktrees (under `.claude/worktrees/`) — never committed to master. Each was audited by reading the source directly from its worktree.

### Win/Loss Discriminator — **INVALIDATED**

[`loader.py:84`](../../.claude/worktrees/elegant-heyrovsky-2f8815/studies/win_loss_discriminator/loader.py) does `merged.merge(td, on='date')` — the canonical bug. The trading_days frame brings `or_45min_range`, `candle_930_*`, `rth_*`, etc.

Three OOS survivors used `or_45min_range` (gate = 10:15). Of the 1572-trade tradeable pool, **1557 (99%) fire before 10:15**; on the OOS slice (n=500), **all 500 fire pre-10:15**. The filter is structurally unobservable for the trades it claims to apply to.

Causal re-run results — see [`rerun_win_loss_causal.py`](rerun_win_loss_causal.py) / [`results/rerun_win_loss_causal.csv`](results/rerun_win_loss_causal.csv):

| Rule | Original OOS (lookahead) | Causal OOS |
| --- | --- | --- |
| `or_45min_range >= 138` | n=221, WR 61.1%, PF 1.57, lift +7.7pp | **n=4, WR 25.0%, PF 0.25, lift −28.4pp** |
| `or_45min_range <= 93` | n=59, WR 40.7%, PF 0.75, lift −12.7pp | **n=1, WR 0%, PF 0.00** |
| `pd_close_pos ≤ 0.3832 AND or_45min_range ≥ 110.8` | n=105, WR 64.8%, PF 1.81, lift +11.4pp | **n=1, WR 0%, PF 0.00** |
| `is_fomc_week == True` (control, safe feature) | (study reported OOS −1.6pp p=0.459) | n=54, lift −1.55pp ✓ matches study |

The control rule reproduces the study's reported OOS result almost exactly under causal load — confirming the methodology is sound *for causally-valid features*. The IS/OOS gate is sound; it just cannot rescue a feature that is structurally unobservable, because the OOS pool carries the same lookahead.

### Morning Narrative — **CLEAN (REVALIDATED)**

[`phase5_composite_score.py`](../../.claude/worktrees/musing-almeida-bd8d95/studies/morning_narrative/phase5_composite_score.py) `compute_scores` uses 14 factors total across bullish/bearish/avoid. All trace to causally-safe inputs: `asia_direction`, `london_direction`, `pm_vs_london_disagree`, `gap_from_prior_close`, `on_close_above/below_pdh/pdl`, `prior_day_close_position` (→ `pd_was_trend_down`), `vixy_regime`, `is_fomc_week`/`is_opex_week`/`day_of_week_name`/`has_red_folder_news`, `overnight_direction`. Every one of these is in `SAFE_AT_OPEN` (mod=570) or derived from prior sessions.

[`build_features.py:175-222`](../../.claude/worktrees/musing-almeida-bd8d95/studies/morning_narrative/build_features.py) (multi-day structure) correctly lags `rth_*` via `.shift(1)` before any rolling/cummax — ATH, 20d high/low, week_high/low_so_far all use prior sessions.

`tools/morning_briefing.py` on master:
- Reads `or_5min/15min/45min_range` only as **historical reference data** for quintile cuts (lines 995-1012, 1263-1283) — these aren't today's intraday values fed into the score.
- `_compute_60d_regime` (line 1507) reads `rth_close` at `target_date`. In live 9:25 use this is harmless (today's row isn't populated yet, so the function falls back to prior date); a historical replay would technically pick up today's close, but this only feeds the matrix-play factors, not the bullish/bearish composite that was OOS-validated.

### Turtle Soup Reversal v0.3 — **CLEAN (REVALIDATED)**

[`run.py:100-106`](../../.claude/worktrees/sleepy-maxwell-2607d4/studies/turtle_soup_reversal/run.py) cherry-picks only 5 trading_days columns: `gap_from_prior_close_pct`, `prior_day_close_position`, `vixy_regime`, `has_pre_rth_news`, `day_of_week_name` — all `SAFE_AT_OPEN`. None of the `or_*` / `candle_930_*` / `rth_*` family is pulled.

The 5 confluence factors ([`v03_confluence.py:41-66`](../../.claude/worktrees/sleepy-maxwell-2607d4/studies/turtle_soup_reversal/v03_confluence.py)):

1. `prior_close_strong` — `prior_day_close_position ≥ 0.70`. **Safe** (prior-day stat).
2. `gap_flat` — `|gap_from_prior_close_pct| ≤ 0.1`. **Safe** (gap known at 9:30).
3. `mw_w3` — `macro_window == 3`. **Safe** (derived from entry timestamp).
4. `depth_5_15pt` — `sweep_depth_pts ∈ (5, 15]`. **Safe** — [`model.py:150,156`](../../.claude/worktrees/sleepy-maxwell-2607d4/studies/turtle_soup_reversal/model.py) computes depth = `wick_extreme − level_price` from the **sweep candle's** wick at sweep time.
5. `mss_confirmed` — `variant == 'reclaim_mss'`. **Safe** (variant of the entry signal, known at entry).

100% WR n=13 score-4 tier is still statistically tiny, but the methodology is causally sound.

### UFVG First-Touch — **CLEAN (REVALIDATED)**

The headline filter `touch_depth_pct ≤ 0.50` is computed at [`run.py:170-176`](../../.claude/worktrees/hungry-ramanujan-a819d8/studies/ufvg_first_touch/run.py) as `depth_pts / gap_size` where `depth_pts = top − touch_bar.low` (bullish) or `touch_bar.high − bottom` (bearish). This is the wick of the **single touch candle** at `touch_idx`, observable at that bar's close — not a session aggregate.

[`phase_b.py:101`](../../.claude/worktrees/hungry-ramanujan-a819d8/studies/ufvg_first_touch/phase_b.py) stratifies events into depth quartiles — fine because the underlying feature is causally observable.

### IFVG Reversal Tempo (`ifvg_reversal/` package) — **CLEAN (REVALIDATED)**

The whole pipeline ([`model.py`](../../ifvg_reversal/model.py), [`engine.py`](../../ifvg_reversal/engine.py), `detectors/{sweep,multi_tf_fvg,chop}.py`) never touches `trading_days.csv` or `daily_volume_profile.csv`. It works exclusively from 30s candles + `session_levels.csv` (with the `ACTIVE_SWEEP_LEVELS` filter for pre-RTH-known levels and the `swept_pre_rth != True` filter).

Key causal-correctness checks:
- Multi-TF resample uses `label='left', closed='left'`, then `entry_ts = inverted_at + TF_SECONDS[tf]` ([`model.py:148`](../../ifvg_reversal/model.py)) — entry is correctly placed at the inverting bar's *close*, not its open.
- `mark_inversions` only considers gaps with `created_at < ts` (strict-before) ([`multi_tf_fvg.py:186`](../../ifvg_reversal/detectors/multi_tf_fvg.py)). Per-session scoping prevents cross-day leakage.
- `engine._simulate_one_fixed_1r` walks forward with strict `> entry_ts` ([`engine.py:102`](../../ifvg_reversal/engine.py)). Soft-stop check `c.close > soft_level` runs on closed bars only.
- `_dealing_range` is `[09:30, at]` inclusive ([`model.py:188-189`](../../ifvg_reversal/model.py)) — RTH-so-far at sweep time, no future bars.
- Sweep level filter restricts to `ACTIVE_SWEEP_LEVELS` (`overnight_high/low`, `prev_day_high/low`) which are all known by 9:30; `swept_pre_rth != True` keeps only intact levels.

The 60-day cohort baseline (PF 1.69 / 50% WR / N=4) is too small to evaluate edge, but the model is causally correct.

The high-leverage deliverable is **[`tools/causal_features.py`](../../tools/causal_features.py)**. Future studies should import it instead of hand-rolling `trades.join(..., on='date')`.

---

## The bug pattern (mechanical)

```python
# DANGEROUS — trades.join takes today's full-session aggregate.
df = trades.join(vp, on='date')                      # poc/vah/val/va_width   (9:30-16:00)
df = trades.join(trading_days, on='date')            # may include rth_*, directional_changes_30m,
                                                     # max_drawdown_from_open, max_drawup_from_open
```

The values are computed from the same calendar day's RTH session. For a trade firing at 9:32, the joined `poc` is what the session's POC ends up being at 16:00 — a future value at trade time.

### What's actually causal vs contaminated

| Window | Available at | Examples |
| --- | --- | --- |
| Prior day / overnight | 9:30 sharp | `prev_day_*`, `asia_*`, `london_*`, `6am_*`, `overnight_*`, `gap_*`, `prior_day_type`, calendar/news, vixy_prior_close, **yesterday's POC/VAH/VAL via `load_lagged_vp()`** |
| First 1m RTH candle | 9:31 | `candle_930_range/body/direction` |
| Opening Range 5m | 9:35 | `or_5min_*`, `fvgs_first_5min*` |
| Opening Range 15m | 9:45 | `or_15min_*`, `fvgs_first_15min*`, `macro_1_*` |
| Macro 2 | 10:00 | `macro_2_*` |
| Opening Range 45m | 10:15 | `or_45min_*` |
| Macro 3 | 11:10 | `macro_3_*` |
| Macro 4 | 13:50 | `macro_4_*` |
| **REFUSE** — full-session aggregate | 16:00 | `rth_close/high/low/range`, `directional_changes_30m`, `max_drawdown_from_open`, `max_drawup_from_open`, today's POC/VAH/VAL/va_width/rth_volume |

`tools/causal_features.py` codifies this exhaustively.

---

## Phase 1 — canonical helper

`tools/causal_features.py` ships with 18 passing unit tests (`tools/test_causal_features.py`). Public API:

- `load_causal_features(trades, include=None)` — joins `trading_days.csv` features; NaN-masks any time-gated column for trades whose `mod` is below the gate; **refuses** to load any column in `CONTAMINATED`.
- `load_lagged_vp(trades)` — adds `poc_lag1`, `vah_lag1`, `val_lag1`, `va_width_lag1`, `vol_lag1` (yesterday's RTH session VP).
- `load_session_levels(trades, names=None)` — reads `session_levels.csv`, parses each level's `available_time`, masks values for trades before that time.

Every future trade-level study should import from this module. Hand-rolled `trades.join(..., on='date')` is the bug surface.

Tests cover:

- 9:32 trade gets `or_15min_high = None`
- 10:00 trade gets `or_15min_high` populated, `or_45min_range = None`
- 9:30 sharp trade gets `candle_930_range = None` (gate=9:31)
- All SAFE_AT_OPEN features are available at 9:30
- `load_causal_features(include=['rth_close'])` raises ValueError
- `load_lagged_vp` returns d-1's POC, not d's
- `load_session_levels(names=['or_high'])` masks pre-9:45 trades to None

---

## Phase 2 — per-study audit

Full per-(study, feature) classification in [`results/audit_log.csv`](results/audit_log.csv). Highlights:

### Priority 1 — `vp_targets` and `discovery_2R_hits` (INVALIDATED)

The composite_vp study already established `vp_targets` is dead. [`rerun_vp_targets_causal.py`](rerun_vp_targets_causal.py) reproduces the 4-bucket breakdown side-by-side ([results/vp_causal_v4_buckets.csv](results/vp_causal_v4_buckets.csv), [results/headline_compare.csv](results/headline_compare.csv)):

```
                          n_vp==0  n_vp==1  n_vp==2  n_vp>=3   (OOS hit_2R%)
today-VP (LOOKAHEAD):       32.94    53.46    62.03    94.12      ← +18pp gradient
lag-1 VP (CAUSAL):          44.20    44.76    44.51    26.67      ← noise, base ≈ 44%
```

The "magnet" pattern is **not real**. The bug introduced a strong reverse-causality signal: trades that hit 2R touched the POC/VAH/VAL on the way; trades that failed didn't; the regression backwards from outcome to feature looks like a +60pp gradient.

`discovery_2R_hits/run.py` has two additional contamination sites beyond the VP join:

1. **`range_regime`** (line 184) — `pl.col('rth_range') > pl.col('rth_range_5d_avg') * 1.25` uses today's full-session range. `range_regime` cannot be computed at trade time. Any downstream study citing `range_regime` (notably `higher_R_targets`, which calls range_regime "the trusted hit_5R signal +11.9pp OOS causal") is INVALIDATED.
2. **`or_*_state` and `match_930_dir`** (lines 137, 155-162) — time-gated features without `mod` masks. Trades at 9:30 sharp inherit values that haven't been observed yet.

### Priority 2 / 3 — VP-stack contamination in studies whose core is clean

`htf_nesting`, `speed_of_move`, `candle_930_anatomy`, and `sweep_fvgc` all join `daily_volume_profile.csv` on date and compute "n_vp_targets" cross-cells. The cross-cells are CONTAMINATED. The **core findings** (HTF FVG nesting, bars-to-1R speed, 9:30 range_z, sweep-then-FVGC short asymmetry) are *independent* of VP and survive the audit. Memory entries should be amended:

- `htf_nesting`: nested_15m headline survives. Drop the Q5 VP-stack cell from playbook usage.
- `speed_of_move`: bars_to_1R≤12 finding survives. "VP×fast → 94.7% hit_2R OOS" claim is INVALIDATED.
- `candle_930_anatomy`: range_z≤-1 finding survives. "VP×rule → 65.4% hit_2R OOS" claim is INVALIDATED.

### Priority 3 — already-killed studies with contamination present

`naked_vp`, `va_width_regime`, `sweep_fvgc` all concluded null. Contamination is present (via the same VP join or via `va_width`) but does not change the verdict; if anything the kill is reinforced.

### Priority 4 — dead-end studies (skim verdict)

`ath_availability`, `pd_50pct_level`, `prior_day_type` all clean. Their null verdicts are trustworthy.

### Studies whose source isn't on master

These memory entries reference work that does not appear in `git log --all`:

- `studies/morning_narrative/` + `tools/morning_briefing.py` operational tool
- `studies/turtle_soup_reversal/`
- `studies/win_loss_discriminator/`
- `studies/ufvg_first_touch/`
- `ifvg_reversal/` package (tempo v0.3.1)

`morning_briefing.py` *does* exist (124KB) but its features and scoring logic need a dedicated audit pass — this audit did not open it. The Win/Loss Discriminator's memory entry advertises `or_45min_range` as a survivor, which is a 10:15-gated feature; for trades firing earlier this is structurally similar to the vp_targets bug. **Treat that study as suspect until its run.py can be audited.**

---

## Phase 3 — re-run of `discovery_2R_hits` + `vp_targets`

See [`rerun_vp_targets_causal.py`](rerun_vp_targets_causal.py) and result CSVs in [`results/`](results/). The conclusion is unambiguous: under strictly causal lag-1 VP, **n_vp_targets is statistical noise**. The bucket hit-rates are flat (44.2 / 44.8 / 44.5 / 26.7%) against an OOS base of 44.3%. No threshold or aggregation window of yesterday's-or-earlier VP shows any usable lift.

The Composite-VP study already attempted 5d/10d/20d rolling composites and found none beat the +3pp kill floor. Combined with this pass: **there is no version of `n_vp_targets` that survives strict causal evaluation.** Stop building on this feature.

---

## Phase 4 — guidance going forward

1. **All new trade-level studies must use `tools/causal_features.py`.** Hand-rolled joins on `date` are forbidden.
2. **Stop using these CSVs**: `data/levels/trades_with_vp.csv` and any reuse of `trades_with_levels.csv` for VP/rth_* columns. They were built without lagging.
3. **Re-validate any "passes" that depended on `range_regime`** — the feature is uncomputable causally. Either replace with `(or_45min_range > rolling_avg)` after 10:15, or drop the regime concept entirely.
4. **Audit the missing studies on their respective branches** before treating any of their findings as playbook-ready. Especially `win_loss_discriminator` (`or_45min` filter) and `morning_briefing.py` (composite score over OR/range features).
5. **For partially-contaminated studies**: keep the core finding, drop the cross-cell. Update memory entries (this audit does so for the ones whose source was readable).

---

## Files written by this audit

- [`tools/causal_features.py`](../../tools/causal_features.py) + [`tools/test_causal_features.py`](../../tools/test_causal_features.py) — canonical helper + 18 passing tests
- [`studies/lookahead_audit/analysis.md`](analysis.md) — this file
- [`studies/lookahead_audit/tools_causal_features_v1.md`](tools_causal_features_v1.md) — design doc
- [`studies/lookahead_audit/rerun_vp_targets_causal.py`](rerun_vp_targets_causal.py)
- [`studies/lookahead_audit/results/audit_log.csv`](results/audit_log.csv)
- [`studies/lookahead_audit/results/revalidated_results.csv`](results/revalidated_results.csv)
- [`studies/lookahead_audit/results/vp_causal_walk_forward.csv`](results/vp_causal_walk_forward.csv)
- [`studies/lookahead_audit/results/vp_causal_v4_buckets.csv`](results/vp_causal_v4_buckets.csv)
- [`studies/lookahead_audit/results/headline_compare.csv`](results/headline_compare.csv)
