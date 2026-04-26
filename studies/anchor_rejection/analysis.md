# Anchor Rejection — does the 9:30-gap-fade mechanic generalize?

## Question

Phil's 9:30 gap-up + bearish-9:30-candle short play hits ~75% WR with its
natural gap-sized bracket. Does the underlying mechanism — *fade the failure of
a fixed liquidity event* — survive when the same idea is applied to other
anchors (OR15 sweeps, prior-day H/L, prior-day VAH/VAL)?

## Method

Eight anchors, two trigger archetypes, one **standardized** bracket so the
table is apples-to-apples:

| Anchor                       | Archetype           | Direction | Search window |
|------------------------------|---------------------|-----------|---------------|
| `930_gap_short` (control)    | entry_bar           | short     | 9:30→11:00 |
| `930_gap_long`               | entry_bar           | long      | 9:30→11:00 |
| `or15_sweep_reject_short`    | first_touch_reject  | short     | 9:45→11:00 |
| `or15_sweep_reject_long`     | first_touch_reject  | long      | 9:45→11:00 |
| `pdh_first_touch_reject`     | first_touch_reject  | short     | 9:30→11:30 |
| `pdl_first_touch_reject`     | first_touch_reject  | long      | 9:30→11:30 |
| `vah_first_touch_reject`     | first_touch_reject  | short     | 9:30→11:30 |
| `val_first_touch_reject`     | first_touch_reject  | long      | 9:30→11:30 |

**Standardized bracket (`--bracket atr`, default):**
- `sl_dist = max(MIN_STOP_PTS=15, ATR_FRAC=0.30 * prior_day_atr_14)`
- `tp_dist = TP_R=1.0 * sl_dist` (1R target)
- `time_stop = anchor's window end`

**Note:** this bracket is *deliberately not* the natural one for any of these
plays. The gap short's headline 75% WR uses a gap-sized bracket; here we
intentionally throw that away to compare *mechanisms* (does the fade work?),
not headlines (how well does the bracket fit?).

**Optional `--bracket structural`:** stop set beyond the trigger-bar wick + 2pt
buffer instead of ATR-based, with the same 1R TP. Lets us check if the ranking
is bracket-dependent.

**Trigger detail for `first_touch_reject`:** walk the search window; first 30s
bar whose `high > level` AND `close < level` (short; mirror for long); also
require the day's RTH open is on the approach side. Entry at the next bar's
open. Trigger bar is the rejection bar (used for the structural stop).

Filters intentionally **not** applied: news / VIXY regime / day-of-week —
the goal here is the raw mechanical edge per anchor.

## Data

- 30s NQ front-month, 2023-10-01 → 2026-03-25 (≈ 30 months, 580 trading days)
- Daily levels (PDH/PDL/PDC/ATR14) computed from RTH 30s bars
- Prior-day VAH/VAL from `data/levels/daily_volume_profile.csv` (579/580 days covered)

## Results — `--bracket atr`

```
  anchor                          n    W    L   TS      WR     PF   meanR     totR    maxDD    /mo
  ------------------------------------------------------------------------------------------------------------
 *930_gap_short                 179   71   69   39   50.7%   0.94    0.01      1.6     -7.6    6.0
  930_gap_long                  114   55   38   21   59.1%   1.48    0.17     19.5     -8.2    3.8
  or15_sweep_reject_short       337   81   94  162   46.3%   0.73   -0.12    -38.9    -42.0   11.3
  or15_sweep_reject_long        342   91  106  145   46.2%   1.03   -0.00     -1.1    -18.6   11.5
  pdh_first_touch_reject        120   33   28   59   54.1%   1.31    0.03      3.0    -11.4    4.0
  pdl_first_touch_reject        100   44   32   24   57.9%   1.15    0.09      9.1     -6.5    3.4
  vah_first_touch_reject        134   41   45   48   47.7%   0.86   -0.08    -10.4    -12.0    4.5
  val_first_touch_reject        121   47   42   32   52.8%   1.05    0.05      5.5     -9.4    4.1
```

### Key observations

1. **The 930-gap headline does not survive a generic ATR bracket.** Control
   prints 50.7% / PF 0.94 vs the 75% headline — confirming that the natural
   play's edge is partly in the *bracket fit* (gap-sized stop + gap-fraction
   target tracking the move), not just in the trigger.

2. **`930_gap_long` is the surprise winner.** 59.1% WR, PF 1.48, +0.17 mean R.
   Symmetric control was supposed to be a sanity check; instead it suggests
   gap-down + bullish 9:30 candle is *more* mechanically robust under a generic
   bracket than the famous short version. Worth a dedicated playbook study.

