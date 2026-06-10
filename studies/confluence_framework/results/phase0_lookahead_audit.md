# Phase 0 — Look-ahead audit of legacy analyses

Date: 2026-06-09. Auditor: Track A session (Claude Code).
Scope: legacy `analysis/` code, the specific claims named in the program brief, and
incorporation of the existing `studies/lookahead_audit/` Pass 1+2 verdicts.

Verdict vocabulary: CLEAN / LOOK-AHEAD / SELECTION-BIASED / UNVERIFIABLE / NOT-FOUND.

## 1. Claims named in the program brief

| Brief reference | Status | Verdict |
|---|---|---|
| `analyses/15m_candle_behavior/` ("100% continuation after touch") | Directory does not exist anywhere in repo; claim string not found by grep | NOT-FOUND |
| `analyses/liquidity_levels_hit_prob/` ("93% gap fill") | Directory does not exist; no "gap fill" claim found. Closest match: `data/levels/analysis.md` "NWOG flat-gap Monday = 93% hit rate" (level-penetration base rate, different claim) | NOT-FOUND |
| `analyses/c1_liquidity_sweeps/c1_liquidity_sweeps.py` | Does not exist | NOT-FOUND |

The brief was evidently written against an assumed repo layout. The actual legacy
analysis code lives in `analysis/` (singular) and contains permutation tests, audited below.

## 2. Legacy `analysis/` permutation studies

### `analysis/permutation_test.py` — single-factor permutation screen
**Verdict: LOOK-AHEAD (partially) + stale-era data.**
- Merges `trading_days.csv` on date (`tradeable.merge(td, on='date')`), exposing
  full-session aggregates. Headline factors `wide_45min_or` / `tight_45min_or` use
  `or_45min_range`, which is knowable only at 10:15 ET — but the trade pool fires
  mostly before 10:15. This is the exact structural flaw that killed
  `win_loss_discriminator` v1 (Pass 2: n=221/61.1% WR collapsed to n=4 under causal masking).
- Factors that are SAFE_AT_OPEN per `tools/causal_features.py` (prior_day_*, gap_*,
  overnight_*, calendar) are mechanically fine, but the result set was computed on the
  1,572-trade 30-month era file and must be re-derived before reuse.

### `analysis/combo_permutation_test.py` — 2/3-way combos
**Verdict: LOOK-AHEAD for all headline survivors.**
- 219 combos "survive" BH FDR at q<0.10, but the entire top of the table hinges on
  `wide_45min_or` (e.g. #1 macro_w1+overnight_down+wide_45min_or, n=31, 83.9% WR).
  These are conditioned on information unavailable at entry. None may be reused as
  confluence factors without causal re-derivation under the 10:15 gate.

### `analysis/results/*` (summary_table.csv, combo_top_results.txt)
**Verdict: do not cite.** Computed on the 30-month era file with contaminated joins.

## 3. Prior `studies/lookahead_audit/` verdicts (Pass 1 2026-05-21, Pass 2 2026-05-22) — adopted

| Study | Verdict |
|---|---|
| vp_targets, discovery_2R_hits, higher_R_targets, win_loss_discriminator v1 | INVALIDATED (look-ahead) |
| htf_nesting, speed_of_move, candle_930_anatomy | Core CLEAN, VP cross-cells INVALIDATED |
| va_width_regime, naked_vp, sweep_fvgc | Kill verdicts unchanged (already null) |
| morning_narrative, turtle_soup v0.3, ufvg_first_touch, ifvg_reversal pkg, or_hl_play, or_width_predictor, low_sweep_confluence, ath_availability, pd_50pct_level, prior_day_type, composite_vp | CLEAN |

## 4. Machinery audit — what Phase 2 may reuse

| Machinery | Verdict | Notes |
|---|---|---|
| `tools/causal_features.py` (+18 unit tests) | CLEAN | Time-gated loader; refuses contaminated columns; `load_lagged_vp` is the only safe daily-VP path. **Primary reuse target.** |
| `data/levels/session_levels.csv` (+ builders) | CLEAN (mechanism) | Carries `available_time` column; `load_session_levels()` masks values pre-availability. Level values themselves are prior-session/overnight facts. |
| `studies/near_miss_draw/tagger.py` | CLEAN (C1 path) / SELECTION-BIASED (C3) | C1 gates entry strictly after `near_miss_confirmed_time` — causal. C3 ("aligned, no time gates", 57.2% n=905) has no entry-time gate: trades before the near-miss confirm are tagged with a future event. Reuse only the C1-gated path. **Era caveat:** results computed on the clobbered 2024-26 / 8:30-window baseline — must re-derive on canonical 8-yr file. |
| `studies/or_sweep_state/run.py` state machine | CLEAN mechanism, REVERIFY at reuse | Sweep detection is post-OR-formation wick logic (same machinery validated in or_hl_play audit). Per-trade tagging must be re-checked to confirm sweep events used are strictly pre-entry when generalized in Phase 2C. Results era: 2.5yr (580 days), not 8yr. |
| `fvgc/volume_profile.py` daily VP join | LOOK-AHEAD unless lag-1 | The original repo-wide bug pattern. Only `load_lagged_vp()` permitted. |

## 5. Standing rule (inherited, re-affirmed)

Any feature joined from `trading_days.csv` must come through `load_causal_features()`
(time-gated), any daily VP through `load_lagged_vp()`, any level through
`load_session_levels()` honoring `available_time`. Direct date-joins are banned in
this study.
