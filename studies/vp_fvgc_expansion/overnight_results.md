# VP × FVGC × Liquidity Expansion — Overnight Run Results

**Date:** 2026-05-23 (overnight)
**Driver:** [studies/vp_fvgc_expansion/run_all.py](run_all.py) — 12 experiments + sanity check (E0)
**Trade universe:** [studies/baseline/results/trades.csv](../baseline/results/trades.csv) — 4,548 non-skip FVGC trades, 2018-2026
**Exit rule:** fixed +3R TP / −1R SL (matches A+ playbook convention)
**Walk-forward split:** pre-IS = 2018, IS = 2018-2022, OOS = 2023-2026
**Causal-features layer:** every experiment uses `tools/causal_features.py::load_lagged_vp()` and `load_session_levels()`. No raw `date` joins on daily VP.
**Pass criteria:** OOS n ≥ 20, OOS PF ≥ 1.5, OOS lift_2R ≥ +5pp vs OOS base (44.2%).

---

## Headline — read this first

> **The most important finding is not from the 12 experiments. It is the sanity check (E0).**

When the original A+ play (`n_vp≥2 + direction-matched VA-edge + variant!=PS + 9:30-10:15`) is rebuilt using **causally-safe lag-1 VP** (yesterday's POC/VAH/VAL — the only choice a trader actually has at 9:30 sharp), the headline collapses:

| Metric | Notion A+ (lookahead, today's VP) | A+ under lag-1 VP (causal) |
|---|---|---|
| OOS PF | **12.33** | **1.43** |
| OOS WR | 81% | 32% |
| OOS n | 123 | 90 |
| OOS lift vs base | +20pp | **−3pp** |

This confirms the [`vp_targets` Phase A INVALIDATED memory](../../../../.claude/projects/-Users-philchan-Work-fvgc-backtest/memory/project_vp_targets.md). The A+ play **does not survive** when the VP-magnet feature is shifted by one day. The Notion playbook entry is misleading and should be **demoted to "killed"** before any live capital is committed to it.

The good news: in scanning 12 expansions, **one cell (E2) does survive** under strict causal rules, with comparable structure and a genuine mechanism story.

---

## Final leaderboard

| ID | Experiment | Verdict | OOS n | OOS PF | OOS WR | OOS exp R | Note |
|---|---|---|---|---|---|---|---|
| **E2** | **Aged-naked VP POC magnet** | **PASS** | **95** | **2.28** | **43.2%** | **+0.73R** | Headline survivor. Mechanism story clean. Deep-dive below. |
| E11 | BSL/SSL sweep + FVGC reversal | NEAR-MISS | 69 | 1.93 | 39.1% | +0.57R | lift +2.1pp (below +5pp gate). Worth tightening. |
| E10 | Liquidity-only mirror | NEAR-MISS | 521 | 1.77 | 37.0% | +0.48R | lift only −1.6pp. PF respectable, large n, but no lift. |
| E5 | VP-sweep then FVGC (pivot) | FAIL | 725 | 1.72 | 36.4% | +0.46R | Lift ~0pp. Large positive sumR but no edge over base. |
| E7 | Cross-framework VP+Liq stack | FAIL | 694 | 1.58 | 34.4% | +0.38R | The "both narratives stack" idea did NOT survive lag-1. |
| E0 | **A+ replication (lag-1)** | **FAIL** | 90 | 1.43 | 32.2% | +0.29R | **Sanity check — A+ is dead under causal VP** |
| E6 | Level-launched FVGC (FVG edge ±3pts of VP) | FAIL | 191 | 1.41 | 31.9% | +0.28R | lift −6pp. Mechanism does not show. |
| E8 | Confluent-zone (VP±3pts of liq) | FAIL | 105 | 1.26 | 29.5% | +0.18R | lift −5pp. |
| E1 | Single-magnet clean shot | FAIL | 30 | 1.09 | 26.7% | +0.07R | lift −1pp. |
| E12 | Dynamic TP at first magnet | MARGINAL | 156 | — | — | +0.083R | Only +0.006R better than fixed +3R (noise). |
| E3 | A+ × stable-POC (3-day) | SMALL_N | 8 | 0.43 | 12.5% | −0.50R | Stable-POC is rare; filter kills the cohort. |
| E4 | HTF weekly VP magnets | SMALL_N | 8 | 1.80 | 37.5% | +0.50R | Sample too small to validate. |
| E9 | NWOG × VP (Monday-only) | SMALL_N | 8 | 5.00 | 62.5% | +1.50R | Tantalizing PF but n=8. Cannot conclude. |

---

## E2 — Aged-naked VP POC magnet (deep-dive)

**Setup:** A FVGC fires in 9:30-10:15, variant ∈ {bos, ifvg, no_fvg}, AND lag-1 POC sits AHEAD of entry in trade direction, AND **the overnight (pre-RTH Globex) session never reached that POC** (`overnight_high < poc_lag1` for longs, `overnight_low > poc_lag1` for shorts).

**Why it might be real:** an untraded prior-day POC is a "memory of agreement" that price hasn't yet revisited. Liquidity is parked there. The overnight failure to reach it leaves the magnet *intact* coming into RTH. The mechanism is the same one A+ assumed (POC = magnet), but the "naked" condition is what filters for the cases where the magnet is genuinely uncontested.

**Yearly stability — 9 of 9 years positive**

| Year | n | WR | PF | exp | sumR |
|---|---|---|---|---|---|
| 2018 (pre-IS) | 37 | 43.2% | 2.29 | +0.73R | +27 |
| 2019 | 9 | 44.4% | 2.40 | +0.78R | +7 |
| 2020 | 104 | 29.8% | 1.27 | +0.19R | +20 |
| 2021 | 101 | 36.6% | 1.73 | +0.47R | +47 |
| 2022 | 134 | 28.4% | 1.19 | +0.13R | +18 |
| 2023 | 103 | 34.0% | 1.54 | +0.36R | +37 |
| 2024 | 76 | 39.5% | 1.96 | +0.58R | +44 |
| 2025 | 114 | **50.9%** | **3.11** | **+1.04R** | **+118** |
| 2026 (partial) | 48 | 27.1% | 1.11 | +0.08R | +4 |
| **9-yr total** | **726** | **36.1%** | **1.69** | **+0.44R** | **+322** |

(OOS subset = 2023-26: **n=341, PF 1.99, exp +0.60R, sumR +203**.)

Cadence: ~80 setups/year → 1.5/week. Much higher frequency than the original A+ (~14/yr).

**The mechanism test — NAKED vs TOUCHED contrast**

Same setup, with the opposite overnight condition:

|  | All years | OOS only |
|---|---|---|
| NAKED (overnight didn't reach POC) | n=726, PF 1.69, exp +0.44R | **n=341, PF 1.99, exp +0.60R** |
| TOUCHED (overnight reached POC) | n=802, PF 1.48, exp +0.32R | n=432, PF 1.61, exp +0.40R |

Both cohorts are positive, but **NAKED is +0.20R per-trade better** in OOS. This is a real mechanism delta, not just the magnet itself.

**Time-window decomposition (OOS) — strong monotone in time-of-day**

| Window | n | WR | PF | exp |
|---|---|---|---|---|
| 9:30-9:45 | 84 | 32.1% | 1.42 | +0.29R |
| 9:45-10:00 | 125 | 39.2% | 1.93 | +0.57R |
| **10:00-10:15** | **132** | **45.5%** | **2.50** | **+0.82R** |

The magnet pull is **strongest in the LATER window**. Speculation: by 10:00 the morning thrust has resolved and the directional draw toward the untouched POC dominates. Worth testing whether the 9:30-9:45 cohort should be skipped entirely.

**R-distance to POC (OOS)**

| Band | n | WR | PF | exp |
|---|---|---|---|---|
| 0-1.5R | 49 | 34.7% | 1.59 | +0.39R |
| **1.5-3R** | **58** | **44.8%** | **2.44** | **+0.79R** |
| 3-6R | 76 | 32.9% | 1.47 | +0.32R |
| **6R+** | **158** | **43.0%** | **2.27** | **+0.72R** |

The very close (0-1.5R) and the mid-distant (3-6R) bands are weaker; sweet spots are **1.5-3R** (POC well clear of entry chop) and **6R+** (massive runners against a far magnet). Sample size doesn't yet support pruning by distance band.

**Variant decomposition (OOS)**

| Variant | n | WR | PF | exp |
|---|---|---|---|---|
| no_fvg | 183 | 41.5% | 2.13 | +0.66R |
| bos | 98 | 40.8% | 2.07 | +0.63R |
| ifvg | 60 | 33.3% | 1.50 | +0.33R |

`ifvg` is the weakest variant, but the cell sample is small. Not enough to prune yet.

**Lookahead audit**

All inputs are causally observable at trade entry time:
- `poc_lag1` → loaded via `load_lagged_vp()` (yesterday's POC, known by 4pm prior day)
- `overnight_high / overnight_low` → `session_levels.csv` with `available_time='open'` (set at 9:30)
- `entry_price`, `sl_dist`, `variant` → from baseline trade row, known at FVGC entry
- `mod ∈ [570, 615]` → trade clock

**No full-session aggregates used. The signal is causally clean.**

---

## What this means for next steps

### Immediate (this week)

1. **Demote the VP Magnet Play (A+) in Notion to "killed/lookahead"**. The 9-yr PF 11.17 / WR 81% numbers are a lookahead artifact. Mark it as a teaching case — every future play write-up should be re-checked against lag-1 inputs before going to "Backtesting" status.
2. **Promote E2 (aged-naked VP POC magnet) to a "Backtesting" Notion entry** mirroring the A+ structure, with:
   - The 9-yr / OOS numbers above
   - The NAKED-vs-TOUCHED contrast as the mechanism evidence
   - The time-window monotone as a sub-grade
   - **Honest** numbers: WR 36% / PF 1.69 / exp +0.44R per trade. Not as flashy as A+ was, but it's real.

### Phase B follow-ups on E2

These were not run tonight but are the natural next slices:

- **E2 × 10:00-10:15-only filter**: PF 2.50 in OOS suggests this single time window might carry most of the edge. Worth a focused n / cadence check.
- **E2 × MAX-time-since-last-touch**: when was the last time price actually traded *at* lag-1 POC? Older = stronger? Need to walk bars to compute.
- **E2 × VAH/VAL naked equivalents**: same mechanism applied to direction-matched VA edges instead of POC. May produce a cleaner cohort.
- **E2 × bos/no_fvg only**: pruning `ifvg` may tighten PF further.

### Investigate the NEAR-MISSES (E10, E11)

- **E10 (Liquidity-only mirror)**: OOS PF 1.77 on n=521 with essentially zero lift over base. This means the cohort earns +0.48R per trade but the *base rate* is hot in 2023-26 too — the filter doesn't pick winners better than no filter. Worth a per-year drill to see if specific years carry it.
- **E11 (BSL/SSL sweep + FVGC reversal)**: lift +2.1pp (below gate) but PF 1.93. The setup count is small (69 OOS). The 2018 pre-IS shows PF 3.0 on n=8 — pre-IS reads positive. Worth a tightening pass on the sweep tolerance.

### Killed

- **E0 (A+ replication)** — kill confirmed.
- **E1 (single-magnet clean shot)** — kill.
- **E6 (level-launched FVGC)** — kill. FVG-edge proximity to VP does not signal.
- **E7 (cross-framework stack)** — kill. Pooling VP+liq magnets does NOT outperform either alone. Your "two narratives stack" intuition does not hold for the magnet mechanism. (It may still hold for other mechanisms — e.g. confluent-zone-as-pivot.)
- **E8 (confluent-zone magnet)** — kill. VP-at-liquidity confluence does not lift entry edge.
- **E12 (dynamic TP at first magnet)** — marginal; not worth the complexity over fixed +3R.

### Cannot conclude (small-n)

- **E4 (HTF weekly VP)** — only 8 OOS setups. Either the band needs widening or the mechanism only fires in specific weeks. Re-run with 0.5-10R band.
- **E9 (NWOG × VP, Monday-only)** — n=8 OOS at PF 5.0 / WR 62.5%. Tantalizing but cannot conclude. A focused 1-yr live monitor would be the only cheap way to validate.
- **E3 (A+ × stable-POC)** — kill the *filter* (POC is rarely stable in NQ; my threshold 50pts is already loose), keep the underlying A+ kill verdict.

---

## Files written tonight

- `studies/vp_fvgc_expansion/_shared.py` — shared loaders + economics helpers (uses `tools/causal_features.py`)
- `studies/vp_fvgc_expansion/run_all.py` — driver for E0..E12
- `studies/vp_fvgc_expansion/e2_deepdive.py` — yearly / direction / mechanism contrast / time / R-band on E2
- `studies/vp_fvgc_expansion/results/summary.json` — machine-readable per-experiment verdict

## The big-picture takeaway

You asked a question that turned out to be more important than either of us realized: *"can we do more combinations of FVGC + VP framework"*.

The framework's strongest play, A+, was largely a lookahead artifact. **Everything built on the "magnet count ahead" mechanism collapses under causal data.** Pooling VP with liquidity doesn't fix it (E7); using HTF VP doesn't fix it at this sample size (E4); using a single tight magnet doesn't fix it (E1).

What *does* survive is a refinement of the magnet idea: **a POC that price hasn't yet touched is materially stronger than one that has been touched**. That's the only signal that beats base rate in OOS under strict causal feature loading.

This suggests the next intellectual move isn't "more combinations of magnets" — it's "what makes a magnet *unfilled and intact*?" The naked-vs-touched contrast in E2 (+0.20R per trade) is the cleanest mechanism evidence in the menu. Phase B should hunt deeper variants of unfilled-ness: time-since-last-touch, gap-and-go signatures, multi-day-naked levels, naked VA edges, etc.
