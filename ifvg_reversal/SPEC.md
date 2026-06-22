# IFVG Reversal — Model Specification

**Version:** v2.0 (draft — re-validation pending)
**Status:** Mechanic clarified after manual chart vetting; performance claims invalidated by foundation fix
**Cohort:** NQ + ES 30s candles, 2018-01-01 → 2026-05-22 (8.4 years)
**Last updated:** 2026-05-26

---

## §1 Status & Honest Caveat

The v1.0 SPEC claimed OOS PF 3.22 on COMBINED ≥ 6. That number was trained on a population using `running_50pct` (intraday running midpoint) as the 50% sweep level — **a level Phil does not draw on his chart**. On 2026-05-25 we discovered the indicator he actually trades is the **CME daily candle midpoint** (prior 18:00 NY → 17:00 NY range mid), which is rarely in the killzone range and produces a very different signal set.

We have NOT re-derived the new performance number. **Do not quote v1.0 numbers as live expectations.** Phases B/C below produce the next honest estimate.

**What this SPEC describes:** the *ideal* mechanic — Tempo's rules + Phil's refinements verified through chart vetting. Where the current code falls short, see §10 Known Gaps.

---

## §2 The Mechanic

### §2.1 Killzone (when)
Trade only **9:30 – 11:00 AM EST**. Outside the killzone the rules are not assumed to hold.

For PM session (deferred — see §10), the equivalent window is 1:30 – 4:00 PM EST against the NY AM range.

### §2.2 Premium / Discount filter (where)
Compute the dealing range (daily H–L so far). Price must be on the **correct side**:
- **Shorts:** only in premium (upper half, `pd_position` ≥ 0.50)
- **Longs:** only in discount (lower half, `pd_position` ≤ 0.50)
- **Mid-range (45–55%):** skip — chop expected near equilibrium

This was missing from v1.0 SPEC. It's the first sanity check before scoring any setup.

### §2.3 The 4-stage setup
A valid IFVG Reversal trade requires all four, in order:

1. **Liquidity sweep** — price wicks beyond a tracked level and closes back through it (same 30s candle). The sweep must be at a level on the tier list (§3).
2. **Instant reaction** — sharp move away from the swept level within 1–2 candles. No stalling. If price lingers near the level, the sweep is dead.
3. **IFVG inverts** — a candle on 30s, 1m, 2m, or 3m closes through an opposing FVG (close BELOW for shorts after a high sweep, close ABOVE for longs after a low sweep).
4. **Momentum close** — the inverting candle has a strong body (`body_fraction` ≥ 0.50). Decisive close, not a doji.

Entry at the close of the inverting candle. Stop at the gap edge + 2pt buffer.

### §2.4 Standard vs Chase entry
- **Standard:** wait for the candle to fully close above/below the gap. This is the default and the only one currently modeled.
- **Chase:** enter before close when all confluences aligned AND waiting would ruin R:R. Tempo's rule, NOT currently modeled. Tagged as future work.

---

## §3 Liquidity Tier Hierarchy

The level being swept determines setup strength. Higher tier = stronger.

| Tier | Levels | Notes |
|------|--------|-------|
| 1 | `data_high`, `data_low` (red-folder news wicks) | NFP, CPI 8:30 wicks. Highest WR per Tempo, separate model |
| 2 | `overnight_high`, `overnight_low` (Asia ∪ London H/L) | Combined overnight extreme |
| 2 | `asia_high`, `asia_low` (2:00 – 8:00 AM EST window) | Tracked separately when ≠ overnight |
| 2 | `london_high`, `london_low` (3:00 – 8:30 AM EST window) | Tracked separately when ≠ overnight |
| 3 | `prev_day_high`, `prev_day_low` | Prior RTH 9:30–16:00 extremes |
| 2 | `daily_50pct_high`, `daily_50pct_low` | **CME daily candle midpoint** (prior 18:00 NY → 17:00 NY range mid). Phil's "1-day 50% line" indicator. Rare but high-conviction when in range. |
| — | `nyam_high`, `nyam_low` | For PM session only (9:30–11:00 range) — not modeled yet |

### §3.1 Definition: daily_50pct
**Verified 2026-05-25 vs Phil's TradingView chart on 5/21:** the level reads as `(prior_cme_day_high + prior_cme_day_low) / 2` where the daily CME candle runs from 18:00 NY two days ago to 17:00 NY prior day. For 5/21/2026 this was `(29397.50 + 28797.25) / 2 = 29097.38` ✓ matches Phil's chart.

