# Enhanced 930 Gap Strategy Analysis

## What This Answers

Your key questions:

1. **Is the 930 gap advantage ONLY about trades at exactly 9:30, or is it spread across the first 15 min?**
   - Breaks 930 shorts into **5-minute buckets**: 9:30-9:35, 9:35-9:40, 9:40-9:45
   - Shows WHERE in the 930 window the wins are concentrated

2. **How do 930 shorts (74.1% WR) compare to ALL shorts in the first 15 min?**
   - Compares win rates across equivalent 5-min buckets
   - Shows the WR advantage (or disadvantage) for 930 shorts vs baseline shorts at each time window

3. **What OTHER factors characterize winning 930 shorts?**
   - Compares FVG size, entry price, fill metrics, stops/targets
   - Shows if winners have specific trade structure characteristics

## How to Run

```bash
python studies/fvgc_plays_off_930_candle/enhanced_analysis.py
python studies/fvgc_plays_off_930_candle/enhanced_analysis.py --window tight
```

## What It Outputs

### Console Output (5 sections)

**Section 1: Baseline vs 930 Overview**
```
All baseline trades               n=1572  WR=51.7%  PnL=...
FVG created in 930 window (all)   n=100   WR=61.0%  PnL=...
  930 long                         n=46    WR=45.7%  PnL=...
  930 short                        n=54    WR=74.1%  PnL=...
```

**Section 2: Where Are 930 Short Wins?**
```
Total 930 shorts: 54
  Bucket 1 (9:30-9:35 min)        n=?     WR=?%    PnL=...
  Bucket 2 (9:35-9:40 min)        n=?     WR=?%    PnL=...
  Bucket 3 (9:40-9:45 min)        n=?     WR=?%    PnL=...
```

**Section 3: Baseline Shorts by 5-Min Window**
```
Baseline shorts in first 15 min: (total count)
  Baseline shorts bucket 1        n=?     WR=?%    PnL=...
  Baseline shorts bucket 2        n=?     WR=?%    PnL=...
  Baseline shorts bucket 3        n=?     WR=?%    PnL=...
```

→ **Here's where you'll see if 930 shorts are better than baseline shorts at EACH time slice**

**Section 4: What Makes 930 Shorts Win?**
```
Winning 930 shorts (n=X):
  fvg_size                    mean=...  median=...
  entry_offset_from_fvg_bottom  mean=...  median=...
  fill_bar_count              mean=...  median=...
  ...

Losing 930 shorts (n=Y):
  [same metrics for losers]
```

→ **Direct comparison of winner vs loser characteristics**

### CSV Files

- `trades_930_shorts_detailed_default.csv` — all 930 shorts with all fields
- `trades_930_shorts_by_bucket_default.csv` — same data + new `bucket_5min_label` column for easy filtering

## Interpretation Guide

### Example Findings

**Scenario A: All 930 wins in bucket 1 (9:30-9:35)**
- The advantage is **ultra-tight**: specifically the opening 5 seconds to 5 min window
- 930 trades after 9:35 lose the edge
- **Implication:** Tight entry timing is critical

**Scenario B: Wins spread across all three 5-min buckets**
- The advantage is **robust across the window**
- 930 opening period = any trade initiated within first 15 min if FVG created at 9:30
- **Implication:** Less sensitive to exact entry timing

**Scenario C: 930 shorts WR 74.1%, bucket-1 baseline shorts WR 45%**
- **Real edge:** Not just "shorts are better at 9:30" but "shorts from 930 FVGs are better"
- The gap cohort / FVG micro-structure filter adds significant edge beyond time-of-day

**Scenario D: Winning 930 shorts have smaller FVG size vs losers**
- Smaller, tighter FVGs = better execution + faster fill
- May suggest the "cleanest" 930 gaps are the ones with smaller daily range

## Technical Notes

- **Bucket assignment:** 5 minutes = single 30s candle + 9 more = 10 consecutive 30s bars
  - Bucket 1: bars at 9:30:00, 9:30:30, ..., 9:34:30
  - Bucket 2: bars at 9:35:00, 9:35:30, ..., 9:39:30
  - Bucket 3: bars at 9:40:00, 9:40:30, ..., 9:44:30

- **Minutes into session:** `(entry_hour - 9) * 60 + (entry_minute - 30) + seconds/60`
  - Entry at 9:30:00 = 0 min
  - Entry at 9:35:30 = 5.5 min
  - Entry at 9:45:00 = 15 min

## Next Steps

Once you run this:
1. Check if 930 advantage is concentrated or spread
2. Look for the structural difference (FVG size, entry offset, etc.)
3. Consider: does the 930 filter + time bucket combo identify a single sweet spot?
4. Validate on new data: are these patterns stable month-to-month?
