# HTF FVG Nesting Recheck

## Causal Audit Status

**REVALIDATED (core) — 2026-05-21.** The `nested_15m` headline (+25.8pp OOS, n=150) is built from `liquidity_levels.csv` HTF FVGs that pre-exist intraday entries — independent of any contaminated VP/range feature. **It survives.**

**Q5 VP-stack subsection is CONTAMINATED.** `run.py:212` joins today's POC/VAH/VAL on date. Any "nested × n_vp ≥ 1" cross-cell here inherits the bug documented in [`studies/lookahead_audit/`](../lookahead_audit/analysis.md). Use the core `nested_15m` signal; ignore the Q5 cross-cell.

---

## TL;DR

The earlier study (`studies/discovery_2R_hits/explore_v3.py`) reported **0 nested
trades across 4,548 entries** — that was a bug, not a real result.

Fixed result: **423 nested trades (9.3%)**, headlined by **15m HTF FVG nesting**:

| cell                | n   | hit_2R | lift vs base |
| ------------------- | --- | ------ | ------------ |
| baseline (all)      | 4548 | 0.422 | —            |
| nested_15m          | 291  | 0.680 | **+25.8 pp** |
| nested_any (15m/1H/4H/Daily) | 423 | 0.596 | +17.4 pp |
| nested_any × has_vp | 229  | 0.659 | +23.7 pp     |

Walk-forward holds: 15m nesting is **+25.2pp IS / +26.4pp OOS**. Stable, real.

The ICT‑canonical 1H / 4H / Daily nestings individually are noise on this sample
size (each n ≤ 60, no consistent lift). The signal lives almost entirely on 15m.

---

## Q1 — Data structure audit

```
HTF rows in data/levels/liquidity_levels.csv:
  htf_fvg_15m    141,088
  htf_fvg_1H      91,378
  htf_fvg_4H      44,635
  htf_fvg_Daily   26,470
  ────────────  ────────
  total          303,571
```

All HTF rows have `fvg_top`, `fvg_bottom`, `fvg_mid`, `side`, `fvg_direction`,
`bars_old` populated (zero nulls). Nesting can be computed directly from
`fvg_bottom <= entry_price <= fvg_top` — no approximation or reconstruction
needed.

The original concern that HTF rows only had a `price` field with `fvg_top` /
`fvg_bottom` null was incorrect. The data is fine; the test was broken.

## Q2 — Root cause of the v3 zero result

`studies/discovery_2R_hits/explore_v3.py` at the date lookup:

```python
htf_by_date: dict = {}
for r in htf.iter_rows(named=True):
    htf_by_date.setdefault(r['date'], []).append(...)   # keys: datetime.date

dates = df['date'].to_numpy()                            # dtype: datetime64[ns]
...
for i in range(df.height):
    fvgs = htf_by_date.get(dates[i], [])                 # numpy.datetime64
                                                         #   != datetime.date
                                                         # → always empty
```

`polars.Date` converted to a numpy array becomes `datetime64[ns]`.
`numpy.datetime64` is not equal (and does not hash equal) to `datetime.date`,
so **every dict lookup returned `[]`** → `nested_*` flags were universally
false → zero nested trades reported.

A pandas-side variant of the same trap: `pd.Timestamp` is a subclass of
`datetime.date` (so `isinstance(t, datetime.date)` is True) but
`hash(pd.Timestamp(d)) != hash(d)`, so the dict still misses. Forcing
`datetime.date(x.year, x.month, x.day)` on both sides is what makes the
lookups land.

This is the same trap that has bitten before — see also the `n_vp_targets`
join in `studies/speed_of_move/run.py`, which explicitly normalizes with
`vp['date'] = vp['date'].dt.date`.

## Q3 — Direction-aware nesting

For each trade:

* `want_dir = 'bullish' if direction == 'long' else 'bearish'`
* iterate HTF rows for that calendar date; require
  `fvg_direction == want_dir` **and** `fvg_bottom <= entry_price <= fvg_top`
* set the appropriate `nested_{timeframe}` flag and increment `nested_count`

Bullish‑in‑bearish (or vice versa) is explicitly excluded — that would be a
counter‑signal, not nesting confluence.

## Q4 — Per‑timeframe lift (full sample, hit_2R)

| cell                 | n   | hit_2R rate | lift_pp |
| -------------------- | --- | ----------- | ------- |
| baseline (ALL)       | 4548 | 0.422       | —       |
| **nested_15m**       | 291 | **0.680**   | **+25.8** |
| nested_1H            | 54  | 0.407       | −1.5    |
| nested_4H            | 49  | 0.408       | −1.4    |
| nested_Daily         | 59  | 0.407       | −1.5    |
| nested_any (≥1 TF)   | 423 | 0.596       | +17.4   |
| nested_count ≥ 2     | 26  | 0.385       | −3.8    |
| nested_count ≥ 3     | 4   | 0.500       | +7.8    |
| nested_4H AND Daily  | 2   | 1.000       | (n too low) |
| nested_1H AND 4H     | 11  | 0.455       | +3.2    |

