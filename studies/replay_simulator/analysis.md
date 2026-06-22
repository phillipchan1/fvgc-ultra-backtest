# Study: Replay Simulator, Account Survival & Film Room (Program Track C — FINAL)

## Question
What does it operationally look and feel like to trade the program's one validated
play — the opening-window FVG short, no protected_swing — mechanically, at TPT PRO
$50K scale, given that its true forward win rate is uncertain across regimes
(56% / 70% / 83%)? Plus: one pre-registered 3-hypothesis family from Track B
structural facts (the only new statistics in this track), and a film room.

**Program state inherited:** Track A NEGATIVE (zero FDR survivors of 58 narrative
factors; harness validated by positive control at p=2.4e-04). No framework was
promoted, so this track ran in **reduced, benchmark-only mode** — the Track A gate
is satisfied on that basis. Track B complete; its session table
(`studies/session_path_atlas/results/cache/session_table.parquet`) supplies the W1 /
ON-tercile / OR5 joins. Canonical baseline: 8-yr frozen-spec run, n=4,542 tradeable,
49.5% WR, PF 1.00 (2018-01 → 2026-05). Notion track page:
https://app.notion.com/p/37be2f0e776081578827c3997f906b48

## Methodology

- **Deterministic replay** (`run.py`, rules pre-written in `results/REPLAY_RULES.md`
  before any run; tiebreaks T-1…T-8). The replay consumes the frozen canonical CSV
  only; `fvgc/model.py` / `fvgc/engine.py` untouched and never re-run (the working
  tree's dirty `fvgc/constants.py` is therefore irrelevant to this study).
  Byte-identical reproduction verified (md5 of `replay_log.csv` and
  `account_survival_grid.csv` across re-runs).
- **Reconciliation assertion** (`tclib.reconcile_or_die`): replay must equal Track
  A's re-derived benchmark exactly — full n=83 / 58 wins / PF 2.846 / +0.398R; IS
  n=41 / 23 wins; recent n=42 / 35 wins. **PASS.** The run aborts with
  `ReconciliationError` (producing nothing) on any mismatch.
- **Eras**: IS = sessions ≤ 2024-02-12, recent = ≥ 2024-02-13 (Track A
  `phase1_split.json`), so every number reconciles with the program ledger to the
  trade. "2018–2023" / "2024+" in the brief map to these boundaries.
- **Monte Carlo** (Part 2): 10,000 paths × 12 months per cell; block bootstrap by
  calendar month (preserves ~1-signal/month clumping and same-session doubles);
  outcomes redrawn Bernoulli(56/70/83%) holding the empirical stop-size
  distribution (15–60pt) and R = ±1 fixed; TPT PRO mechanics per `MC_CONFIG`
  (trail $2,000 on intraday unrealized, floor locks at $50,000, no daily loss
  limit). Sizing: floor($700 / (stop × $2)) MNQ contracts, min 1 (never binds);
  mean realized risk ≈ $676 (~3% rounding loss). 0.5× rider at $350.
- **Intra-trade path model**: the engine tracks win-side MFE/MAE through end of
  day (post-exit contaminated), so win-side intra-trade MAE is NOT available.
  CONSERVATIVE primary: every win dips a full stop before winning; every loss
  first runs up by its empirical pre-stop MFE (benchmark losses' own `mfe_r`,
  n=25, intra-trade exact, median 0.29R), ratcheting the trailing floor before the
  stop hits. OPTIMISTIC bound (no dip, no ratchet) reported alongside; truth is
  between. All survival numbers labeled accordingly.
- **Part 3**: family m=3, BH q=0.10 within family, on ALL tradeable baseline
  signals (not the benchmark cohort); registration rows written to
  `results/test_ledger.csv` before computation; IS first, ONE confirmatory OOS
  look; exact binomial vs each cohort's own split base rate. Benchmark sub-rows
  descriptive only. OR5-contradiction table descriptive, ledger-exempt.
- **Film room**: all 83 benchmark trades + the 20 most recent non-qualifying
  opening-window signals; 30s candles 9:15–10:30 ET, named levels, FVG zone,
  entry/stop/target, outcome path, Part-3-factor side panel; 10-chart self-quiz
  truncated at entry. Regenerate: `python3.13 studies/replay_simulator/run.py
  --film-room`.

## Results

### Part 1 — the frequency finding is the headline
- **0.83 trades/month pooled** (83 trades / 1,845 sessions / 100.4 months); only
  3.7% of sessions fire. IS era: 0.56/month; recent era: 1.55/month.
- Longest drought **395 days** (2018-03-27 → 2019-04-26), immediately followed by
  a 369-day drought: **2018-03 → 2020-04 produced exactly one trade in two years.**
- The validated play cannot support a 3–5 setups/week tempo. Anything traded more
  often is outside the validated cohort by definition.
- Per-era: full +0.398R/trade, PF 2.85, max DD 4.0R (414 days to recover); IS
  +0.122R/trade, PF 1.26; recent +0.667R/trade, PF 6.51, max DD 1.0R.
- Losses cluster: the worst streak (4) came from two double-signal sessions in 7
  calendar days.

### Part 2 — survival per regime (CONSERVATIVE / $700 / pooled frequency unless noted)
- **56% regime: P(termination within 12mo) = 60.2%** (47.3% at its own 0.56/mo
  frequency); P(safe buffer ≥$52K within 12mo) ~29–34%; median 12-month balance
  ≈ $49.7–50.0K. Expectation to buffer at era frequency: **~4 years.**
- 70% pooled: P(term 12mo) 32.8%; P(buffer 12mo) 60%; median 12mo ≈ $52.0K.
- 83% regime at its own 1.58/mo frequency: P(term 12mo) 12.2%; buffer median ~3
  months, P(buffer 12mo) 89%.
- Half sizing ($350): termination ~0–7% everywhere, but buffer probability
  collapses (56%: 2.6–7.1%) — **sizing reallocates the failure mode (death →
  stagnation), it does not remove it.**
- Where Phil's prior constraint math said ~4 weeks to buffer (at 16/month tempo),
  the validated play says **~3 months in the best regime and effectively never
  (within a year) in the worst.**

### Part 3 — pre-registered family: 0 of 3 validated
- **T1 W1-alignment**: no IS effect (49.6% vs 49.3% base, n=1,118, q=0.83). OOS
  mildly positive (53.9% vs 51.8%, n=746, p=0.26) — not significant, and IS already
  failed. NOT VALIDATED.
- **T2 stop-beyond-W1-extreme**: **passed IS decisively (59.3% vs 49.3% base,
  n=199, p=0.0056, q=0.017) and then failed the one-shot OOS look with the effect
  reversed (49.2% vs 51.8% base, n=118).** NOT VALIDATED — and a textbook
  demonstration of why the single-look discipline exists.
- **T3 ON-range expansion**: flat both splits (IS 47.3% vs 47.6%, n=1,130; OOS
  53.3% vs 52.5%, n=625). NOT VALIDATED.
- OR5-contradiction (descriptive, LOW-N EXPLORATORY): flat — 50.1% consistent
  (n=1,961) / 50.7% (n=546) / 50.5% (n=661). No structure.

### Part 4 — film room
113 charts under `results/film_room/` (83 trades: 58 winners / 25 losers; 20
not-quite; 10-quiz). Losers section framed explicitly as "correct trades that
lose" — at 56–83% WR, 1-in-6 to 1-in-2 of correct trades lose.

## Honest caveats (every dollar figure inherits these)
1. **Regime uncertainty dominates everything.** The benchmark's pooled 69.9% WR
   (n=83) decomposes into 56.1% (n=41, 2018→2024-02) and 83.3% (n=42, 2024-02→
   2026-05). Nothing in this program identifies which regime forward trades come
   from; no scenario in Part 2 is a forecast. Quote ranges, never the pooled point.
2. **Simulated fills**: entries at frozen-engine prices, stops filled AT the stop
   price, no slippage or commissions, R = ±1 exactly. Real MNQ stop slippage makes
   all survival numbers somewhat worse; commissions (~$1.5–2.5/contract RT, often
   10–20+ contracts/trade) meaningfully reduce the +0.12R IS-regime expectancy.
3. **MAE approximation**: win-side intra-trade adverse excursion is not exposed by
   the frozen engine; the CONSERVATIVE/OPTIMISTIC bracket bounds it. The
   conservative model also penalizes higher signal frequency (more full-stop dips
   testing the floor), visible in the 83% era-matched row.
4. **TPT terms drift**: trail/floor/lock parameters verified 2026-06-09 against
   TakeProfitTrader's help center; re-verify before acting (the daily-loss-limit
   removal in Jan 2025 shows how fast these change). 80/20 profit split and
   withdrawal rules NOT modeled.