This is NOT:
- (PDH + PDL) / 2 using our `prev_day_high/low` columns (those are RTH-only)
- Running 50% of today's range
- 24h NY-day midpoint

### §3.2 Stacked level dedup
When the same setup matches multiple co-located levels (within 5pt — e.g., overnight_high and asia_high happen to be at the same price), emit ONE candidate with `stacked_levels_count = N` as a bonus factor. Don't fire N separate candidates.

---

## §4 FVG Selection Rules

### §4.1 Timeframe universe
**Only 30s, 1m, 2m, 3m** for inversion entries. NO 5m+ — too late, R:R degrades.

Cycle through these as the sweep is happening; pick the most attractive gap. Multi-TF agreement is a confluence factor.

### §4.2 Per-TF minimum size (chart visibility)
A gap must be visible on the chart at the relevant zoom to be tradeable:

| TF | min size (pts) |
|------|---------------|
| 30s | 6 |
| 1m | 10 |
| 2m | 15 |
| 3m | 18 |

Ideal range per Tempo: 8–15 pts on the entry TF.

### §4.3 Multi-TF detection of same body = ONE zone
When 1m and 30s both detect a gap with nearly identical body bounds, that is **one visual gap**, not two setups. Track as `multi_tf_count` metadata on a single zone. Phil 2026-05-25: "I'd just take the singular higher one."

### §4.4 Cross-zone proactive merging
When two DIFFERENT same-direction gaps sit close in price, merge them into one zone IF the merged span + 2pt buffer ≤ **40 pts**. The combined zone is treated as one for entry/stop:
- Entry on close that crosses the OUTER bound
- Stop at the OUTER bound + 2pt buffer
- `is_zone_merge = True` flag exposed on the candidate

Above 40pt, leave them separate — the merged SL becomes too wide. Phil 2026-05-25: "we're not combining to make something like a 60 point SL."

### §4.5 Inversion timing rule (THE bug we found)
**An FVG is inverted only by a candle on its OWN timeframe (or smaller).** A 30s candle close cannot invert a 3m gap — only a 3m candle close can. Phil 5/13 vetting: a 3m gap whose 3m close at 9:57 was 29162.25 (below gap top 29208.50) was NEVER inverted, yet our model fired on a 30s close at 9:54:30. This is a code bug, see §10.

### §4.6 Multi-gap inversion (high conviction)
When ONE candle close inverts ≥2 same-direction FVGs simultaneously, this is a high-conviction event. Flag `multi_gap_count = N`. Even when the gaps are too far apart to merge (§4.4), simultaneous inversion validates the cluster empirically. In this case, stop placement uses the OUTERMOST bound regardless of the 40pt cap (Option B per Phil 2026-05-25).

There is still an **absolute hard ceiling at 60pt SL** beyond which we skip regardless.

---

## §5 Path-Clear Check

Before emitting a candidate, scan for **uninverted opposing-direction FVGs within 1R of entry**:
- For LONG: any bearish FVG with body within `[entry, entry + SL_distance]` and not yet inverted
- For SHORT: any bullish FVG with body within `[entry − SL_distance, entry]` and not yet inverted

Tagged as `path_clear` (boolean) and `nearest_opp_fvg_pts`. Currently used as a SCORE factor (not a hard filter) — gate model decides.

Lesson source: Phil 2026-05-25 on 5/21 10:30 LONG. A 30s bearish FVG `[29225.75, 29231.25]` sat uninverted 0.75pt above the long entry at 29225. Price rejected at this resistance immediately and stopped out 3 min later. The clean path-clear concept came from the DOL play; we mirror it here.

---

## §6 Sweep → Setup Window

After a valid sweep:
- **Highest WR:** immediate reaction (within 1–2 candles ≈ 30–60 sec on 30s).
- **Still valid:** up to **30–40 min** later IF price has not "nuked" through the level (i.e., the level continues to act as resistance/support).
- **Dead sweep:** if a candle closes ≥ 5pt beyond the level in the sweep direction, the level is invalidated — look for the next level instead.

Currently coded: `SWEEP_VALIDITY_MIN = 40`. Nuke detection is per `NUKE_THRESHOLD = 5.0`. These need vetting.

---

## §7 Anti-Patterns (any one → SKIP)

Hard rejections, no exceptions:

| # | Anti-pattern | Threshold | Source |
|---|--------------|-----------|--------|
| A1 | `is_chop_day` | True | Chop kills mean reversion |
| A2 | `or_15min_range` | < 67 pts | Too small to fade |
| A3 | late killzone | entry time ≥ 10:15 | Tempo: edge fades after AM peak liquidity |
| A4 | `ath_swept_today` | True | ATH already broken = trend regime |
| A5 | `inversion_body_fraction` | > 0.90 | Too-extreme momentum = exhaustion, not reversal |
| A6 | `remaining_same_dir_unswept` | ≥ 1 magnet within 50pt against trade | Price will magnetize to it |
| A7 | `am_range_at_1030` | 50–100 pts | Choppy morning |
| A8 | mid-range entry | 0.45 ≤ `pd_position` ≤ 0.55 | §2.2 premium/discount filter |
| A9 | Tempo Sweep mismatch | (see §11) | Optional, not modeled |

These were derived from v1.0 lift tables. May need re-validation after the running_50pct → daily_50pct swap.

---

## §8 Direction-Aware Score

Once the day passes anti-patterns, score the setup. **Factor list preserved from v1.0; threshold values flagged as needing re-validation.**

### §8.1 SHORT factors (0-8)
| # | Factor | Threshold |
|---|--------|-----------|
| s1 | `sweep_level` ∈ {`prev_day_high`, `asia_high`, `london_high`, `daily_50pct_high`, `overnight_high`} | Tier-2/3 high sweep |
| s2 | `or_15min_range` ≥ 90 pts | Strong opening range |
| s3 | `prior_day_type` ∈ {`reversal_down`, `trend_down`} | Yesterday bearish |
| s4 | `prior_day_close_position` ≤ 0.30 | Yesterday closed near low |
| s5 | `gap_size_pts` ∈ [10, 20] | Sweet spot band |
| s6 | `ob_strength_ratio` ≥ 2.0 | Moderate Order Block confirms |
| s7 | `pd_position` ∈ [0.50, 0.75] | Premium of dealing range |
| s8 | `smt_bearish_at_sweep` | ES↔NQ divergence at sweep |

### §8.2 LONG factors (0-8)
| # | Factor | Threshold |
|---|--------|-----------|
| l1 | `or_45min_range` ≥ 137 pts | Long-specific OR positive |
| l2 | `prior_day_type` ∈ {`reversal_up`, `trend_up`} | Yesterday bullish |
| l3 | `prior_day_directional_changes` ≥ 4 | Intraday flips |
| l4 | `prior_day_range_atr_ratio` ≥ 0.74 | Moderate volatility |
| l5 | `or_15min_range` ≥ 88 pts | OR threshold |
| l6 | `sweep_level` ∈ {`prev_day_low`, `asia_low`, `overnight_low`, `london_low`, `daily_50pct_low`} | Low-side sweep |
| l7 | `pd_position` ∈ [0.25, 0.50] | Discount |
| l8 | NOT `is_near_ath_100pt` | Far from ATH magnet |

### §8.3 Bonus factors (proposed, not yet validated)
- `path_clear` (§5)
- `multi_gap_count ≥ 2` (§4.6)
- `multi_tf_count ≥ 2` (§4.3)
- `stacked_levels_count ≥ 2` (§3.2)

### §8.4 Score thresholds
**Old thresholds (SHORT ≥ 4, LONG ≥ 5/6/7) are invalidated until §12 Phase C re-derives them.** Currently use thresholds only for hand-vetting until walk-forward re-confirms.

---

## §9 Risk Management

### §9.1 Stop placement
- **Hard stop:** gap edge + 2pt buffer (HARD_STOP_BUFFER)
- **Soft stop:** if a candle's full body closes back through the entry gap, exit at close (don't wait for hard stop)
- **Absolute ceiling:** skip the setup if computed SL > **60 pts** (Phil 2026-05-25)

### §9.2 Break-even rule (per Tempo)
- Move stop to entry **only after price makes a first internal swing high/low ≥ 10-20 pts** in profit
- **NEVER BE at 4-5pt swings** — too premature
- If price returns to entry after a real 10-20pt move, it's a bad sign — the model is invalid

This is more nuanced than v1.0's "BE after TP1 hits at 1R."

### §9.3 Trim / TP rules (per Tempo)
| Stage | Action | Condition |
|-------|--------|-----------|
| TP1 | Trim 30-50% | First major swing (20-30 pts) |
| TP1 modifier | Take MORE off (50-70%) | If an FVG sits just past TP1 — expect rejection |
| TP1 modifier | Take LESS off (20-30%) | If "open road" to a clear target (equal highs/lows) — let runner go |
| TP2 | Trim another 20-30% | Next swing / clear level |
| Final TP | Hold 1-3 contracts | Main liquidity objective (HOD/LOD, session H/L, major drawn liquidity) |

