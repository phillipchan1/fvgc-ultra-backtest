# Study: Confluence Framework (Program Track A)

## Question
Does a point-in-time narrative/confluence framework (draw map, need proxies, session
state, HTF alignment) add measurable, OOS-validated edge on top of the frozen FVGC
v2.0.5 entry model — expressible as a sub-60-second human checklist?

Promotion bar: ≥65% WR or ≥2.0 PF on OOS with n≥30 and preserved score monotonicity.
Negative result is a valid outcome. Notion track page:
https://app.notion.com/p/37ae2f0e776081bc99fbd84b269a1f1d

---

## Phase 0 — What we actually know (2026-06-09)

### Canonical baseline decision
- `logs/baseline_trades.csv` is **not usable**: it has been clobbered by daily runs to a
  2024-01→2026-05 window AND was generated with the uncommitted 8:30 trading-window
  experiment in `fvgc/constants.py` (working tree is dirty: 9:30→8:30 on both
  `TRADING_WINDOW_START` and `FVG_START_TIME`; git HEAD remains the frozen 9:30 spec).
- **Canonical baseline adopted**: `logs/baseline_trades.csv.preserve`, frozen-copied to
  `results/cache/baseline_trades_8yr.csv`. Verified clean under the frozen spec:
  earliest FVG creation 09:30:30, entries 09:31–10:15 only, 2018-01-02 → 2026-05-15.
- Canonical stats: **n=4,542 tradeable, WR 49.49%, PF 0.997** (wins 2,248 / losses 2,294;
  skips 2,066, ambiguous 6 excluded). Per-year n: 2018=161, 2019=69 (thin), 2020-2026 = 565/557/839/582/656/785/328.
- The brief's "~1,572 tradeable, 51.7% WR / 1.1 PF" and "shorts 74.1% n=54" trace to the
  **original ~30-month era** of `baseline_trades.csv` (confirmed in
  `studies/fvgc_plays_off_930_candle/analysis.md`). All program numbers are re-based to
  the 8-yr canonical file. **Blind FVGC is a coinflip at 1:1 RR — the model only earns
  through context. That is the entire premise of this program.**

### (a) Surviving filters (re-derived, 8-yr, BH FDR q=0.10 across 21 Phase-0 tests)
See `results/phase0_survivor_audit.csv`; all tests in `results/test_ledger.csv` (phase 0).

| Cohort | n | WR | PF | p | q | Verdict |
|---|---|---|---|---|---|---|
| Opening-window shorts, no protected_swing | 83 | 69.9% | 2.85 | 0.0002 | 0.005 | **SURVIVES — program benchmark** |
| Opening-window shorts (all variants) | 109 | 63.3% | 2.25 | 0.004 | 0.031 | SURVIVES |
| Opening-window longs, FVG >10pt | 78 | 33.3% | 0.48 | 0.004 | 0.031 | SURVIVES as ANTI (knife-catch) |
| Opening-window longs, FVG ≤10pt | 65 | 63.1% | 1.73 | 0.034 | 0.180 | fails FDR — stays "candidate" |
| Opening-window all-dirs | 252 | 54.0% | 1.22 | 0.166 | 0.66 | not significant |
| Day-of-week (all 5 days; Thursday 50.4%) | 840–945 | 48.0–50.6% | 0.93–1.05 | ≥0.39 | ≥0.91 | **DEAD on 8yr** — 30-mo Thursday claim does not generalize |
| Thursday shorts | 458 | 52.6% | 1.10 | 0.19 | 0.66 | not significant |
| Macro windows W1/W2/W3, variants, direction | — | 47.8–50.7% | 0.93–1.06 | ≥0.22 | — | flat context splits |

Cohorts requiring tagger re-runs (near_miss_draw C1–C4, or_sweep_state play cells) were
**not** re-derived in Phase 0 — their published numbers were computed on the clobbered
2024-26/8:30-window file (near_miss) or a 2.5-yr sample (or_sweep). They are queued for
causal re-derivation inside Phase 2/3 where their taggers get rebuilt against the
canonical file anyway.

### (b) The benchmark play
**Opening-window FVG short, no-PS**: FVG created 09:29:30–09:31:00 ET (`fvg_created_at`),
direction=short, variant≠protected_swing, outcome∈{win,loss}.
**8-yr: n=83, WR 69.9%, PF 2.85, avg +0.40R per trade.** (~10 signals/yr.)
This is the cohort every Phase 3 factor must add marginal lift to, and the Phase 1
harness sanity target (exact reproduction required).
Known prior caveats (from study + memory): gap_large_down is an anti-confluence
(−16pp); same-day follow-up M1 shorts fail (PF 0.62); runner unlocks +1.3–1.5R/trade.