5. **W1/ON/OR5 joins** come from Track B's session table (starts 2018-01-09; 5
   unknown sessions handled per tiebreak T-4). Most benchmark entries occur before
   9:45, so W1 fields on benchmark trades are film-room context, never entry-time
   information (tiebreak T-5).
6. **Part 3's OOS look is spent.** T2 in particular cannot be re-tested on
   2024-02→2026-05 data; any revival requires fresh forward data and fresh
   registration.
7. The ledger is append-only by design; re-running `--part3` appends duplicate
   rows. The canonical ledger is the committed one (9 rows: 3 REGISTERED + 3×IS +
   3×OOS).

## Deliverables
- `results/REPLAY_RULES.md` (pre-written) · `results/replay_log.csv` (1,860 rows)
- `results/portfolio_stats.md` + `portfolio_stats.csv` + `equity_curve_r.csv`
- `results/account_survival.md` + `account_survival_grid.csv` (13 MC cells)
- `results/part3_hypotheses.md` · `results/test_ledger.csv` (3 tests, registered first)
- `results/film_room/` (FILM_ROOM.md + 113 charts)
- `results/OBSERVATIONS_FOR_RESEARCH_QUEUE.md` (7 untested items)
- `run.py` / `tclib.py` — one-command regeneration, byte-identical (fixed seeds)

Notion: track page updated with checkpoints + final report; program parent updated
to "Program complete — A negative, B complete, C complete."
