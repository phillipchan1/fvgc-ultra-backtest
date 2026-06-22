# FVGC Morning Levels — TradingView indicator

Auto-draws the pre-market + in-session levels you draw by hand every morning, as
neat black lines with labels, and **cuts each line at the candle where liquidity
was taken**.

## Install
1. TradingView → **Pine Editor** → paste `morning_levels.pine` → **Add to chart**.
2. Best on a **30s or 1m NQ chart** (matches your workflow; the Data-candle logic
   pulls 1-minute data regardless of chart timeframe).
3. Make sure the symbol is the CME contract (NQ1!) so the session clock lines up
   with `America/New_York` (the script forces NY time internally — your chart's
   display timezone doesn't matter).

## Levels drawn (all match `data/levels/build_session_levels.py`)
| Label | Window (NY) | Side |
|---|---|---|
| Prev Session High/Low | prior RTH 09:30–16:00 | sweep on touch |
| Asia High/Low | prior 19:00 → 02:00 | |
| London High/Low | 02:00 → 08:00 | |
| 6am High/Low | 04:00 → 08:00 | |
| Overnight High/Low | prior 18:00 → 09:30 | |
| OR High/Low | 09:30 → 09:45 (forms at 09:45) | |
| Daily 50% | CME 18:00 → 17:00 midpoint | |
| NWOG High/Low | Mondays: Fri RTH close ↔ Mon RTH open | |
| Data High/Low | a 1m candle with range > threshold | |
| 15M Gap / 1H Gap | 3-candle FVG ≥ min size | cut when filled |

## Behaviour
- **Sweep cut** — a line extends right until price trades through it, then stops
  at that exact candle (your "horizontally cuts where it happened").
- **Confluence merge** — levels within `Confluence merge tolerance` (default 5 pts)
  collapse into **one line with a combined label**, e.g. `6am Low + London Low`.
- **Distance filter** — only levels within `Max distance` of price (default 300 pts)
  are shown. Set to 0 to disable.
- **Session shading** — faint Asia / London / RTH background tints (toggle off in
  Display).

## Two honest constraints
1. **"Data H/L" has no news feed.** Pine can't read an economic calendar, so a
   "data candle" is detected by **size** — any 1-minute candle whose range exceeds
   `Min 1m candle range` (default **60 pts**) inside the data window (default
   **08:00–09:30 ET**, i.e. pre-market data drops only). That's a proxy for
   red-folder spikes, not the actual calendar. Widen `Data window end` if you want
   to flag big intraday candles too.
2. **Bold is faked with Unicode.** Pine has no native font-weight, so the
   `Bold labels (unicode)` toggle (default on) maps label text to Unicode
   mathematical-bold glyphs to match your hand-drawn labels. If your TradingView
   font renders them oddly, turn it off. Exact pixel sizes aren't available either
   — pick `tiny/small/normal/large`. Lines are true black, width configurable.

Lines now originate at **the exact candle that printed the high/low** (not the
session-window end), so the left anchor matches where the level was actually made.

## Key inputs
- **Display**: max distance, confluence tolerance, line color/width, label size,
  label offset, session shading, prune age.
- **Levels**: toggle each level on/off.
- **Data candle**: min range + window.
- **FVG / Gaps**: toggle 15m / 1H, min FVG size, fill color.