### (c) Legacy code safe to reuse
Full verdicts in `results/phase0_lookahead_audit.md`. Summary:
- **REUSE**: `tools/causal_features.py` (time-gated loader, 18 tests) — sole permitted
  path to `trading_days.csv`, daily VP (lag-1 only), and `session_levels.csv`
  (honors `available_time`).
- **REUSE WITH RE-VERIFICATION**: `near_miss_draw/tagger.py` (C1 gated path only — C3
  broad cohort is selection-biased), `or_sweep_state` machinery (verify pre-entry
  ordering when generalizing).
- **DO NOT CITE**: `analysis/` permutation results (single + combo) — headline survivors
  all hinge on `or_45min_range` (10:15 information applied to pre-10:15 trades); stale era.
- The brief's `analyses/15m_candle_behavior/`, `liquidity_levels_hit_prob/`,
  `c1_liquidity_sweeps/` and the "100% continuation" / "93% gap fill" claims **do not
  exist in this repo** (NOT-FOUND).

### Open question for Phil (Phase 0 gate)
1. Canonical baseline = `.preserve` (8-yr, frozen 9:30 spec) — confirm. Alternative is a
   fresh full regeneration (~long run, requires temporarily reverting the dirty
   constants.py); .preserve was used by all recent validated 8-yr studies, so I treat it
   as authoritative.
2. Benchmark = opening-window short no-PS (69.9%/2.85/n=83) — confirm this replaces the
   brief's stale "74.1% n=54".
3. 2018–2019 data is thin (n=161/69). Keep in sample (default) or exclude?

---

## Phase 1 — Splits, session quality, evaluation harness (2026-06-09)

Phil's Phase-0 gate decisions: baseline = `.preserve` 8-yr file; benchmark =
opening-window short no-PS; **no year-based exclusion** — instead a mechanical
session-quality rule (his amendment): exclude sessions missing >10% of expected
overnight/pre-market 30s bars (18:00→09:30 ET, 1,860 expected).

### Session quality rule
14 of 1,859 sessions removed (`results/cache/session_quality.csv`). By year:
2018=2, 2019=2, 2020=5, 2021=1, 2022=1, 2023=1, 2024=1, 2025=1. The removals are
informative: COVID circuit-breaker days (2020-03-16/17/18), **every post-DST-fallback
November Monday 2018–2024** (Sunday-evening bars missing — consolidation tz artifact),
day-after-Thanksgiving 2025. Zero benchmark trades lost. 2018–19 thinness is organic
(fewer ≥3pt FVGs), not data gaps — rule keeps those years.

### Split (recorded; OOS sealed until Phase 5)
- IS: 2018-01-02 → 2024-02-12, 1,291 sessions, 2,809 tradeable trades, base WR 47.67%
- OOS: **2024-02-13** → 2026-05-15, 554 sessions, 1,700 tradeable trades
- IS walk-forward folds (equal sessions): f1 2018-01-02→2019-11-22 (221 trades),
  f2 →2021-06-01 (800), f3 →2022-09-29 (958), f4 →2024-02-12 (830)

### Harness
`harness.py`: `evaluate()` → n, WR, PF, avg R, max consecutive losses, per-fold WR +
same-sign count, exact binomial p vs the split's own base rate; auto-appends every call
to `results/test_ledger.csv`; **OOS evaluation raises unless `allow_oos=True`**
(Phase 5 only). `bh_fdr_rewrite()` recomputes q-values ledger-wide.

### Sanity check — PASS
Benchmark reproduced exactly on program basis: **n=83, WR 69.9%, PF 2.85** (avg
+0.398R, max 4 consecutive losses).

### Pre-registered observation (logged before any Phase 3 work)
The benchmark is IS/OOS-asymmetric: IS-only = 56.1% WR / PF 1.26 (n=41, p=0.35 vs IS
base 47.67%), fold WRs 100/46.7/61.5/50.0 (n=3/15/13/10). Most of the pooled 8-yr
strength sits in the 2024+ window — i.e. partially a recent-regime phenomenon. Phase 3
marginal-lift tests use the IS benchmark honestly; Phase 5 interpretation must revisit
this asymmetry.

---

## Phase 2 — Point-in-time snapshot library (2026-06-09)

