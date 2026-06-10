# Session Path Atlas (Track B) — analysis

**Status: COMPLETE (2026-06-09).** Descriptive atlas of NQ 9:30–10:15 ET behavior
over 2,148 sessions (2018-01-02 → 2026-05-21). No entries, no P&L — calibrated
probabilities only. Notion: synced live (Track B page in Backtest Projects DB);
no manual import pending.

Deliverables: [results/ALMANAC.md](results/ALMANAC.md) ·
[results/PRE_SESSION_LOOKUP.md](results/PRE_SESSION_LOOKUP.md) ·
[results/DEFINITIONS.md](results/DEFINITIONS.md) ·
part1_base_rates.csv (113 stats) · part1_distributions.csv ·
part2_conditionals.csv (1,140 cells) · part3_archetypes.csv ·
part3_transitions.csv · test_ledger.csv (1,221 logged tests: 113 + 928 + 180;
**separate file** from Track A's ledger, same column discipline adapted to
probabilities).

## 1. Method

- Unit of analysis = session. Universe = trading_days.csv ∩ 30s-bar coverage
  (≥85/90 RTH bars, ≥90% ON bars, lag-1 ATR available): 2,148 kept, 14 excluded
  (results/cache/excluded_sessions.csv). Includes half-days that pass coverage.
- One cached feature table (results/cache/session_table.parquet, one row per
  session); Parts 1–3 are groupby operations on it. Reuses fvgc/context/
  (Track A's point-in-time library): bar loader, level table + pre-RTH sweep
  flags, lag-1 ATR14. Frozen fvgc/model.py and engine.py untouched.
- Spot-check (results/spotcheck.md): full-table OR5/OR15/open cross-check vs
  the independently built trading_days pipeline — 0 mismatches in 2,148×5
  fields; 10 random sessions recomputed with independent code — 0 mismatches.
- All definitions frozen in DEFINITIONS.md before outcomes were computed;
  conditioner bucket edges chosen on conditioner marginals only.

## 2. Null model

Per-session bar shuffle (500 resamples; seed 20260609): bars decomposed into
(high−open, low−open, close−open) offsets, order shuffled, path rebuilt chained
on closes from the real 9:30 open. Preserves per-bar volatility, bar shapes,
and the session's NET drift; destroys ordering. Important consequence: the null
is not a driftless random walk — it answers "does the *sequencing* of this
session's bars matter beyond its volatility and net move?"

Results (actual vs null, pooled):
- OR15 ≥1 side taken: 93.9% vs 97.3% → reality breaks *less* than chance.
- OR15 both sides: 13.6% vs 23.5% → STRUCTURAL, sign-consistent 8/8 years.
- Return to OR mid after break: 40.6% vs 52.4% → STRUCTURAL, 8/8 years.
- W1 extreme holds: 86.5% vs 76.5% → STRUCTURAL.
- Extension ≥0.25 ATR: 19.1% vs 24.6% → STRUCTURAL (lower than chance).
- W1 dir → net dir: 73.3% vs 70.4% → weak, sign-consistent 7/8 (2024 even).
- Every named-level touch stat, every distance bucket: within ~1pp of null.

One coherent story: **NQ mornings are more one-sided than a vol-matched random
path — they pick an edge early, hold the break, and don't ping-pong — but
nothing about WHICH levels get touched goes beyond distance × volatility.**

## 3. Verdicts on the named claims

| Claim | Verdict |
|---|---|
| Phil: "one side of the OR is taken by 10:15 ≈ 94%" | **CONFIRMED, 93.9%** (n=2,148, CI 92.8–94.8); refers to the 15m OR; 5m OR = 99.8%. Strict-break vs touch-counts changes it by 0.05pp. Caveat: null is 97.3% — true but mechanical. |
| Ryley: "OR side taken within the 9:45/10:00 15m candles ≈ 97%" | **Framing equals the same stat** (OR15 breaks can only occur ≥9:45). Actual 93.9%, not 97% — claim 3pp high vs our 8-yr sample; recent-3yr 95.5% is closer. |
| Ryley: "6am H or L taken by the 10:00 candle ≈ 97%" | **CONFIRMED at 97.0%** (n=2,148) under repo definition (04:00–08:00 H/L) counting 8:00–9:30 pre-market sweeps; 95.7% by 10:00 strictly; literal 06:00–9:30 variant 93.4%/89.7%. **But** conditional on a side surviving to 9:30 untaken, RTH touch by 10:15 is only 45.1% (n=1,995) — the claim is true and nearly information-free for the open. |

## 4. Conditional layer summary (Part 2: 928 tested cells, BH q=0.10, ≥5pp)

87 cells MOVE; all but a handful are geometry: gap, open position, and draw
asymmetry move level-touch and sweep-order events exactly as the distance
ladder predicts. Non-geometric survivors worth noting: ON-range bucket on
extension (compressed 12.2% / expanded 26.4% vs 19.1%) and on ON-extreme touch
(83.0% / 64.8% vs 73.8%). Conditioners that move (almost) nothing: two-day
streak 0/30, prior-day type 2/50, day-of-week 1/50, and the entire OR-break
family (T1/T2/T3) has zero movers. Archetypes (Part 3): 0/180 tested cells
move (42 suppressed at n<30) — the morning's shape is not predictable at 9:30.

## 5. Stationarity honesty note

The pre-registered rule (yearly value inside pooled 95% CI in ≥6/8 years) is
miscalibrated at n≈2,150: the pooled CI is ±1pp while yearly sampling noise is
±5–6pp, so 99/113 Part-1 stats get flagged DRIFTING while only 10 show real
heterogeneity (chi-square p<0.01; reported per stat as `het_p`). Almanac labels
use the pre-registered verdict plus the companion test ("stable-in-practice").
Real drift exists and is consistent across stats: since 2022 mornings are more
two-sided (both-sides 10%→17%, ret-mid 32%→45%, W1-holds 90%→83%, TWO_WAY
archetype 10–11%→15–18%, CHOP 11–12%→3–6%; archetype×year chi² p=2.9e-05).
Direction of every structural deviation vs null is unchanged across all years.
Point-denominated stats (ext ≥10/20/30/50 pts) drift mechanically with NQ's
price level; use ATR-normalized versions across years.

## 6. What this data CANNOT support

- **Any "level X attracts price" claim beyond distance.** We cannot
  distinguish level identities at fixed distance; cells would need far more
  data and the pooled test already says no.
- **Pre-market prediction of the path archetype.** 0/180. Don't ask the atlas
  "what kind of day will it be."
- **Depth-3 conditioning** (e.g. gap × open-pos × asymmetry): typical cells
  fall under n=100 and the program cap is 2. Phil's template query (streak ×
  asymmetry) was answered as a labeled exploratory row only; its value tracks
  the single-conditioner asymmetry row.
