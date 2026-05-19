# Multi-Cell Confluence Matrix — 8-Year Re-Validation

**Date:** 2026-05-18
**Question:** With the Databento extension to 2018–2026 (was Oct 2023 – Mar 2026), do the published M1 Short / M2 Long / M3 Long confluence stacks still hold? If not, what does?
**Inputs:** `studies/mfe_multi_r/results/mfe_trades_enriched.csv` (regenerated on 8yr baseline, n=4,542), `studies/multi_cell_confluence/results/cell_configs.json` (old frozen stacks).
**Pipeline:** `build_analysis_frame.py` → `phase_a_validate_frozen.py` → `phase_b_remine.py`
**IS/OOS split:** IS = 2018-01-01 → 2024-12-31 (n=3,429), OOS = 2025-01-01 → 2026-05-15 (n=1,113).
**Convention follows** `studies/m1_short_factor_remine/` for IS/OOS dates and gate definitions.

---

## TL;DR

| Cell | Old verdict | **8yr verdict** | Action |
|------|-------------|------------------|--------|
| **M3 Long** | Tier B (OOS collapse −21pp / −52pp) | **Tier A confirmed** — WR 64.4%, PF 1.34, year-floor 47.8%, regime spread 1.8pp, **5/5 gates** | **Upgrade Notion page to Tier A.** New factor stack. |
| **M2 Long** | Tier A (3+ tier OOS-validated, n=20) | **Tier C / regime-fragile** — old stack: WR 59%, year-floor 26.7% in 2021. Re-mine on 8yr produces n=14 (too thin). | **Downgrade Notion page to Tier C** or attach yearly-regime gate. |
| **M1 Short** | Tier A (2+ tier, WR 68.5%) | **Tier B** — re-mine: WR 59.4%, year-floor 41.2% in 2020. Already known from `m1_short_factor_remine`. | Page already updated per that study; this run confirms. |
| **M1 Long** *(unpublished)* | not on Notion | **Tier A candidate** — re-mine: WR 59%, PF 1.34, year-floor 50%, regime spread 9.4pp, **5/5 gates** | **Add as new Notion page.** |
| **M2 Short** *(unpublished)* | not on Notion | **Skip** — year-floor 17.6%, regime-fragile both old and new | No play. |
| **M3 Short** *(unpublished)* | not on Notion | **Skip** — year-floor 38.2% old / 27.8% new | No play. Carve-out concept only. |

**Headline:** the matrix study's *unpublished* M3 Long is the most robust play in the playbook; the *published* M2 Long is the most regime-fragile.

---

## Methodology

### Acceptance gates (Phase B)

A cell passes "Tier A" if its 8yr re-mined stack hits all five at the cell's primary confluence tier (3+ for most, 2+ for M1 Short legacy):

| Gate | Threshold |
|---|---|
| IS WR | ≥ 58% |
| OOS WR | ≥ 55% (requires n ≥ 20 OOS, else marked insufficient) |
| \|IS − OOS WR\| | ≤ 10pp |
| Year-floor | ≥ 45% (minimum WR across years with n ≥ 10) |
| Regime spread | ≤ 15pp (max − min across bull/bear/neutral, n ≥ 20/regime) |

### Inputs

- 4,542 tradeable FVGC trades, 2018-02-01 → 2026-05-15
- 30s NQ futures, IS/OOS split at 2025-01-01
- 61 factor masks: gap, overnight, prior_day, news, calendar, vixy, 9:30 candle, first 5/15min FVG, OR 5/15/45min, macro window FVGs, variant, 60d regime
- Quantile cutoffs (top/bot quartile factors) **re-fit on 8yr IS** for the new stacks; old quantiles preserved for apples-to-apples comparison with the old stacks

### Phase A — frozen-stack validation

Apply the existing cell stacks (from `studies/multi_cell_confluence/results/cell_configs.json`) as-is to 8yr data. Reveals which stacks generalize.

### Phase B — re-mine

For each cell, on 8yr IS only: univariate lift per safe factor, greedy stack pros (uncorrelated, ≥ +5pp lift) up to K=7, then vetos (uncorrelated, ≤ −5pp lift) up to K=3. Validate stack on 8yr OOS. Compare to old.

### Phase C — dropped

M4 (10:15–10:30) cell had only n=25–28 trades over 8yr — too thin for a confluence study. The FVGC engine emits very few signals in that window because by 10:15 most FVGs have been taken.

---

## Cell-by-cell verdicts

### M3 Long — **Tier A confirmed (5/5 gates)**

