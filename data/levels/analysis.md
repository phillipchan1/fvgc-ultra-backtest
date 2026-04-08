# Level proximity pipeline

This folder builds session/HTF liquidity levels from NQ data, joins them to baseline trades, and summarizes how often price is near those levels in R units relative to stop distance.

## Data sources

| Use | File |
|-----|------|
| Level construction (session H/L, HTF FVGs) | `data/consolidated/nq-front-month.ohlcv-30s.csv` — same validated front-month series the backtest engine uses (`load_nq_consolidated` / `nq_1m_front`); aggregated to 15m / 1H / 4H / daily as needed |
| Swept-before-entry + sweep filter (enrichment) | `data/raw/glbx-mdp3-20231002-20251027.ohlcv-30s-trading-session.csv` — bar-by-bar from RTH open through entry (session-scoped file; not the same path as consolidated) |
| Trading calendar | `data/trading_days/trading_days.csv` |
| Trades | `logs/baseline_trades.csv` |

Session/HTF builders resample the consolidated 30s bars to higher timeframes. Enrichment uses the separate raw **session** 30s file only for in-session sweep detection (window may differ slightly in symbol/calendar coverage from consolidated).

**Coverage:** A session `date` appears in `liquidity_levels.csv` only if that calendar day has at least one bar in the consolidated file (`date_ny`). Gaps in the consolidated feed skip those dates entirely (no stub rows). PDH/PDL for a session always come from the prior trading day’s RTH in that same consolidated series when both days exist.

## Single output: `liquidity_levels.csv`

`build_liquidity_levels.py` concatenates session rows (`build_session_levels.build_session_dataframe`) and HTF FVG rows (`build_htf_fvgs.build_htf_dataframe`), sorts by `(date, group, level_name)`, and writes one file.

- **Session H/L rows:** `timeframe`, `fvg_*`, `created_date`, `bars_old` are null; `price` is the level; `swept_pre_rth` / `swept_pre_rth_time` filled where the pre-RTH sweep applies.
- **HTF FVG rows:** `level_name` = `htf_fvg_{tf}_{direction}_{created_bar_idx}` (unique per gap instance); `price` = `fvg_mid` (single distance reference; `fvg_top` / `fvg_bottom` retain the zone); `group` = `htf_fvg_15m` / `htf_fvg_1H` / …; `side` = support for bullish, resistance for bearish; `available_time` = `open`. Pre-RTH sweep uses the gap **zone**: bullish if any overnight bar `low <= fvg_bottom`, bearish if any overnight bar `high >= fvg_top`.

Run **`python data/levels/build_liquidity_levels.py`** for production. `build_session_levels.py` and `build_htf_fvgs.py` accept **`--write`** to emit legacy debug CSVs only.

## FVG geometry (aligned with `fvgc/model.py`)

Gap math matches **`detect_fvg`** in `fvgc/model.py` (no `FVG_START_TIME` on HTF). Three-bar pattern uses candles `c1`, `c2`, `c3` at indices `idx-2`, `idx-1`, `idx`.

**Bullish FVG** (`c1['high'] < c3['low']`):

- Unfilled gap sits **above** `c1` and **below** `c3`: `bottom = c1['high']`, `top = c3['low']`.
- ASCII (price increases upward):

```
        c3  ─────────  high
            │ ░░░░░░░░ │   ← gap (bullish FVG): air between c1 high and c3 low
        c1  ─────────  high
```

Price **refilling from above** means wicks down: mitigation when a later bar’s **`low <= bottom`** (first touch of the lower gap edge).

**Bearish FVG** (`c1['low'] > c3['high']`):

- Gap between `c3['high']` and `c1['low']`: `bottom = c3['high']`, `top = c1['low']`.
- Refill from below: mitigation when a later bar’s **`high >= top`**.

This **wick-touch** rule is the same family as in `fvgc/model.py` for gap interaction; this pipeline applies it consistently for HTF mitigation and for sweep / enrichment.

## Implementation notes and known bugs fixed

### Prior trading day lookup (`_prior_trading_date`)

