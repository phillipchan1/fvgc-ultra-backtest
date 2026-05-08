# Study: OR Sweep State by 10:15 ET

## Question
Does sweeping one side of the 9:30-9:45 opening range (OR) change FVGC expectancy for continuation vs fade entries?

Core hypothesis from the study brief: once one OR side is swept, the opposite side is unlikely to be swept by 10:15, so continuation to the opposite OR side may underperform.

## Methodology
- Data/timeframes:
  - `data/consolidated/nq-front-month.ohlcv-30s.csv`
  - `data/consolidated/nq-front-month.ohlcv-1m.csv`
- Per-day sweep classification on 9:45-10:15 window:
  - `neither`, `only_H_swept`, `only_L_swept`, `both_swept`
- Sweep definitions:
  - `loose`: any wick beyond OR boundary
  - `strict`: wick-through + close back inside OR
- Trade tagging:
  - Use FVGC entries from `generate_signals()` + `simulate_trades()`
  - Keep entries from 9:45-11:00, with primary focus on entries before 10:15
  - Label each trade by sweep state at entry and play type:
    - `L_swept_first→long(cont→OR.H)`
    - `L_swept_first→short(fade)`
    - `H_swept_first→short(cont→OR.L)`
    - `H_swept_first→long(fade)`
    - `baseline` (no first-sweep context yet)
- Outputs:
  - `results/or_sweep_days_30s.csv`
  - `results/or_sweep_days_1m.csv`
  - `results/or_sweep_state_30s_loose.csv`
  - `results/or_sweep_state_30s_strict.csv`
  - `results/or_sweep_state_1m_loose.csv`
  - `results/or_sweep_state_1m_strict.csv`

## Results
### Part A: Sweep base rates by 10:15 (loose definition)
From `or_sweep_days_30s.csv` (same day-level classification as 1m):
- Total days: 580
- `only_L_swept`: 234 (40.3%)
- `only_H_swept`: 226 (39.0%)
- `both_swept`: 92 (15.9%)
- `neither`: 28 (4.8%)

Conditional second-sweep probability:
- Given H swept first: `P(L also swept by 10:15) = 16.9%` (n=272)
- Given L swept first: `P(H also swept by 10:15) = 16.4%` (n=280)

Interpretation: once one side is swept first, the opposite side is swept by 10:15 only about 1 in 6 sessions.

### Part B: FVGC outcomes by play cell (primary 9:45-10:15 window, loose)
#### 30s run (`or_sweep_state_30s_loose.csv`, n=1128)
- `L_swept_first→long(cont→OR.H)`: n=220, WR=50.9%, PF=1.09
- `L_swept_first→short(fade)`: n=366, WR=53.2%, PF=1.20
- `H_swept_first→short(cont→OR.L)`: n=149, WR=38.9%, PF=0.69
- `H_swept_first→long(fade)`: n=354, WR=58.0%, PF=1.20
- `baseline`: n=39, WR=25.6%, PF=0.32

#### 1m run (`or_sweep_state_1m_loose.csv`, n=558)
- `L_swept_first→long(cont→OR.H)`: n=87, WR=47.1%, PF=0.94
- `L_swept_first→short(fade)`: n=204, WR=53.2%, PF=1.22
- `H_swept_first→short(cont→OR.L)`: n=59, WR=49.2%, PF=1.06
- `H_swept_first→long(fade)`: n=196, WR=48.0%, PF=0.85
- `baseline`: n=12, WR=8.3%, PF=0.05

## Conclusions
- The day-level premise holds: opposite-side sweep by 10:15 is uncommon (~16-17%) after first sweep.
- On the 30s sample, continuation after an H-first sweep (`H→short`) is the weakest cell (WR 38.9%, PF 0.69), while the corresponding fade (`H→long`) outperforms (WR 58.0%, PF 1.20).
- For L-first sweeps, fade (`L→short`) edges continuation (`L→long`) on WR/PF in both 30s and 1m snapshots.
- Net: this study supports using OR sweep state as a directional confluence/avoid filter, especially to avoid `H-first then short continuation` in the primary 30s sample.

## Notes
- The files include both loose and strict sweep definitions; numbers above use loose because it is the primary operational definition in the study brief.
- No permutation significance test is included in this study; results should be treated as descriptive edge profiling rather than final statistical proof.