The biggest surprise. The Notion page warned "generic M3 longs FAIL OOS" based on n=17 OOS at the old stack. **Over 8 years, M3 long is the most regime-robust cell in the entire playbook.**

**New stack (8yr-mined):**
- **Pros (7):** `dow_monday`, `prior_day_weak`, `no_5m_bull_fvg`, `not_fomc_week`, `has_5m_bear_fvg`, `variant_no_fvg`, `dow_friday`
- **Vetos (3):** `prior_day_mid`, `is_opex_week`, `dow_tuesday`

**Old stack (Notion):** `c930_range_bot_q`, `or_5m_bot_q`, `no_5m_bear_fvg`, `dow_friday`, `not_fomc_week`, `prior_day_weak`, `variant_no_fvg` / vetos `dow_tuesday`, `or_5m_top_q`, `prior_day_mid`.

| Metric | Old stack on 8yr (clean) | **New stack on 8yr (clean)** |
|---|---|---|
| n at 3+ tier | 261 | **264** |
| WR | 63.2% | **64.4%** |
| PF @ 2R | 1.18 | **1.34** |
| Year floor | 45.5% | **47.8%** |
| Regime spread | (not computed) | **1.8pp** |

**Year-by-year (new stack):**
| Year | n | WR | PF |
|---|---|---|---|
| 2020 | 38 | 57.9% | 0.92 |
| 2021 | 26 | 73.1% | 2.73 |
| 2022 | 42 | 69.0% | 1.36 |
| 2023 | 41 | 63.4% | 1.15 |
| 2024 | 34 | 67.6% | 1.24 |
| 2025 | 50 | 68.0% | 1.23 |
| 2026 | 23 | 47.8% | 1.29 |

**Regime breakdown:**
| Regime | n | WR |
|---|---|---|
| Bear | 59 | 64.4% |
| Bull | 106 | 65.1% |
| Neutral | 98 | 63.3% |

**Interpretation:** the play *isn't* a compression-washout setup as the old stack believed. The 8yr-mined stack flips most of the compression factors out (`c930_range_bot_q`, `or_5m_bot_q` drop) and pulls in calendar/structural factors (`dow_monday`/`dow_friday` ends of week, `prior_day_weak`, `has_5m_bear_fvg`, `variant_no_fvg`). New thesis: **M3 long is a Monday/Friday prior-weak no-bull-FVG mean-reversion play.**

**Notion page action:** Replace factor stack. Bump Tier B → Tier A. Drop the "needs magnet gate to survive" caveat — the 8yr data refutes it.

---

### M2 Long — **Tier C / regime-fragile**

The Notion-page A-tier play. **Did not generalize back to 2018–2022.** OOS WR was real (65%, n=20) but the IS window was a strong bull stretch (2023–2025) that doesn't represent the full distribution.

**Old stack on 8yr:**
- n=229 @ 3+ clean, WR 59.0%, PF 1.18
- **Year floor: 26.7% (2021)** — catastrophic
- Notion-claimed 66.4% IS WR was Oct 2023 – Sep 2025 only

**Re-mine on 8yr:** stack collapsed to n=14 (mutually rare factors). Suggests the factor universe doesn't have features that capture M2 long structure reliably across regimes.

| View | n | WR | PF |
|---|---|---|---|
| Old stack 8yr (3+) | 229 | 59.0% | 1.18 |
| Old stack 8yr (4+) | 110 | 64.5% | 1.24 |
| **New stack 8yr (3+)** | 14 | 64.3% | 2.00 |

**Year-by-year (old stack, 3+):**
| Year | n | WR | PF |
|---|---|---|---|
| 2020 | 37 | 54.1% | 0.74 |
| **2021** | **30** | **26.7%** | **0.50** |
| 2022 | 11 | 45.5% | 1.67 |
| 2023 | 31 | 54.8% | 0.70 |
| 2024 | 40 | 82.5% | 2.71 |
| 2025 | 62 | 67.7% | 1.65 |

2021 was a wild grind-higher year (Fed-supported melt-up). M2 long bulls *should* have worked, but the FVGC engine's signals in that period were largely losers. Why is unclear from this data alone — possibly the macro_1 2plus_fvgs factor signaled too often when price was already extended.

**Notion page action:** Mark as Tier C, document the 2021 collapse, recommend **trade 4+ tier only** (n=110, WR 64.5%, PF 1.24 — still year-fragile but n much larger). Or **suspend live trading** of M2 long until a year-robust stack is found.

---

### M1 Short — **Tier B (confirms `m1_short_factor_remine` finding)**

Already extensively studied; this run is corroborative.

