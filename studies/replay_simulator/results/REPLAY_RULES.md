# REPLAY_RULES.md — Track C deterministic replay rules

**Written 2026-06-09, BEFORE any replay run.** Every rule below is applied uniformly and
mechanically. Same inputs → byte-identical logs. Any edge case discovered during the run
that is not covered here gets a tiebreak APPENDED here (with a "added during run" stamp)
before the run is re-executed from scratch; no per-case judgment calls.

## 1. Program state this run inherits

- Track A returned a **NEGATIVE** result (zero FDR survivors of 58 narrative factors).
  Track C therefore runs in **reduced, benchmark-only mode** — no confidence tiers,
  no confluence scoring. The play either fires or it doesn't.
- Canonical baseline: `studies/confluence_framework/results/cache/baseline_trades_8yr.csv`
  (frozen copy of `logs/baseline_trades.csv.preserve`, FVGC v2.0.5, frozen 9:30 spec,
  2018-01-02 → 2026-05-15). n=4,542 tradeable (win/loss), 49.5% WR, PF 1.00.
  The stale 51.7%/n=1,572 numbers are never used.
- The working tree's `fvgc/constants.py` is dirty (8:30 experiment). The replay does NOT
  regenerate signals; it consumes the frozen canonical CSV only. `fvgc/model.py` and
  `fvgc/engine.py` are not touched, not imported, not re-run.

## 2. Cohort definition (the benchmark play)

A baseline row is a **benchmark trade** iff ALL of:
1. `fvg_created_at` time-of-day ∈ [09:29:30, 09:31:00] ET inclusive (exact bounds, as in
   Track A `harness.py: benchmark_mask`);
2. `direction == "short"`;
3. `variant != "protected_swing"`;
4. `outcome ∈ {win, loss}` (tradeable);
5. session passes the Track A session-quality rule (≥90% of expected overnight 30s bars;
   `studies/confluence_framework/results/cache/session_quality.csv`).