The story: the **15m HTF FVG carries the entire signal**. 1H/4H/Daily as
individual filters add nothing. Multi-TF compound buckets are too thin to
trust.

## Q5 — Stack with VP filter (`n_vp_targets ≥ 1`)

| cell                          | n   | hit_2R | lift_pp |
| ----------------------------- | --- | ------ | ------- |
| ALL                           | 4548 | 0.422 | —       |
| has_vp                        | 2258 | 0.539 | +11.7   |
| nested_any                    | 423  | 0.596 | +17.4   |
| **has_vp AND nested_any**     | 229  | **0.659** | **+23.7** |
| has_vp only (no nest)         | 2029 | 0.526 | +10.4   |
| nested_any only (no vp)       | 194  | 0.521 | +9.8    |

VP and nesting each lift ~10pp individually and ~24pp combined. Roughly
additive → they are **largely independent signals**, not redundant. The
combined cell (n=229) is the cleanest A+ confluence we have seen for hit_2R
short of a full multi-factor playbook.

## Q6 — Walk‑forward (IS 2018‑22 / OOS 2023‑26)

| cell             | IS n | IS rate | IS lift | OOS n | OOS rate | OOS lift |
| ---------------- | ---- | ------- | ------- | ----- | -------- | -------- |
| ALL              | 2193 | 0.400   | —       | 2355  | 0.442    | —        |
| **nested_15m**   | 141  | 0.652   | +25.2   | 150   | **0.707** | **+26.4** |
| nested_1H        | 22   | 0.409   | +0.9    | 32    | 0.406    | −3.6     |
| nested_4H        | 22   | 0.364   | −3.7    | 27    | 0.444    | +0.2     |
| nested_Daily     | 21   | 0.286   | −11.5   | 38    | 0.474    | +3.1     |
| nested_any       | 194  | 0.572   | +17.2   | 229   | 0.616    | +17.3    |
| has_vp ∧ nested  | 111  | 0.640   | +23.9   | 118   | 0.678    | +23.6    |

**15m nesting is the kind of clean walk-forward we wish more cells had**:
IS lift +25, OOS lift +26, both with n > 140. Same ranking on the combo with
VP. The "nested_any" wash is purely the contribution of 15m diluted by the
other three TFs.

The 1H/4H/Daily cells flip sign or stay flat between IS and OOS — small n,
no useful signal. Drop them.

## Kill criteria

* Data audit clean → not a "can't be tested" case.
* `nested_15m` OOS lift = **+26.4pp** → well above the +3pp survival
  threshold. Signal lives.
* `nested_any` is a slightly noisier stand‑in (+17pp OOS) but mostly just
  recovers 15m diluted.

## Why this matters

This shifts where ICT‑style HTF confluence actually shows up. The folk
wisdom ("look for 4H / Daily FVG nesting") is **not** what the data
supports — at least not at this trade size. The 15‑minute HTF FVG, sitting
just above the 5m FVGC, is doing all the work.

Two interpretations:

1. The 15m HTF FVG is **near enough to entry to materially affect price
   reaction**, while 4H/Daily FVGs are far enough away that the entry
   sitting "inside" them isn't actually doing much locally.
2. There are simply more 15m FVGs (~141k rows vs. ~26k Daily), so the
   sample of nested trades is much larger and statistically stable; the
   HTF effects may exist but n=21‑59 is too small to detect.

The honest read is "we have a strong 15m signal; the larger HTFs are
under‑powered on this sample, not refuted."

## Outputs

```
results/per_tf_full.csv     full-sample per-TF + compound cells
results/walk_forward.csv    IS / OOS per-TF + compound cells
results/yearly.csv          per-year nested lift by TF
results/vp_stack.csv        nested × n_vp_targets stacking
results/run.log             stdout
```

## Suggested next steps

1. **Add `nested_15m` as a playbook factor** (gate or score-add) — single
   biggest hit_2R lift with stable walk-forward we've found outside the
   confirmed VP / OR_HL cells.
2. **Stack with existing A+ cells** (`or_60_100 × long`, `n_vp_targets ≥ 2`,
   bs=2 morning narrative) to see whether nested_15m is additive or
   already captured.
3. **Re‑run on the larger M1/M2 cell sample if available** — the 1H/4H/Daily
   cells may light up with more n.
4. **15m HTF FVG distance‑band study** — distinguish "entry deep in the
   middle of a 15m FVG" from "entry grazing the edge." The current binary
   nesting flag throws that information away.
