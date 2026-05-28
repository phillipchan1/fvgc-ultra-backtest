# Research Prompt: Swept-Level FVGC Break-&-Retest — Cohort Mining

> Paste-ready brief for a research run. Goal: find the highest-expectancy
> tradeable subset of FVGC continuation signals, conditioned on liquidity
> sweeps, break-and-retest structure, magnet levels, and market regime —
> then rank the contributing factors and validate the winning cohort
> out-of-sample.

---

## 1. Objective

Mine for the **best cohort**: the subset of FVGC continuation signals with the
strongest, most robust expectancy when conditioned on the factors below. Then
**rank every factor by marginal contribution** so we know which carry the edge
and which are noise, and **OOS-validate** the frozen cohort.

Final deliverable: a frozen cohort definition (PF / expectancy-in-R / win rate /
frequency), an ordered factor-importance table, an out-of-sample verdict, and a
one-paragraph mechanism-grounded conclusion on whether the thesis is real and
frequent enough to trade.

## 2. Core thesis

An FVG that forms at a **recently-swept level**, then **breaks and retests** that
level as new structure, with an **untested magnet level within reach** as a
target, has materially higher continuation expectancy than baseline FVGC — and
this edge is strongest when **aligned with the prevailing regime**. Falsify or
confirm.

## 3. What already exists — REUSE, do not rebuild

- **Signals & sim:** `fvgc/model.py` (`generate_signals`), `fvgc/engine.py`
  (`simulate_trades`, `summarize_results`). Outcomes already include MFE/MAE in
  pts & R and `hit_1R…5R` with `bars_to_XR`.
- **Variants** (`fvgc/model.py:166`): `bos` (first close-through = break of
  structure), `ifvg`, `no_fvg`, `protected_swing`. Cascading taps
  (`model.py:390`) = the retest mechanic.
- **Levels:** `data/levels/level_registry.py` — ~15 session levels + HTF FVGs
  (15m/1H/4H/Daily via `build_htf_fvgs.py`, each with direction/top/bottom/mid/
  `bars_old`). Sweep detection today is pre-RTH only (`swept_pre_rth`,
  `build_session_levels.py:40`).
- **Per-trade enrichment:** `data/levels/enrich_trades_with_levels.py` — home for
  all new per-signal features.
- **Volume profile:** `fvgc/volume_profile.py` returns `poc/vah/val/va_width`
  (70% VA). Prior usage: `studies/volume_profile_confluence/`, `studies/vp_targets/`.
- **VWAP:** exists only as a documented play (`playbook/plays.json:284`,
  "VWAP Continuation", session-anchored from 9:30, PF 4.61, EV +0.73R, n=313,
  8yr-revalidated) — NOT a computed feature. Borrow that exact definition.
- **Reclaim vs non-reclaim & FVG locality:** already toggled in
  `studies/breakout_continuation/run.py` (`sweep_reclaims`, `fvg_locality`).
  **Diagnose this study first** — it's a v1 of the thesis; state what it found
  and why it isn't a tier-1 play before extending.
- **Touch / untested machinery:** `data/levels/study_level_hit_rate_45min.py`
  detects which 15-min macro window a level is first touched in — basis for a
  virgin-level feature.
- **Regime:** `studies/prior_day_type/` (joins `prior_day_type` from
  `data/trading_days/trading_days.csv`); `regime_breakdown` phase in
  `studies/multi_cell_confluence/run.py`; VIXY-based vol regime wired in (per the
  VWAP play); gap-direction & `above_open` in `study_level_hit_rate_45min.py`.
- **Study scaffolding:** copy `studies/_template/`; multi-phase orchestration
  pattern in `studies/multi_cell_confluence/run.py`; train/test + early/late
  split harness in `studies/nq_pf_wr_occ_iter/search_pf_wr_occ_iter7_auto.py`;
  significance gates in `analysis/permutation_test.py` and
  `analysis/combo_permutation_test.py`.
- **Data:** `data/consolidated/nq-front-month.ohlcv-30s.csv` (canonical NQ 30s);
  extended history available for OOS.