- **Tails**: extensions ≥1 ATR, sub-30s sequencing, and any cell involving
  Asia-pair ping-pong (n≤41) are LOW-N or suppressed.
- **W1-sweep texture**: whether W1 swept a level adds ≤3pp to the 9:45
  transition read; finer sweep taxonomies (which level, rejection depth) were
  not pre-registered and are future work.

## 7. Future conditioners (not in this run's ledger)

VIX/VIXY regime; news-day flags (red-folder 8:30/10:00); FOMC/opex weeks;
distance-to-ATH; W1 sweep identity + rejection grade (needs pre-registration);
30s-FVG count in W1; prior-day archetype (self-conditioning of Part 3 labels).

## 8. Handoff

See results/HANDOFF_TRACK_A.md. Candidate scorecard factors (≥15pp movers, all
distance-mediated — promote only through Track A's IS/OOS process): gap bucket →
PD-touch; open-position × draw-asymmetry → sweep order; ON-range bucket →
extension. Caveat: Track A already found generic draw-map vocabulary flat at
the trade level; these are session-level touch probabilities, not trade edges.

## Caveats (verbatim constraints)

- Prior settlement is proxied by prior RTH close (documented in DEFINITIONS §5).
- "6am" levels follow the repo's 04:00–08:00 window; the literal 06:00–9:30
  variant is computed alongside wherever cited.
- The null preserves net session drift; deviations measure path-order structure
  only, not directional edge.
- Half-days passing coverage remain in the sample (e.g. 2022-05-30).
- First-sweep tie-breaks at 30s resolution use deeper-penetration ordering;
  ties are rare and unlogged individually.
- 2026 is a partial year (n=99) and excluded from stationarity votes.