Built `fvgc/context/` (additive package: `htf.py`, `draws.py`, `snapshot.py`) and
`results/phase2_snapshots.csv`: **4,509 trades × 105 columns** (91 features + ids/targets).
Build: 98s total; HTF inventory = 40,518 15m FVGs, 10,669 1h FVGs, 18,707 level sweeps.

**Feature groups** (each carries a point-in-time justification in code):
- **A. Draw map** — 15 named levels (incl. derived `prev_close`, live-computed OR H/L)
  with distance, ATR-normalized distance, status (untaken / swept / swept_reclaimed);
  untaken-draw counts above/below (raw + within-1-ATR); `draw_asym_dir` (toward-minus-
  against trade direction); nearest-untaken-draw distance in R; `target_aligned`
  (nearest draw in trade direction sits at/beyond the 1R target); nearest unfilled
  15m/1h FVG above/below (untouched-since-creation definition, 14-day visibility cap);
  `nested_15m` (entry FVG mid inside a not-inverted same-direction 15m FVG).
- **B. Need proxies** — `need_v1` impulse grid (X∈{20,30,40}pts × Y∈{5,10}min toward an
  untaken draw); `need_v2_last_fvg` (no other unmitigated same-direction 30s FVG between
  leg origin and entry; leg origin = pre-entry session extreme); `need_v3` rejection
  grid (Z∈{10,15,20}pts × N∈{4,10}bars; NaN unless the grading window fully pre-dates entry).
- **C. Session state** — sweep count + first-sweep identity (prev_day_high 24%,
  prev_day_low 21% of sessions); OR state at entry (forming 1,337 / broke_low 1,176 /
  broke_high 1,147 / inside 663 / broke_both 186); opposing-HTF-FVG-inverted-today;
  macro window W1/W2/W3; **near-miss flags via reused `near_miss_draw/tagger.py`**
  (`scan_day` fed canonical bars; trade-level gate = confirmed_time ≤ entry, their C1
  logic; base rate 6.9% ≈ original study's 6.6%).
- **D. HTF alignment** — 15m/1h confirmed-swing structure (up/down/mixed + aligned
  flags); prior-day range position (premium/discount/above/below + aligned); gap class
  (flat <0.2 ATR) + gap size in ATR; lagged ATR14.

**Bugs found and fixed during QA** (documented per "hunt the bug first" rule):
1. `session_levels.csv` carries or_high/or_low rows with **NaN prices** (live-only
   levels) → OR features silently "unknown". Fixed: OR computed from 9:30–9:44:30 bars,
   exposed only from 9:45 (point-in-time), included in draw counts.
2. `nested_15m` initially used untouched-FVG containment → 0.1% true-rate (a nested
   entry is by definition inside the zone). Fixed to not-inverted containment → 5.5%.
3. Spot-check verifier itself had a direction-blind touch rule (bullish rule applied to
   bearish FVGs) — fixed; feature was correct.

**Spot check: 98/98 PASS** across 10 random trades (seed 42), independently re-deriving
level distances/status, untaken counts (incl. OR), or_state, macro window, gap, need_v1,
pd_zone, and the causality of nearest-15m-FVG (created-before-entry + untouched-before-
entry verified against raw 30s bars). `results/phase2_spotcheck.md`.

**Data-quality notes** (`results/phase2_quality_report.md`): missingness is structural,
not accidental — htf1h_nearest_above 36% NaN (no unfilled 1h draw within 14d),
need_v3_*_n10 23% NaN (grading window not yet closed at entry), nearest_untaken_dir 21%
NaN (no untaken draw in trade direction = itself informative). Definitional choices
logged: unmitigated FVG = untouched (draw/magnet semantics); nesting = not-inverted;
settlement proxied by prior RTH close; impulse legs RTH-only.

---

## Phase 3 — Single-factor screen, IS only (2026-06-09)

58 pre-registered factors × {longs, shorts, benchmark} = **174 tests** (all ledgered;
IS-only quantile cuts recorded: ATR p20=185.8 / p80=339.0). Selection bar: BH FDR
q<0.10 within the screen family + same-sign in ≥3/4 walk-forward folds + n≥30.

### Result: ZERO survivors.
- Best cell: `or_break_against` longs (56.9% vs 48.0% base, PF 1.44, n=253, p=0.0046)
  → q=0.66. Surviving BH at q=0.10 with this family needs p≈0.0006.
- **Robustness**: recomputing FDR excluding degenerate n<30 cells (family m=121):
  min q = 0.47 — the null is not an artifact of family construction.
- Global ledger check (197 tests, program-wide FDR): the only q<0.10 survivors are the
  **benchmark cohort itself** (Phase 0/1 entries). Nothing the narrative library
  produced beats multiple comparisons.

### Informative negatives (large-n, decisively flat on IS)
| Narrative hypothesis | Cells | Verdict |
|---|---|---|
| `target_aligned` (draw pulls price through TP) | longs 47.3% n=843 / shorts 46.6% n=839 | flat — does NOT matter |
| HTF structure alignment (15m & 1h) | 44.4–48.8%, n=405–441 | flat-to-negative |
| `nested_15m` | longs 46.4% n=69 / shorts 45.3% n=75 | flat on IS within this entry pool — the htf_nesting study's +25.8pp does not appear under this definition/cohort |
| `pd_zone_aligned` (premium/discount) | 44.4–47.5% | flat-to-negative |
| `htf15_toward_1atr` (HTF magnet toward trade) | ~47% both | flat |
| `opp_htf_inverted_today` | ~47% both | flat |
| `fvg_small` (≤10pt) on full pool | 47.5–48.6% n>1000 | the small-FVG edge is specific to the opening-window cohort, not general |

### Near-misses (sign-stable but far from significant — hypotheses only, NOT promoted)
- `or_break_against` longs 56.9%/1.44 (n=253, 4/4 folds) — fade-the-OR-break long;
  echoes or_sweep_state's "H-first → long fade" cell.
- Draw asymmetry is **direction-asymmetric**: helps shorts (asym_pos 52.2%, 4/4 folds),
  HURTS longs (asym_pos 45.0%; asym_ge2 43.6%) — same feature, opposite sign by side.
- `macro_w3` longs 54.1% (n=477) vs `macro_w1` longs 43.3% (n=448) — late-morning longs.
- `near_miss_c1` longs 56.2%/1.38 (n=96, p=0.13) — the best truly-narrative cell.
- `fvg_stale` (>15min) longs 59.1% (n=93).

### Marginal-value pass
Vacuous — no survivors to test over the benchmark (n=41 IS).

---

## Phase 4 — Framework construction (2026-06-09): NOT CONSTRUCTIBLE

The pre-registered rule is explicit: "Build candidate frameworks **from surviving
factors only**." With zero Phase-3 survivors there is nothing to compose; assembling
scorecards from near-misses would be exactly the threshold-relaxation that constraint
#6 bans. Phase 5 (one-shot OOS) is therefore vacuous — **no candidate is evaluated on
OOS** — and the program proceeds to a negative final report unless Phil directs
otherwise at this gate.

### Diagnostic addendum (Phil's gate request — `results/phase3_diagnostic_addendum.md`)
1. **Comparison target**: each factor vs its cohort's own IS base (longs 47.95% /
   shorts 47.39% / benchmark 56.10%), not the pooled 49.5%. Top factors shown both
   ways; intersected with the IS benchmark they show no marginal lift (e.g.
   asym_pos∩benchmark: 56.2% n=16 vs 56.1% base).