`trading_days.csv` dates are read as `datetime.date`, but the same calendar can appear as `pandas.Timestamp` in some pipelines. Using `list.index(d)` with mixed `Timestamp` vs `datetime.date` failed to find the session date, so the wrong prior index was used and **PDH/PDL** could reference the wrong session. **`_prior_trading_date` now normalizes every entry to `datetime.date` before comparison**, matching `by_date` keys from `date_ny`.

## Sweep states (three-way categorical)

Each level can be:

- **`available`** — not tagged as swept pre-RTH and not swept by 30s RTH bars from 9:30 through entry; still a valid magnet for proximity math.
- **`pre_rth`** — `swept_pre_rth = True` in `liquidity_levels.csv`: for session levels, overnight window touch; for HTF FVGs, overnight touch of the gap edge as above. Excluded from magnet / obstruction / path / confluence (no 30s check needed).
- **`in_session`** — not pre-RTH swept, but swept by **30s** bars from **9:30 → entry** (resistance: `high >= price`; support: `low <= price`; both: either). Treated as consumed liquidity for magnet math, but distinguishable for analysis of **RTH** vs **pre-open** consumption.

**Overnight session level rows** (`overnight_high` / `overnight_low`) are **not** assigned `swept_pre_rth` in the builder (same window as their definition). Pre-RTH sweep **is** computed for `prev_day_*`, `london_*`, `asia_*`, `6am_*`, `nwog_*` (when price is present), `bsl_level`, `ssl_level`, and **HTF FVG rows** (zone-based, as above). `or_*` stubs and null-price NWOG rows are skipped for session sweep.

The **`{group}_swept`** column records the state of the **nearest** time-gated level to entry **in the trade direction** (among all prices in that group): `pre_rth`, `in_session`, `available`, or empty if there is no candidate.

## Swept level handling (Option B + pre-RTH gate)

1. **Build time:** `liquidity_levels.csv` includes `swept_pre_rth` and `swept_pre_rth_time` where applicable.
2. **Enrichment:** If `swept_pre_rth` is true → **`pre_rth`**; else classify **`in_session`** vs **`available`** using 30s bars **9:30 → entry**. HTF rows use **bullish → support**, **bearish → resistance** for in-session wick rules vs `fvg_mid`.
3. **Magnet pool** = levels with state **`available`** only.
4. **`level_swept_before_entry`:** reference whether the **chosen** (available) magnet price was traded through in the 30s window (directional touch).

**`no_valid_levels`:** `True` when there is **no** level with sweep state **`available`** in the trade direction within **3R**.

**`available_level_count`:** number of **distinct groups** with **at least one** **`available`** level on the correct side of entry with **R ≤ 3** (points / `sl_dist`).

### HTF proximity extras (`trades_with_levels.csv`)

Per timeframe (`15m`, `1H`, `4H`, `Daily`):

- **`htf_fvg_{tf}_aligned_nearest_pts`** — distance to the nearest **`available`** FVG whose direction **matches** the trade (long ↔ bullish zone, short ↔ bearish zone), in the trade direction (same logic as group nearest).
- **`htf_fvg_{tf}_any_nearest_pts`** — nearest **`available`** FVG **mid** in the trade direction regardless of bullish/bearish.

## Level taxonomy and time gates

Templates are in `level_registry.py`. HTF FVG **instances** are dynamic rows in `liquidity_levels.csv` (not one static name per day). Enrichment loads all HTF rows for the session date from the file.

## HTF FVG methodology (`build_htf_fvgs.py`)

- Aggregated bars: **15m**, **1H**, **4H** via `pd.Grouper(freq=..., label='right', closed='right')` on NY `ts_ny`; **Daily** = OHLC by NY **`date_ny`** with bar label at that day’s 16:00 ET (RTH close).
- Chronological walk: on each bar, apply **wick mitigation** to pending FVGs, then detect a new FVG at `i` if `detect_fvg_htf` fires. Only **unmitigated** FVGs are scanned each bar (performance).
- **Morning snapshot** for session date `D` with `cutoff = 09:30` ET on `D`: include an FVG if **`created_ts <= cutoff`** and (**not mitigated** OR **`mitigated_ts >= cutoff`**), so gaps filled only *after* the open still appear as active at the bell. FVGs fully mitigated before open are omitted.
- **`bars_old`:** count of HTF bars with `timestamp_ny < cutoff` and `timestamp_ny > created_ts`.
- A gap can remain unmitigated for a long time on HTF; the snapshot can therefore list **many** FVG rows per date per timeframe until wick mitigation occurs.