Everything else in the baseline file is logged **OBSERVED-NOT-TRADED** (context counts
only; no statistics are computed on it outside Part 3's pre-registered family).

## 3. Tiebreaks (pre-registered)

- **T-1 Ambiguous outcomes** (`outcome == "ambiguous"`, same 30s bar touches SL and TP,
  n=6 in baseline): EXCLUDED from the replay cohort and from all statistics, matching
  Track A's tradeable definition. They are counted in replay_log.csv signal counts.
- **T-2 Multiple benchmark-qualifying signals in one session**: all are taken, in
  timestamp order — the frozen engine already serializes entries; no per-day cap exists
  in the validated cohort. (Empirically the cohort has ≤2 per session; both count.)
- **T-3 Skip rows** (`outcome == "skip"`): never tradeable; counted as observed signals.
- **T-4 Session-table join misses** (replay session absent from Track B
  `session_table.parquet`, e.g. its excluded sessions): joined fields recorded as
  `unknown`; the trade still replays. Part 3 drops unknown rows from tests (counted in
  the part3 doc).
- **T-5 W1 fields used before 9:45**: any join field derived from the 9:30–9:45 window
  (`w1_dir`, `w1_high`, `w1_low`) is recorded in replay_log.csv for ALL trades for
  film-room/descriptive use, but is marked `w1_formed = False` when entry < 09:45:00 ET.
  Part 3 T1/T2 use only `w1_formed == True` rows (entry ≥ 9:45), per pre-registration.
  Benchmark trades all enter before 9:45 → for them W1 fields are "as later formed,
  shown for film-room context only", never claimed as entry-time information.
- **T-6 OR5 state at entry**: from Track B per-session break timestamps (`or5_t_hi`,
  `or5_t_lo`, seconds-of-day at 30s resolution): broke_high if `or5_t_hi` < entry-second,
  broke_low if `or5_t_lo` < entry-second, both → broke_both, neither → `forming` when
  entry < 09:35:00 else `inside`. Entries at exactly the break bar count as NOT yet
  broken (strict <) — conservative, information must pre-date entry.
- **T-7 Eras**: IS era = sessions ≤ 2024-02-12; recent era = sessions ≥ 2024-02-13
  (Track A `phase1_split.json` boundary). The brief's shorthand "2018–2023" / "2024+"
  maps to these exact boundaries so that replay numbers reconcile with Track A to the
  trade.
- **T-8 R accounting**: R = pnl / sl_dist from the frozen engine; at 1:1 RR this is
  exactly ±1.0 per trade (verified). No costs, no slippage — stated in every output.

## 4. Reconciliation assertion (must pass before anything else is produced)

The replayed benchmark cohort MUST equal Track A's re-derived numbers exactly:
- Full sample: n=83, wins=58 (69.88% WR), PF 2.85 (±0.005 rounding), avg R +0.398.
- IS era: n=41, wins=23 (56.10% WR).
- Recent era: n=42, wins=35 (83.33% WR).
`run.py` raises `ReconciliationError` and produces NO downstream artifacts on mismatch.

## 5. Part 2 Monte Carlo — pre-registered model choices

- **Account**: TPT PRO $50K. Config block in `run.py`; parameters verified against
  TakeProfitTrader help center 2026-06-09 (trail $2,000 on intraday unrealized P&L;
  trail stops at starting balance; floor locks permanently once reached — encoded with
  a RE-VERIFY-BEFORE-ACTING comment; no daily loss limit since Jan 2025).
- **Sizing**: contracts = floor($700 / (stop_pts × $2)) on MNQ, min 1. 0.5× rider: $350.
- **Intra-trade path model (CONSERVATIVE, pre-registered)**: the engine's MFE/MAE for
  WINS are tracked through end-of-day (post-exit contaminated) and are NOT usable;
  for LOSSES they stop at the SL-hit bar and ARE intra-trade exact. Therefore:
  - Loss trade path: unrealized ratchets UP by the trade's empirical pre-stop run-up
    (`mfe_r` drawn from the loss-side empirical distribution; raises the trailing floor
    if unlocked), THEN hits −1R (tests the floor). Worst-case ordering.
  - Win trade path: unrealized dips to FULL stop distance first (tests the floor — the
    stated conservative approximation), THEN closes +1R (ratchets HWM at exit).
  - A secondary OPTIMISTIC bound (wins never dip, losses never ratchet) is reported as
    a labeled row; truth lies between. Primary headline = CONSERVATIVE.
- **Bootstrap**: block bootstrap by calendar month (preserves trade clumping at ~1
  trade/month). Primary frequency basis = pooled 8-yr months. Labeled secondary =
  era-matched months (56% ↔ IS-era months, 83% ↔ recent-era months) since the regimes
  also differed in signal frequency (0.56 vs 1.55 trades/month).
- **Outcomes**: redrawn iid Bernoulli(target WR) per trade at 56% / 70% / 83%; stop
  sizes taken from the sampled months' actual trades (empirical distribution held fixed).
- **Paths**: 10,000 per scenario per sizing. Horizons 3/6/12 months.
- **"Safe buffer" definition**: EOD balance ≥ $52,000 = starting balance + full trail
  width (floor locked at $50,000 AND one full trail of cushion above it; also TPT's
  standard-withdrawal threshold). Median months to reach it, per scenario.
- **Termination**: intraday equity (balance + modeled unrealized trough/peak path)
  touches the trailing floor. Stop fills assumed AT the stop price (no slippage) —
  results are conservative in path shape, optimistic in fill quality; both stated.

## 6. Part 3 pre-registration (the ONLY new statistics in this track)

Family m=3, BH q=0.10 within family. Tested on ALL tradeable baseline signals
(n≈4,542 before session-quality filter; exact n in part3_hypotheses.md), NOT just the
benchmark cohort. Benchmark cohort reported as a labeled descriptive sub-row, no test.
Procedure per hypothesis: IS first → ONE confirmatory OOS look → exact binomial p vs
the relevant cohort base rate; no sub-slicing, no variants, no interactions; all
results reported regardless of direction. All 3 ledgered BEFORE any is computed.

- **T1 — W1 alignment.** Cohort: entries ≥ 09:45:00 ET with known `w1_dir` ∈ {up,down}.
  Condition: trade direction matches w1_dir (long↔up, short↔down). PRIMARY TEST:
  WR(aligned) vs the all-≥9:45 cohort base rate (exact binomial). Counter-W1 row
  reported alongside.
- **T2 — W1-extreme stop protection.** Cohort: entries ≥ 09:45:00 ET, known W1 extremes.
  Condition: model stop strictly beyond the W1 extreme (short: sl > w1_high;
  long: sl < w1_low). PRIMARY TEST: WR(protected) vs the same cohort base rate.
- **T3 — Overnight-range expansion.** Cohort: ALL tradeable entries with known
  `on_bucket`. Buckets = Track B session-table terciles (`on_bucket` ∈ {expanded,
  normal, compressed} — edges were set in Track B from conditioner marginals, never
  from outcomes). PRIMARY TEST: WR(trades on expanded sessions) vs the all-entries
  base rate. Compressed and normal rows reported alongside.
- **Descriptive-only, ledger-exempt**: OR5-contradiction state at entry (w1_dir up AND
  or5 low already broken before entry, or mirror), entries ≥ 9:45 only; WR/n per state,
  labeled LOW-N EXPLORATORY. No p-values.

Survival labeling: a hypothesis that passes IS (q<0.10 within family after BH on the 3
IS p-values) AND the single OOS confirmatory look (same-direction effect, p<0.05) is
labeled **VALIDATED — FORWARD-TEST NEXT**; it still enters no playbook from this run.

## 7. Output framing rules

- Replay outputs are **operational characteristics** of already-validated trades —
  never new evidence of edge.
- Any apparent improvement noticed anywhere goes to
  `results/OBSERVATIONS_FOR_RESEARCH_QUEUE.md` as an untested hypothesis. Acted on: never.
- Every probability carries (n=…). The 56%-regime numbers and the frequency finding get
  the same prominence as favorable numbers.
