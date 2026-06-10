# Session Path Atlas — DEFINITIONS (frozen before computation)

Written 2026-06-09, BEFORE any outcome statistic was computed. Bucket edges for
conditioners were chosen by inspecting ONLY the conditioner's own marginal
distribution (documented per item) — never an outcome variable.

Track: B (Session Path Atlas). Companion to Track A (studies/confluence_framework/).
Test ledger: `results/test_ledger.csv` — **separate file** from Track A's ledger
(same column discipline, adapted to probabilities).

---

## 1. Data sources

| Input | Path | Notes |
|---|---|---|
| 30s bars | `data/consolidated/nq-front-month.ohlcv-30s.parquet` | NQ front-month, naive NY timestamps, loaded via `fvgc.context.htf.load_bars_30s`. 2018-01-01 → 2026-05-29. |
| Named levels | `data/levels/session_levels.csv` via `fvgc.context.draws.load_level_table` | carries `available_time` and `swept_pre_rth` per level |
| Day facts | `data/trading_days/trading_days.csv` | RTH OHLC, overnight stats, gap, calendar flags. 2018-01-02 → 2026-05-21 |
| ATR | `fvgc.context.draws.daily_atr14_lagged` | ATR(14) of RTH daily bars, **lagged 1 day** — known at 9:30 |

All times are America/New_York (naive). 30s bars are labeled by their LEFT edge:
bar `t` covers [t, t+30s) and its values are final at t+30s.

## 2. Session universe

One observation per session (date). A session enters the atlas iff:

1. It appears in `trading_days.csv` (canonical RTH day list, 2018-01-02 → 2026-05-21).
2. ≥85 of the 90 30s bars in [09:30:00, 10:15:00) are present.
3. Overnight coverage ≥90% of expected 30s bars in [18:00 prior calendar day, 09:30:00)
   — mirrors Track A's session-quality rule, recomputed here over the full range
   (Track A's cached file stops in 2025). Guards the trustworthiness of ON/Asia/
   London/6am levels.
4. Lag-1 ATR14 is available (≥5 prior sessions).

Exclusions are logged with reasons in `results/cache/excluded_sessions.csv`.

## 3. Time windows

| Name | Window (bar labels) | Known at |
|---|---|---|
| Analysis window | 09:30:00 ≤ t ≤ 10:14:30 | — |
| W1 | 09:30:00 – 09:44:30 | 09:45:00 |
| W2 | 09:45:00 – 09:59:30 | 10:00:00 |
| W3 | 10:00:00 – 10:14:30 | 10:15:00 |
| OR5 window | 09:30:00 – 09:34:30 | 09:35:00 |
| OR15 window | 09:30:00 – 09:44:30 (= W1) | 09:45:00 |

- "**by 10:15**" = within bars labeled ≤ 10:14:30.
- "**by the 10:00 candle**" (Ryley framing) = by the CLOSE of the 15m candle
  opening at 10:00, i.e. by 10:15:00 — identical to "by 10:15". The stricter
  variant "before 10:00" (bars ≤ 09:59:30) is reported alongside wherever the
  claim is tested.
- "**within the 9:45 and 10:00 15M candles**" = event time in [09:45:00, 10:15:00).
- `open_930` = open of the 09:30:00 bar. `close_1015` = close of the 10:14:30 bar.

## 4. Opening range — BOTH variants, always labeled

- **OR5**: high/low of bars 09:30:00–09:34:30. **OR15**: high/low of bars
  09:30:00–09:44:30. Mid = (H+L)/2.
- **Side taken / broken**: a bar strictly AFTER the OR window with
  `high > ORH` (high side) or `low < ORL` (low side). **Strict inequality**:
  a later bar printing exactly the OR extreme is a retest, not a break.
  (Named-level touches in §5 use ≥/≤ per the repo sweep convention; the
  difference is intentional and a `>=` sensitivity for the headline OR stat is
  reported once in analysis.md.)
- First-break time per side = label of first qualifying bar. Extension beyond
  the first-broken boundary = max excursion past it by 10:14:30 (pts and /ATR).
- **Return to OR midpoint** after first break: any bar after the first-break
  bar with `low ≤ mid` (after high break) or `high ≥ mid` (after low break).

## 5. Named levels (the atlas draw set) — all knowable at 9:30

11 levels, prices from `session_levels.csv` (windows as established in
`data/levels/build_session_levels.py`):

| Level | Formation window | Untaken-at-9:30 source |
|---|---|---|
| prev_day_high / prev_day_low | prior RTH session | `swept_pre_rth` (full ON window check) |
| prev_close | prior RTH close (settlement proxy — documented approximation; derived as `rth_open − gap_from_prior_close`) | computed here: untaken iff prev_close ∉ [ON low, ON high] |
| overnight_high / overnight_low | 18:00 prev → 9:29:30 | always untaken at 9:30 (they ARE the ON extremes) |
| asia_high / asia_low | 19:00 prev → 02:00 | `swept_pre_rth` (checked 02:00→9:30) |
| london_high / london_low | 02:00 → 08:00 | `swept_pre_rth` (checked 08:00→9:30) |
| 6am_high / 6am_low | **04:00 → 08:00** (repo definition) | `swept_pre_rth` (checked 08:00→9:30) |

**Ryley-literal 6am variant (`six2`)**: because "6am high/low" is ambiguous, a
second variant is computed from bars: H/L of [06:00:00, 09:29:30]. By
construction it cannot be pre-RTH-swept. Both variants are reported wherever
the 97% claim is tested, clearly labeled.

- **Touched/swept during RTH**: side is fixed by level price L vs `open_930` O:
  L ≥ O → touched when a bar's `high ≥ L`; L < O → touched when `low ≤ L`.
  Single tick through-or-equal counts (matches `fvgc.context.draws` sweep
  convention). A level inside the 9:30 bar's range is touched at 09:30:00 —
  mechanically true, and flagged as such where it matters.
- First-touch time = label of first qualifying bar within the analysis window.
- **Distance buckets** (|L − O| / ATR, fixed): [0, 0.10), [0.10, 0.25),
  [0.25, 0.50), [0.50, 1.00), ≥1.00.
- **First-sweep identity**: among levels untaken at 9:30, the one with the
  earliest RTH first-touch ≤ 10:14:30 (ties broken by larger |distance| — a
  deeper sweep through both implies the nearer was passed first; in practice
  ties at 30s resolution are rare and logged). Category "none" if no untaken
  level is touched.
- **Ping-pong pairs**: PDH↔PDL, ONH↔ONL, AsiaH↔AsiaL, LondonH↔LondonL,
  6amH↔6amL. Given side X of a pair touched first (both untaken at 9:30),
  the event is: opposite side also touched by 10:14:30.

## 6. Pre-registered conditioners (all as-of 09:30:00)

1. **Gap direction × size** = `gap_from_prior_close` / ATR.
   |gap|/ATR < 0.10 → `flat`; [0.10, 0.30) → `small`; [0.30, 0.60) → `medium`;
   ≥ 0.60 → `large`. Direction = sign (flat carries no direction). Buckets set
   from the gap marginal only (≈22/33/28/17% of sessions); chosen before any
   outcome was computed.
2. **Prior-day type** (atlas taxonomy; `trading_days.prior_day_type` exists but
   uses a different scheme — NOT used). Using prior session P and the session
   before it PP (RTH OHLC), precedence top-down:
   - `outside`: P.high > PP.high AND P.low < PP.low
   - `inside`: P.high < PP.high AND P.low > PP.low (strict; ties → next rules)
   - `trend_up`: close-position (C−L)/(H−L) ≥ 0.75 AND P.range ≥ 1.0 × trailing
     20-session median range (as of P, lagged)
   - `trend_down`: close-position ≤ 0.25 AND same range condition
   - `neutral`: everything else
3. **Two-day streak**: bullish day = RTH close > RTH open. Over the two prior
   sessions: `up-up` / `down-down` / `mixed`.
4. **Open position in prior-day range**: pos = (O − PDL)/(PDH − PDL).
   `above_range` pos > 1; `premium` 0.5 ≤ pos ≤ 1; `discount` 0 ≤ pos < 0.5;
   `below_range` pos < 0.
5. **Draw-count asymmetry**: among the 11 named levels untaken at 9:30, count
   strictly above vs below O. `above_heavy` if (above−below) ≥ +2;
   `below_heavy` if ≤ −2; `balanced` otherwise.
6. **ON range bucket**: today's `overnight_range` ÷ median of the prior 20
   sessions' overnight ranges (lagged, min 10). `compressed` < 0.80;
   `normal` 0.80–1.25; `expanded` > 1.25. (Marginal terciles sit at ≈0.80/1.23;
   rounded before outcomes were computed.)
7. **Day of week** (Mon–Fri).

**Two-way pairs (only these):** (1×2) gap × prior-day type, (1×4) gap × open
position, (2×3) prior-day type × streak, (4×5) open position × draw asymmetry.

## 7. Tier-1 event list (the ≤10 events carried into Part 2)

| ID | Event (all "by 10:15" unless stated) | Denominator |
|---|---|---|
| T1 | OR15: at least one side taken | all sessions |
| T2 | OR15: both sides taken | all sessions |
| T3 | OR15: first side taken = HIGH | sessions with ≥1 side taken |
| T4 | OR15: return to OR mid after first break | sessions with ≥1 side taken |
| T5 | OR15: extension ≥ 0.25×ATR beyond first-broken boundary | sessions with ≥1 side taken |
| T6 | PDH or PDL touched | all sessions |
| T7 | ONH or ONL touched | all sessions |
| T8 | Nearest untaken named draw (at 9:30) touched | sessions with ≥1 untaken draw |
| T9 | Nearest untaken BELOW-draw touched before nearest untaken ABOVE-draw | sessions with untaken draws on BOTH sides |
| T10 | W1 direction (close vs open) matches 9:30→10:15 net direction | sessions with nonzero W1 and net move |

## 8. Null model (ground rule 6)

Per-session bar shuffle, 500 resamples: decompose each 30s bar into offsets
(dh, dl, dc) = (high−open, low−open, close−open); shuffle the session's 90-bar
order uniformly; rebuild the path chained on closes (o′₁ = real 9:30 open,
o′ₖ = c′ₖ₋₁). Preserves per-bar volatility and the set of bar shapes (and the
session's net drift), destroys ordering/path structure. Each Tier-1 statistic
is recomputed on every resample; the null value of a probability = mean over
resamples and sessions.

Classification of an actual stat vs its null:
- **Structural deviation**: actual outside the central 95% of the null sampling
  distribution AND |actual − null| ≥ 5pp.
- **Weak structure**: outside the 95% band but deviation 2–5pp.
- **MECHANICAL**: deviation < 2pp (true, useful for expectations, no path
  structure beyond volatility).

**GEM** (almanac headline) requires: structural deviation + STABLE (§9) +
n ≥ 100 + Wilson CI half-width ≤ 5pp. Everything true-but-null-consistent is
labeled MECHANICAL and kept (expectation-setting value).

## 9. Stationarity (ground rule 7)

Split by calendar year 2018–2025 (8 full years; 2026 partial reported as a
9th column but excluded from the vote). **STABLE** if the yearly point estimate
lies within the pooled 95% Wilson CI in ≥6 of 8 years; else **DRIFTING**
(reported with the 2023–2025 value emphasized, pooled value secondary).

## 10. Archetypes (Part 3) — rule-based on OR15, label at 10:15

Let B = first-broken OR15 boundary, M = OR15 mid, C = close_1015. Exactly one
label per session; rules evaluated top-down:

1. `BALANCE_CHOP` — neither OR15 side taken by 10:15.
2. `TWO_WAY_SWEEP` — both sides taken.
3. (exactly one side taken:)
   `STRAIGHT_RUN` — C beyond B AND no post-break bar crossed M
   (after high break: no bar low ≤ M; mirror for low break).
4. `BREAK_RETEST_GO` — C beyond B AND some post-break bar crossed M.
5. `FAILED_BREAK` — C inside the OR, on the broken-boundary side of M
   (C ≥ M after a high break; C ≤ M after a low break; C = M falls here).
6. `SWEEP_AND_REVERSE` — C on the opposite side of M from B (inside the OR;
   beyond the opposite boundary is impossible here — that's TWO_WAY_SWEEP).

## 11. W1 → W2/W3 transition table (as-of 09:45)

W1 state (all knowable at 9:45:00):
- `w1_dir`: sign(close_0944:30 − open_930) → up / down / flat.
- `w1_or5`: OR5 sides taken by 9:45 → high / low / both / none.
- `w1_sweep`: ≥1 named level untaken at 9:30 touched during W1 → Y/N.

Outcome at 10:15 (close-based, 3-way):
- `continuation`: close_1015 beyond W1's directional extreme
  (close > W1 high when w1_dir=up; mirror for down).
- `reversal`: close_1015 beyond W1's opposite extreme.
- `chop`: close_1015 within [W1 low, W1 high].

Plus, per W1 state: P(each remaining untaken draw category touched in W2/W3).

## 12. Reporting discipline

- Every probability: n + 95% Wilson CI. No exceptions.
- Cells n < 30: suppressed entirely. 30 ≤ n < 100: LOW-N flag, never in the
  headline almanac. Headline requires n ≥ 100.
- Part 2 significance: per cell, two-sided binomial test of cell successes vs
  the marginal probability of its denominator population; BH FDR q = 0.10
  across ALL Part-2 cell tests; material only if |cell − marginal| ≥ 5pp.
  Verdicts: `MOVES` (q ≤ 0.10 and ≥5pp), `NULL` (neither), `WEAK` (one of two).
- Conditioning depth ≤ 2, pairs pre-registered in §6. New conditioner ideas go
  to "Future conditioners" in analysis.md — not into this run.