## Outputs

### `liquidity_levels.csv` (unified schema)

| Column | Meaning |
|--------|---------|
| `date` | NY session / snapshot date |
| `level_name` | Session registry name or `htf_fvg_{tf}_{dir}_{idx}` |
| `group` | Proximity group |
| `side` | resistance / support / both |
| `price` | Session: level price; HTF: **`fvg_mid`** |
| `available_time` | Gate for enrichment (`open` for HTF) |
| `swept_pre_rth`, `swept_pre_rth_time` | Pre-RTH sweep where applicable |
| `timeframe` | `15m` / `1H` / `4H` / `Daily` for HTF; empty for session |
| `fvg_direction`, `fvg_top`, `fvg_bottom`, `fvg_mid` | HTF only |
| `created_date`, `bars_old` | HTF only |
| `notes` | Builder notes |

### `trades_with_levels.csv`

Original baseline columns, then **aggregates:**

| Column | Meaning |
|--------|---------|
| `nearest_magnet_pts`, `nearest_magnet_R`, `nearest_magnet_group` | Tightest **available** magnet in R units |
| `magnet_valid` | Nearest **available** magnet within **3R** |
| `magnet_within_1R` / `2R` / `3R` | Cumulative vs `nearest_magnet_R` |
| `nearest_obstruction_*`, `obstruction_count`, `path_clear` | From **available** levels only, price strictly between entry and TP |
| `level_confluence_count` | Distinct groups with an **available** level within 10 pts of the magnet price |
| `level_swept_before_entry` | Reference: 30s window vs chosen available magnet |
| **`available_level_count`** | Distinct groups with ≥1 **`available`** level in trade direction with R ≤ 3 |
| **`no_valid_levels`** | **True** if no **`available`** level within 3R in direction |
| **`htf_fvg_{tf}_aligned_nearest_pts`**, **`htf_fvg_{tf}_any_nearest_pts`** | See above |

Then **per group** (registry order): `{group}_nearest_price`, `{group}_nearest_pts`, `{group}_nearest_R`, **`{group}_swept`** (`pre_rth` \| `in_session` \| `available`).

**3R cap:** `magnet_valid` flags magnets within 3R so “far” liquidity does not dominate naive hit-rate analysis.

### `results/` (from `study_level_proximity.py`)

- `summary_by_magnet_R_bucket.csv` — WR/PF by `nearest_magnet_R` and `no_valid_levels`
- `summary_by_path_clear.csv`, `summary_by_obstruction_count.csv`, `summary_by_magnet_group.csv`, `summary_by_confluence.csv`
- **`summary_by_available_level_count.csv`** — WR/PF by `available_level_count` (0, 1, 2, 3+). The **0** bucket is the control: trades with no **available** narrative context within 3R.
- `summary_by_existing_clusters.csv` — `magnet_valid` × `path_clear` for selected short cohorts vs others
- `trades_verified.csv` — manual QA columns (see script for order)

`macro_window` in the study matches `analysis/permutation_test.py`: 1–4 = first four 15m blocks from 9:30; 5 = after 10:30.

## Adding a new level type

1. Add one row to **`LEVEL_REGISTRY`** in `level_registry.py` (name, group, side, `available_time`, builder, optional timeframe).
2. Extend **`build_session_levels.py`** or **`build_htf_fvgs.py`** to emit rows with the unified schema; rerun **`build_liquidity_levels.py`**.

## Known limitations

- HTF FVG mitigation uses **wick** touch at gap edges as specified above.
- Sweep filter uses **30s** bars; sub-30s spikes are invisible.
- **`price` for HTF = `fvg_mid`** — single reference point; edge-aware distance is a possible follow-up.

## Commands

```bash
python data/levels/build_liquidity_levels.py
python data/levels/enrich_trades_with_levels.py
python data/levels/study_level_proximity.py
```

Debug-only CSVs: `python data/levels/build_session_levels.py --write`, `python data/levels/build_htf_fvgs.py --write`.