2. Top-10 by raw effect with n / raw p / q under both family definitions — in addendum.
3. **Positive control**: full-sample benchmark fires decisively through the harness
   (69.9% n=83 vs 49.48%, exact p=2.4e-04 — the only global-FDR survivor). On IS it
   does NOT fire (56.1% n=41, p=0.278) — its strength is OOS-era-concentrated
   (pre-registered Phase 1). **Power analysis: a TRUE 70%-WR factor at IS n=41 would
   survive this screen with only 27% probability; 80% power requires n≥95.**
   → The negative result is STRONG for common factors (n≥200), but the screen is
   structurally blind to rare, benchmark-sized cohort plays (n~40 in IS).
4. **Family sizes**: screen m=174 (clean m=121), ledger m=197. The best factor
   (or_break_against, p=0.0046) survives q=0.10 only in a family of m≤21; even a
   one-cohort-per-factor pre-registration (m=58) needs p≤0.0017. Null ≠ family bloat.
5. **Spot-check** draw_asym_dir + need_v2 vs raw bars on 3 random trades: 6/6 PASS.

**Scoped conclusion**: no COMMON narrative factor adds detectable edge to frozen FVGC
v2.0.5 on IS; rare cohort-plays below n≈95 are not addressable by this design and
remain an open class (the benchmark itself being the existence proof).