3. **PDH / PDL first-touch-reject is the only other family that holds up.**
   Both above 54% WR, both PF > 1.1, both positive total R. PDL slightly
   stronger on per-trade R (0.09 vs 0.03), but PDH has more conviction in PF.
   These are credible candidates for promotion to a playbook cell — they
   don't need news/regime filters to break-even with a generic bracket.

4. **OR15 sweep-reject is the worst family.** Both directions sub-50% WR,
   PF < 1.05, and ~50% of trades **time-stop** (162 of 337 shorts). Reading:
   the 9:45 OR is too noisy a level for naked rejection-fades — sweeps either
   continue (loss) or chop sideways (time-stop). Skip unless paired with a
   confluence factor.

5. **VAH/VAL is mediocre.** VAH is a weak short (47.7% / PF 0.86), VAL is
   marginally positive long. Mixed signal — the prior-day value-area edges
   aren't a free lunch by themselves.

## Results — `--bracket structural`

```
  anchor                          n    W    L   TS      WR     PF   meanR     totR    maxDD    /mo
  ------------------------------------------------------------------------------------------------------------
 *930_gap_short                 179   80   98    1   44.9%   0.92   -0.10    -18.7    -19.7    6.0
  930_gap_long                  114   46   68    0   40.4%   0.72   -0.19    -22.0    -25.0    3.8
  or15_sweep_reject_short       337  159  171    7   48.2%   0.90   -0.04    -12.2    -26.7   11.3
  or15_sweep_reject_long        342  168  168    6   50.0%   0.97   -0.01     -2.4    -27.6   11.5
  pdh_first_touch_reject        120   61   57    2   51.7%   1.26    0.03      3.4    -13.7    4.0
  pdl_first_touch_reject        100   50   50    0   50.0%   0.90    0.00      0.0    -10.0    3.4
  vah_first_touch_reject        134   63   65    6   49.2%   0.84   -0.03     -4.4    -13.8    4.5
  val_first_touch_reject        121   46   73    2   38.7%   0.61   -0.22    -26.4    -33.6    4.1
```

### What the bracket swap reveals

- **Time-stops nearly disappear** (1–7 per anchor vs 21–162 on ATR). Tighter
  stops mean almost every trade resolves to win/loss inside the window.
- **The 930-gap *long* edge collapses** under structural stops (40% WR /
  PF 0.72). Reading: that ATR-bracket result was leaning on TP fitting inside
  the gap-day's range, not on trigger-bar wick rejection.
- **PDH first-touch-reject is the only anchor robust across both brackets**
  (54%/PF 1.31 ATR; 51.7%/PF 1.26 structural). That's the strongest
  mechanism-survives-bracket-choice signal in the table — promote candidate.
- **VAL collapses** (52.8% → 38.7%) — its trigger-bar wicks are too shallow on
  30s, so the structural stop is too tight to survive normal noise.

## Verdict

The fade-the-failure-of-a-fixed-liquidity-event mechanism does **not**
generalize uniformly. Bracket choice matters as much as anchor choice for
most plays. Of the seven non-control anchors:

| Anchor | Robust across brackets? | Mechanism survives? |
|---|---|---|
| `930_gap_long` | ❌ (collapses on structural) | Bracket-dependent |
| `pdh_first_touch_reject` | ✅ | **Yes** |
| `pdl_first_touch_reject` | partial (PF 1.15→0.90) | Marginal |
| `or15_sweep_reject_*` | ❌ | No |
| `vah_first_touch_reject` | ❌ | No |
| `val_first_touch_reject` | ❌ | No |

**Next steps** (out of scope for this study):
- Run PDH/PDL first-touch-reject through the regime / news / DOW filter grid
  used in `small_gap_fade` to see if a high-WR cell exists.
- Re-run the 930-gap *long* with its natural bracket to see if 59% WR translates
  into a shippable cell.
- Consider an **8:30 econ-news anchor** (rejection of the post-news spike) —
  not implemented in this first cut because pre-RTH 30s data presence varies
  across the dataset and needs a coverage check first. **TODO.**

## Reproduce

```bash
git lfs pull   # data files are LFS-tracked
python studies/anchor_rejection/run.py                     # ATR bracket (default)
python studies/anchor_rejection/run.py --bracket structural
```

Outputs: `results/trades_<anchor>.csv` per anchor and `results/summary.csv`
(with `_structural` suffix for the alternative bracket).