This is more contextual than v1.0's fixed 25/25/50 @ 1R/4R/8R. The fixed ladder was a coded approximation; **Tempo's actual rule is conditional on what's in the path**.

### §9.4 EOD
If any position is still open at 16:00 NY, exit at last close.

---

## §10 Known Code Gaps & Bugs

What the SPEC says vs. what code does today:

| Gap | Spec ref | Status |
|-----|----------|--------|
| Premium/Discount mid-range veto (A8) | §2.2, §7 | NOT in current emitter |
| Daily_50pct as sweep level | §3.1 | ✓ Implemented 2026-05-25 |
| Per-TF min size enforcement | §4.2 | ✓ in v0.5 emitter |
| Multi-TF detection vs zone-merge distinction | §4.3, §4.4 | Conflated as `is_combined`; needs split (Task #44) |
| Cluster inversion uses largest-TF candle | §4.5 | **BUG — uses 30s stream (Task #43)** |
| Multi-gap inversion factor | §4.6 | Partial (in v0.4 not v0.5) |
| Absolute 60pt SL ceiling | §9.1 | NOT enforced (Task #40) |
| Path-clear factor | §5 | ✓ in v0.5 emitter |
| Time-window dedup | §3.2, §4.3 | NOT enforced — 5/13 fires 5 candidates from one window (Task #39) |
| Tempo BE rule (10-20pt swing) | §9.2 | NOT implemented — uses fixed 1R |
| Tempo conditional trim rule | §9.3 | NOT implemented — uses fixed 25/25/50 |
| Chase entry | §2.4 | NOT modeled |
| Tempo Sweep variant | §11 | NOT modeled (Task #14) |
| PM session | — | NOT modeled (Task #13) |
| Data H/L (8:30 news wick) | Tier 1 | Separate model, not validated |

**v3.1 score factor thresholds (§8.1, §8.2):** trained on running_50pct population. Need re-derivation on daily_50pct population.

**v1.0 risk config (25/25/50 @ 1/4/8R + BE):** never re-tested after foundation swap. PF 3.22 claim is invalidated.

---

## §11 Open Refinement Items

Linked tasks (see TaskList for live status):

| # | Task |
|---|------|
| 36 | FVG clustering: merge adjacent same-direction gaps into one zone |
| 37 | Sweep-level deduplication |
| 38 | Multi-TF FVG selection / scoring |
| 39 | Time-window dedup |
| 40 | Absolute SL ceiling |
| 41 | v0.6: dedupe same-candle multi-cluster + multi-cluster-inversion factor |
| 42 | Opposite-FVG path-clear check (DONE in v0.5) |
| 43 | BUG: cluster inversion must use largest-TF close |
| 44 | Re-label multi_tf_detection vs cross_zone_combine |

Plus from earlier:
| # | Task |
|---|------|
| 11 | Equal highs/lows detector + structural target |
| 12 | Structural target mode in engine (PDH/PDL/EQ H/L) |
| 13 | PM session module |
| 14 | Tempo Sweep variant |
| 23 | Order Block detector |
| 24 | Structural target detector |
| 25 | Regime detector (distance to ATH + vol) |

---

## §12 Re-Validation Plan

**Phase A** (this doc): SPEC v2.0 ← we are here

**Phase B:** Code fixes — apply tasks #39, #40, #41, #43, #44, plus §2.2 Premium/Discount filter, §9.1 60pt ceiling.

**Phase C:** Re-run population on 8-yr cohort with fixed v0.6 emitter. Re-derive:
- Per-factor lift tables on daily_50pct foundation
- Confluence thresholds (replacing §8.4 invalidated values)
- Risk sweep (replacing §9.3 25/25/50 claim with Tempo-conditional rule or its proxy)
- Walk-forward across 19+ rolling 6-month windows

**Phase D:** Decision gate:
- Walk-forward median PF ≥ 1.5 → tighten + build daily briefing tool
- 1.0 ≤ median PF < 1.5 → another refinement round (target the worst-performing factor)
- median PF < 1.0 → fundamental rethink (the IFVG-reversal mechanic may not capture Phil's live edge — try other plays)

---

## §13 Glossary

| Term | Definition |
|------|------------|
| **FVG** | Fair Value Gap. 3-candle pattern: c1.high < c3.low (bullish) or c1.low > c3.high (bearish). c2 body is the gap. |
| **IFVG** | Inverted FVG. Bullish FVG closed BELOW = now resistance; bearish FVG closed ABOVE = now support. |
| **Sweep** | A candle that wicks beyond a level and closes back through it, same candle. |
| **Order Block (OB)** | 2-candle engulfing. Bullish OB = green candle whose body engulfs prior red. |
| **SMT divergence** | One index makes a new session extreme, the other doesn't. Bullish = one made low, other didn't. |
| **Premium / Discount** | Premium = upper half of dealing range. Discount = lower half. Midpoint at 50%. |
| **Killzone** | 9:30 – 11:00 NY (AM); 1:30 – 4:00 NY (PM, not modeled). |
| **Dealing range** | Today's RTH range from 9:30 to evaluation time. |
| **OR** | Opening Range — first 5/15/45 min of RTH. |
| **Anti-pattern** | Factor whose presence reliably indicates SKIP. |
| **Multi-gap inversion** | One candle close inverts ≥2 same-direction FVGs at once. High conviction. |
| **Zone merge** | Two distinct FVGs combined into one logical zone (proactive, ≤ 40pt cap). |
| **Path-clear** | No uninverted opposing FVG within 1R above (long) or below (short) of entry. |
| **Walk-forward** | Test PF on rolling time windows to assess regime stability. |
| **CME daily candle** | 18:00 NY (prior day) → 17:00 NY (current day). Used for daily_50pct. |

---

## §14 Files & Code

| Component | Path |
|-----------|------|
| Population generator (loose defaults) | `studies/ifvg_reversal_population/run.py` |
| v0.4 candidate emitter (multi-gap aware) | `studies/ifvg_reversal_population/emit_v0_4_candidates.py` |
| v0.5 candidate emitter (cluster + path-clear) | `studies/ifvg_reversal_population/emit_v0_5_candidates.py` |
| Sweep detector | `ifvg_reversal/detectors/sweep.py` |
| Multi-TF FVG detector | `ifvg_reversal/detectors/multi_tf_fvg.py` |
| Chop filter | `ifvg_reversal/detectors/chop.py` |
| Engine (scaled exits, v1.0) | `ifvg_reversal/engine.py` |
| Daily 50% builder | `data/levels/build_daily_50pct.py` |
| Daily 50% join | `data/levels/add_daily_50pct_to_session_levels.py` |
| SMT detector | `shared/smt_detector.py` |
| FVG primitives | `shared/fvg.py` |
| Structural levels | `shared/structural_levels.py` |
| v3.1 confluence (stale) | `studies/ifvg_reversal_population/v3_1_confluence.py` |
| Risk sweep (stale) | `studies/ifvg_reversal_population/v3_1_risk_sweep.py` |
| Walk-forward | `studies/ifvg_reversal_population/walk_forward.py` |
| Factor ranking | `studies/ifvg_reversal_population/factor_ranking.py` |
| Tempo recap log | `studies/tempo_recaps/demonstrations.csv` (33 trades, 10 recaps) |
| Tempo manual (reference) | `ifvg_reversal/reference/tempo-manual.md` |
| Methodology | `ifvg_reversal/METHODOLOGY.md` |
| v1.0 SPEC backup | `ifvg_reversal/SPEC.md.v1.0.bak` |

---

## §15 Changelog

- **v2.0 (2026-05-26)** — Foundation reset after Phil chart vetting. Daily_50pct replaces running_50pct. Adds clustering (§4.4), multi-TF detection distinction (§4.3), inversion-TF rule (§4.5), path-clear (§5), Tempo BE/trim refinement (§9.2-9.3), absolute SL ceiling (§9.1). Invalidates v1.0 performance numbers. Known gaps explicit in §10.
- **v1.0 (2026-05-22)** — Validated v3.1 confluence + 25/25/50@1/4/8R+BE risk + walk-forward. Backtest-validated state. Pre-deployment. **NOW INVALIDATED** due to running_50pct foundation mismatch.
- **v0.3.5** — Asia/London distinct sweep levels.
- **v0.3.4** — Running 50% (equilibrium) sweep level added. (Later removed in v2.0.)
- **v0.3.3** — Hard stop switched from sweep-wick to gap-edge based.
- **v0.3.2** — Flat 300s confirmation window.
- **v0.3.1** — Three open TODOs resolved.
- **v0.3.0** — Tempo manual grounding, 13 rule sections.
- **v0.2.0** — Skeleton with variance grids.
- **v0.1.0** — Initial empty skeleton.