**Phase 4 gate decision (Phil, 2026-06-09):** close out with the negative report,
plus three additions: (1) elevate the benchmark time-concentration finding to a
headline + queue a stability follow-up study; (2) pre-register the single long-side
question in the hypothesis doc; (3) instruct Track C to run benchmark-only with a
56/70/83% WR sensitivity. All three delivered (see below).

---

## Phase 5 — OOS validation: VACUOUS BY CONSTRUCTION

Zero candidates were frozen at Phase 4, so nothing was evaluated on OOS. **The
2024-02-13 → 2026-05-15 window remains sealed** — no candidate, factor, or framework
from this program ever touched it. It is reusable by future studies at full strength.

---

## Phase 6 — Final verdict

**The narrative-confluence vocabulary tested here does not add measurable edge to
frozen FVGC v2.0.5 entries — with one scoping caveat and one headline by-catch.**

### Headline 1 (negative, the program's answer)
58 pre-registered point-in-time narrative factors (draw map, need proxies, session
state, HTF alignment) screened on 6 years of in-sample data across 174 tests: zero
survive BH FDR q=0.10 + fold stability. Decisively flat at large n: target alignment,
15m/1h structure alignment, premium/discount, HTF-FVG magnet proximity,
opposing-inversion state, draw counts. The harness was validated by a positive
control (the benchmark fires at p=2.4e-04 full-sample, sole global FDR survivor among
197 ledger tests).

### Headline 2 (by-catch, elevated per Phil): the benchmark is time-concentrated
Opening-window short no-PS: pooled 69.9% / PF 2.85 (n=83) **decomposes into IS
(2018→2024-02) 56.1% (n=41) vs implied ~83% (35/42) in 2024-02→2026-05.** The edge as
traded today is substantially a recent-regime phenomenon. Follow-up study
pre-registered in `results/FORWARD_TEST_PROTOCOL.md` §A (year-by-year + rolling-24m
with Clopper–Pearson 90% CI and pre-set interpretation rules).

### Scoping caveat (honest limit of the negative)
The screen had only **27% power** to detect a true-70%-WR factor at benchmark-like
size (IS n=41); 80% power needs n≥95. The negative is strong for common factors
(n≥200), structurally weak for rare cohort plays. Rare high-WR cells remain an open
class — the benchmark itself is the existence proof.

### Honest caveats
1. IS-era weakness is general: IS base WR 47.7% vs OOS-era-lifted pooled 49.5%; any
   factor whose edge is 2024+-only is invisible to this design by construction.
2. Several feature definitions are one of several defensible choices (unmitigated =
   untouched; nesting = not-inverted; impulse legs RTH-only; leg origin = pre-entry
   session extreme; near-miss = original tagger's single best per day). A different
   vocabulary could in principle score differently — but each choice was frozen
   before screening.
3. `need_v3` n10-grid and 1h-FVG features carry 23–36% structural NaN; their tests
   are correspondingly weaker.
4. The benchmark cohort definition itself was discovered in prior research on
   overlapping data; its pooled significance here is confirmatory, not de novo.
5. 2018–19 signal counts are thin (organic, not data gaps); fold 1 carries less
   information than folds 2–4.

### What this changes
- Pre-market narrative prep (marking draws, structure reads) should NOT be expected
  to upgrade generic FVGC entries — the during-session playbook keeps its focus on
  the specific validated cohort plays.
- The opening-window short stays the anchor play, but sizing should respect the
  56/70/83 regime uncertainty (Track C instruction issued).
- The long side of the opening window is the most promising unexplored territory
  (all top near-misses were longs-side) — one pre-registered forward question, §B of
  the protocol doc.
- The 2024+ OOS window is intact for future research.

### Deliverables
- `results/test_ledger.csv` — 197 tests, final BH q-values (program-wide)
- `results/phase0_survivor_audit.csv`, `results/phase0_lookahead_audit.md`
- `results/phase1_split.json`, `results/cache/session_quality.csv`
- `results/phase2_snapshots.csv` (+ quality report, spot-checks 98/98 & 6/6)
- `results/phase3_screen.csv`, `phase3_survivors.csv` (empty — meaningful),
  `phase3_diagnostic_addendum.md`
- `results/FORWARD_TEST_PROTOCOL.md` — pre-registered follow-ups with goalposts
- `results/HANDOFF_NQ_VP_LAB.md` — fvgc/context reuse + Track C instruction
- `results/EXECUTION_CHECKLIST.md` — not produced (nothing promoted; intentional)
- Notion track page: https://app.notion.com/p/37ae2f0e776081bc99fbd84b269a1f1d