- Old stack on 8yr clean @ 2+: n=49, WR 57.1%, PF 1.92, year-floor 66.7% (limited to vetoed-out years)
- New 8yr-mined stack: n=106, WR 59.4%, PF 1.53, year-floor 41.2% (2020)
- The `m1_short_factor_remine` REPORT.md already concluded "modest improvement, regime-fragile; A-tier only via the right runner exit (TP@5R no-BE)"

**Notion page action:** Already updated per `m1_short_factor_remine/REPORT.md`. No new change required from this study.

---

### M1 Long — **Tier A candidate (5/5 gates) — NEW play**

Unpublished, but the 8yr re-mine produces a robust stack.

**New stack:**
- **Pros (7):** `no_pre_rth_news`, `prior_day_mid`, `variant_no_fvg`, `vixy_normal`, `is_fomc_week`, `dow_wednesday`, `gap_large_down`
- **Vetos (2):** `prior_day_weak`, `c930_body_top_q`

| Metric | Value |
|---|---|
| n at 3+ tier | 117 |
| WR | 59.0% |
| PF @ 2R | 1.34 |
| Year floor | 50.0% (2025, n=16) |
| Regime spread | 9.4pp |
| IS WR | 60.1% |
| OOS WR | 55.0% (n=20) |
| All 5 gates | **Pass** |

**Interpretation:** M1 long fires on **gap-down quiet mornings with normal vol, no pre-RTH news, and FOMC-week Wednesdays**. Counter-intuitive: bears who'd shorted into the gap-down get squeezed in M1 (9:30–9:45) when no_fvg variant signals continuation against them.

**Action:** Create new Notion page **"M1 Long — Confluence Model"**. Tier A, 5/5 gates.

---

### M2 Short, M3 Short — **No plays**

Both fail year-floor at every reasonable stack. Year-floor 17.6% (M2 short, 2023) and 27.8% (M3 short, new mine). Don't add to playbook.

The "M3 Short — Both-Swept Carve-Out" idea on the M3 Long page remains valid as an explicit *conditional carve-out* (only when OR.H and OR.L both swept), but the matrix-level confluence stack isn't there.

---

## Files produced

- `results/trades_analysis_8yr.csv` — 4,542 enriched trades w/ macro_window, regime_60d, split, year
- `results/phase_a_summary.json` — frozen stacks scored across 5 time slices, all 6 cells
- `results/phase_a_per_cell.csv` — flat tier breakdown (236 rows: 6 cells × 5 slices × 2 views × ≤4 tiers)
- `results/phase_a_year_by_year.csv` — primary-tier WR per year per cell
- `results/phase_b_per_cell.json` — full new-stack scoring per cell, gates breakdown, regime + year
- `results/cell_configs_8yr.json` — new factor stacks (drop-in replacement for the old `cell_configs.json` once Notion is updated)
- `results/phase_b_comparison.csv` — flat old-vs-new per cell

---

## Recommended next steps

1. **Update Notion pages** (manual; specific diffs are in the next section):
   - M3 Long → Tier A, new factor stack, drop magnet-gate caveat
   - M2 Long → Tier C (or suspend), document 2021 collapse, recommend 4+ tier only
   - Create new "M1 Long — Confluence Model" page
2. **Replace** `studies/multi_cell_confluence/results/cell_configs.json` with `studies/multi_cell_8yr_v2/results/cell_configs_8yr.json` so `tools/morning_briefing.py` uses the new stacks. *Don't* delete the old one — preserve for audit.
3. **Update** `playbook/plays.json` and `playbook/briefing_config.json` to match.
4. **Live tracking** of M3 Long with the new stack starting tomorrow's session — old Notion page trade list is still valid retroactively, but tag a "v2 cutover" date in the CSV.

## Notion-page diffs (one-line summaries)

- **M3 Long:** title `M3 Long — Confluence Model (8yr v2)`; Tier → A; factor stack → 7-pro / 3-veto above; OOS section → 8yr cross-validation table; remove "CRITICAL: generic M3 longs FAIL OOS" callout; rewrite "Why this works" around prior-weak Monday/Friday + variant_no_fvg.
- **M2 Long:** title same; Tier → C; add red-banner "8yr re-validation found year-floor 26.7% in 2021"; recommend 4+ tier only with size cap; remove "OOS-validated" language; surface 2018-2026 year-by-year table.
- **M1 Long (new):** Tier A, 5/5 gates, factor stack and metrics above, paired with M1 Short on the playbook page tree.

---

*Generated by `studies/multi_cell_8yr_v2/` on 2026-05-18.*