## 4. Net-new features to build (post-hoc, in `enrich_trades_with_levels.py`)

> All dynamic features (VWAP, developing POC, touch counts) must be computed
> **as of the signal bar — no full-session lookahead.**

### 4.1 Intraday sweep + recency
Generalize pre-RTH sweep logic to intraday. Per signal's FVG:
- `swept` (level was wicked past + closed back before the FVG formed)
- `bars_since_sweep` → buckets 0–5 / 5–15 / 15–60 / >60
- `swept_level_provenance` (categorical): PDH/PDL, session H/L, swing, HTF-FVG,
  OR, etc. **VWAP/POC excluded from sweep provenance** (see §6).

### 4.2 Time break→retest
- `bars_break_to_retest` = bars from the structural break (first close-through of
  the swept level / BOS) to the FVGC entry candle. Bucketed; expect a
  **sweet-spot curve**, not monotonic. Distinct from post-entry `bars_to_XR`.

### 4.3 Next-level magnet (target)
- `dist_to_next_untested_level` past entry in trade direction, normalized two
  ways: `/ fvg_size` and `/ ATR`.
- `clean_runway` (bool): no opposing level between entry and that target.
- Magnet universe (see §5).
- Test the magnet **both as a target** (does a near level lift realized R?) **and
  as a filter** (does the setup only work with clean runway?).

### 4.4 Location vs VWAP / value area
- VWAP position: above/below, signed distance in pts; encode the proven
  **R0 ≥ 10 NQ pts** idea (entry-to-VWAP distance).
- Value-area position: inside VA / at VAL / at VAH / outside.
- Test as filter and as target.

### 4.5 Level-state qualifiers (apply to whichever level the FVG sits at)
- `virgin_this_session` / `touch_count` (first-touch vs Nth-touch reaction).
- `reclaim_vs_reject` (post-sweep close-back-through = reclaim → fuel).
- `level_age` (`bars_old` for HTF gaps; test as a curve).
- `confluence_stack_count` (ordinal: # distinct levels coinciding in the FVG zone).

### 4.6 Nested HTF-gap factor
- `inside_htf_fvg` (bool) × `htf_tf` (15m/1H/4H/D) × `htf_untested` (bool) ×
  `position_within_gap`.
- **Critical split:** FVG inside an unfilled HTF gap *trading toward its far edge*
  (open runway → bullish for continuation) vs FVG *at the far edge* of an HTF gap
  (trading into HTF resistance → likely a fade). Separate these; do not blend.

### 4.7 Regime layer — three independent scales (do not conflate)
1. **Macro trend:** ONE boring proxy — price vs daily 20/50-EMA, or sign of MA
   slope, or daily higher-high/higher-low structure. Keep it simple (overfit-prone).
2. **Intraday trend-vs-balance day:** open vs prior VA, OR width, IB extension,
   price vs developing VWAP/POC. May matter MORE than macro for a continuation play.
3. **Volatility regime:** VIXY or realized-ATR percentile.

## 5. Magnet / level universe (for §4.3 target and §4.5 state)

**High value:** naked/unfilled HTF FVGs (untouched-since-creation), prior-day POC
& VAH/VAL, today's developing POC/VAH/VAL, opening range H/L (`or_high/or_low`),
initial balance (first-hour H/L), anchored VWAP.
**Medium:** NWOG/overnight gaps, round numbers (50/100-pt), weekly open / prior-week H/L.
**Low (flag, don't prioritize):** Fib / measured-move levels (high researcher DOF).

## 6. Mechanism discipline — level *role* matters

Levels play different roles; don't treat them identically:
- **Stop-liquidity pools** (session H/L, swings, HTF-FVGs, OR, round numbers) →
  eligible as **sweep fuel** (§4.1).
- **Mean-reversion magnets** (VWAP, POC) → eligible as **target** (§4.3) and
  **location filter** (§4.4), but **NOT as sweep provenance** — no stops rest on
  VWAP, so "sweeping VWAP" is a different mechanism.

## 7. Exit model (for R-multiples)

- Primary target = next untested magnet level (§4.3). Stop = structure
  invalidation (opposite side of the swept level / FVG).
- Also report fixed-R outcomes via existing `hit_XR` for cross-study comparability.
- Make the target rule explicit so every signal yields an R-multiple.
- Consider the validated VWAP-play exit nuance (BE move at +1R) as an exit variant
  to test.

## 8. Method — phased (mirror `multi_cell_confluence/run.py`)

- **Phase 0 — Prior-art diagnosis.** Read `studies/breakout_continuation/`;
  report findings and why it isn't tier-1.
- **Phase A — Baseline.** Plain FVGC continuation, no conditions. Record PF,
  expectancy (R), win rate, frequency. **Every cohort must beat this.** Also
  produce **regime-matched baselines** (baseline long-WR in bull days, etc.) for §10.
- **Phase B — Single-factor sweeps.** One variable at a time, bucketed, reporting
  **lift over baseline** + sample size: sweep recency, provenance, break→retest
  timing, magnet distance / clean-runway, VWAP/VA location, virgin/touch-count,
  reclaim-vs-reject, level age, confluence-stack, nested-HTF-gap (both splits),
  each regime scale, and `direction × regime`.
- **Phase C — Factor ranking.** Quantify each factor's MARGINAL contribution
  (expectancy lift holding others at baseline, or model-based importance). Output
  the ordered factor table — this is a primary deliverable.
- **Phase D — Tiered cohort mining.** NOT a flat brute-force. Take only Phase-C
  survivors; enumerate AND-combos among them; rank by composite (PF × WR × log n)
  but **report expectancy + frequency alongside** — never select on WR alone.
- **Phase E — OOS / robustness.** Train/test + early/late splits. The frozen
  cohort must hold OOS. Run the permutation/combo significance gate. Flag any
  cohort whose edge lives in one regime/era only.
- **Phase F — Regime & time-of-day breakdown** of the winning cohort.

## 9. The direction × regime test (the alignment hypothesis)

Test as an **interaction**, not a flat filter — the 2×2:

|              | Long setups   | Short setups  |
|--------------|---------------|---------------|
| Bull regime  | aligned       | counter-trend |
| Bear regime  | counter-trend | aligned       |

Hypothesis: the **aligned diagonal** beats the counter-trend diagonal.

## 10. Guardrails (non-negotiable)

- **Beat baseline on expectancy / PF**, not win rate.
- **R, not win rate** as the headline metric.
- **Sample floor** (e.g. N ≥ 30 per reported bucket); below = "inconclusive," not a finding.
- **Tiered search**, not flat combinatorial brute-force (rank singles → combine survivors).
- **Multiple-testing discipline:** winning cohort must survive a permutation null /
  Bonferroni-style haircut (`analysis/permutation_test.py`, `combo_permutation_test.py`).
- **Mechanism before metric:** every winning combo needs a one-sentence *why*
  (trapped stops + open runway + first-touch …). No mechanism → treat PF as noise.
- **Regime-matched baselines (beta vs alpha):** "longs work recently" is likely
  bull-market beta. Score aligned setups against *same-regime* baselines; only the
  excess is edge. **Demand the alignment effect appear in BOTH regimes** — bear
  sample is small (2018–2026 mostly up), so lean on 2018 / 2022 / selloff windows
  for the short side and flag the limited N.
- **No lookahead:** dynamic features computed as of the signal bar only.
- **OOS confirmation required** before any cohort is called an edge.

## 11. Outputs

- `studies/swept_fvgc_break_retest/analysis.md` — question, method, ordered
  factor-importance table, winning cohort(s) with PF/expectancy/WR/frequency, OOS
  table, regime breakdown, caveats.
- `results/` — JSON cohort definitions + per-cohort `trades_*.csv`.
- One-paragraph verdict: is the thesis real, which factors carry it (ranked), is
  it beta or alpha, and is the cohort frequent enough to trade.
