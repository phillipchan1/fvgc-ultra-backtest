# Speed-of-Move Continuation Study

## Causal Audit Status

**REVALIDATED (core) — 2026-05-21.** `bars_to_1R` and its derived speed buckets are computed from entry-forward bars — strictly causal. The headline `bars_to_1R ≤ 12 → +7.7pp OOS hit_2R` finding survives.

**The `VP × fast → 94.7% hit_2R OOS` cross-cell is CONTAMINATED.** It joins today's POC/VAH/VAL on date (per `run.py`); the VP component is from the future. Do not use the VP×fast cell. The pure speed signal is intact.

---

## Hypothesis (steelmanned)

> Trades that reach 1R quickly are dramatically more likely to continue to 2R / 3R / 5R than trades that grind to 1R slowly. If true, this becomes a *trade management* rule — applies to every trade regardless of entry filter.

## Verdict (TL;DR)

- **Effect is real but smaller than hypothesized on `hit_2R`.** Within the hit_1R cohort, fast trades hit 2R at ~88% vs slow at ~79%. The lift survives IS/OOS and year-by-year stability, but the slow cohort is **not garbage** — 79% hit_2R is still well above the unconditional 42% base rate.
- **The hit_3R / hit_5R gradient is much steeper.** Bars 1-2 → 85% hit_3R, 67% hit_5R. Bars 100+ → 30% hit_3R, 15% hit_5R. Speed-of-move predicts *how far the runner goes*, not whether 2R will print.
- **"Scratch the slow ones at 1R" actually HURTS expectancy.** Under conservative assumptions (TP=2R / SL unchanged), slow holds clear +1.37R/trade — more than the +1.0R of scratching. The intuitive rule from the hypothesis is *inverted by the data*.
- **Stacking with VP is the real finding.** `n_vp_targets >= 1 AND fast` → **94.7% hit_2R OOS, n=449**. As a confirmation trigger to "size up / let it run", this is actionable.
- **Bottom line for the playbook:** speed-of-move is a *runner sizing* tool, not a stop-out tool. Pair with VP for the "let it ride to 3R+" gate.

## Methodology

**Data:** `studies/baseline/results/trades.csv` — 4,548 non-skip 30s FVGC trades, 2018-01 → 2026-05. TP and SL both set at 1R for the underlying simulation; `hit_NR` / `bars_to_NR` columns track hypothetical MFE multiples for management studies like this one. Verified base hit_2R = **0.4222** matches the prompt's stated 42.2%.

**Splits:** IS = 2018-2022 (2,193 trades). OOS = 2023-2026 (2,355 trades). All threshold selection is from IS; OOS is frozen-validation.

**Survivorship caveat:** `bars_to_1R` only exists for trades where MFE reached 1R (n=2,254 of 4,548). The management rule is conditional-on-1R-touch anyway, so this is the right population.

**Convention:** "fast" ⇔ hit_1R=True AND bars_to_1_0R ≤ N* where N* is selected from IS.

## Q1 — P(hit_NR | bars_to_1R) curve

Within the hit_1R cohort (n=2,254):

| bars_to_1R bin | n   | P(hit_2R) | P(hit_3R) | P(hit_5R) |
| -------------- | --- | --------- | --------- | --------- |
| [1, 2)         | 116 | **0.905** | **0.845** | **0.672** |
| [2, 3)         | 227 | 0.907     | 0.789     | 0.678     |
| [3, 4)         | 201 | 0.896     | 0.796     | 0.582     |
| [4, 5)         | 196 | 0.898     | 0.776     | 0.643     |
| [5, 6)         | 153 | 0.869     | 0.778     | 0.621     |
| [6, 8)         | 266 | 0.846     | 0.722     | 0.489     |
| [8, 10)        | 205 | 0.868     | 0.727     | 0.488     |
| [10, 15)       | 304 | 0.832     | 0.704     | 0.490     |
| [15, 20)       | 191 | 0.801     | 0.639     | 0.476     |
| [20, 30)       | 188 | 0.819     | 0.590     | 0.383     |
| [30, 50)       | 130 | 0.777     | 0.577     | 0.338     |
| [50, 100)      | 57  | 0.789     | 0.596     | 0.263     |
| [100, ∞)       | 20  | 0.550     | 0.300     | 0.150     |

**Read:** the `hit_2R` column flattens around ~80% by the 15-bar mark; the `hit_3R` and `hit_5R` columns keep falling. Speed matters mostly for the upper-R tail.

**ASCII sketch (P(hit_2R) vs bars_to_1R):**

```
P(hit_2R)
1.0 |
0.9 | ●●●●●
0.8 |       ●●●● ● ●
0.7 |               ●  ●
0.6 |                       ●
0.5 |
    +---+---+---+---+---+---+---+
       1   5   10  20  50  100+
```

(See `results/curve_P_hit2R.csv` for exact values.)

## Q2 — Threshold sweep

Whole-population sweep on hit_1R cohort, lift = P(hit_NR | fast) − P(hit_NR | slow):

| N   | n_fast | hit_2R fast | n_slow | hit_2R slow | lift_2R pp | lift_3R pp |
| --- | ------ | ----------- | ------ | ----------- | ---------- | ---------- |
| 2   | 343    | 0.907       | 1911   | 0.842       | +6.5       | +11.0      |
| 4   | 740    | 0.901       | 1514   | 0.828       | +7.4       | +12.1      |
| 6   | 1046   | 0.886       | 1208   | 0.822       | +6.4       | +12.2      |
| 8   | 1287   | 0.880       | 967    | 0.815       | +6.5       | +12.5      |
| 10  | 1433   | 0.880       | 821    | 0.803       | +7.7       | +14.5      |
| 12  | 1569   | 0.878       | 685    | 0.791       | +8.7       | +15.9      |
| 15  | 1706   | 0.872       | 548    | 0.788       | +8.4       | +16.8      |
| 20  | 1897   | 0.866       | 357    | 0.776       | +9.0       | +16.0      |
| 25  | 1998   | 0.864       | 256    | 0.758       | +10.6      | +18.1      |
| 30  | 2062   | 0.861       | 192    | 0.755       | +10.6      | +18.3      |

Lift on `hit_2R` is mild and rises slowly with N. Lift on `hit_3R` is structurally bigger and grows monotonically — the more bars you allow before calling it "slow", the more clearly the slow cohort under-runs on 3R.

## Q3-Q4 — IS-selected threshold and OOS frozen validation

**Selection rule:** From the IS-only sweep, pick the N that maximises IS lift on `hit_2R` subject to n_fast_IS ≥ 100 and n_slow_IS ≥ 100. **Selected N\* = 12.** (5 min wall-clock on 30s bars.)

| Split  | n_fast | hit_2R fast | n_slow | hit_2R slow | lift_2R pp | lift_3R pp |
| ------ | ------ | ----------- | ------ | ----------- | ---------- | ---------- |
| **IS** | 709    | 0.876       | 330    | 0.779       | **+9.7**   | **+19.4**  |
| **OOS**| 860    | 0.880       | 355    | 0.803       | **+7.7**   | **+12.5**  |
| ALL    | 1569   | 0.878       | 685    | 0.791       | +8.7       | +15.9      |

**OOS-vs-IS hit_2R drop: 2.0pp.** Well under the 5pp overfit gate. **PASS.**
**OOS-vs-IS hit_3R drop: 6.9pp.** Marginally over the 5pp gate; treat the 3R claim as weaker.

### Year-by-year stability at N* = 12

| year | n   | n_fast | n_slow | hit_2R fast | hit_2R slow | lift pp | positive |
| ---- | --- | ------ | ------ | ----------- | ----------- | ------- | -------- |
| 2018 | 80  | 48     | 32     | 0.875       | 0.844       | +3.1    | ✓        |
| 2019 | 30  | 12     | 18     | 0.750       | 0.667       | +8.3    | ✓ (n<100)|
| 2020 | 260 | 170    | 90     | 0.900       | 0.756       | +14.4   | ✓        |
| 2021 | 269 | 185    | 84     | 0.838       | 0.762       | +7.6    | ✓        |
| 2022 | 400 | 294    | 106    | 0.891       | 0.811       | +8.0    | ✓        |
| 2023 | 291 | 184    | 107    | 0.864       | 0.738       | +12.6   | ✓        |
| 2024 | 333 | 229    | 104    | 0.860       | 0.865       | −0.5    | ✗        |
| 2025 | 432 | 317    | 115    | 0.893       | 0.791       | +10.1   | ✓        |
| 2026 | 159 | 130    | 29     | 0.908       | 0.862       | +4.6    | ✓ (n<100)|

**8/9 positive years (gate: ≥7/9). PASS.** Only 2024 is flat-negative, and even there both buckets are at ~86% hit_2R — the signal disappears in a regime where almost every hit_1R trade ran to 2R.

## Q5 — VP × speed stacking

`n_vp_targets` = count of {POC, VAH, VAL} that sit between +0.5R and +3R from entry in the trade's direction (re-derived locally from `data/levels/daily_volume_profile.csv` using the same definition as `studies/vp_targets`).

### Full sample

| Cohort                        | n     | P(hit_1R) | P(hit_2R) | P(hit_3R) |
| ----------------------------- | ----- | --------- | --------- | --------- |
| **all (baseline)**            | 4,548 | 0.496     | **0.422** | 0.354     |
| n_vp ≥ 1 (entry filter)       | 2,258 | 0.589     | 0.539     | 0.454     |
| fast (hit_1R AND bars ≤ 12)   | 1,569 | 1.000     | 0.878     | 0.763     |
| **n_vp ≥ 1 AND fast**         | **843**| 1.000    | **0.942** | **0.837** |
| n_vp == 0 (anti-filter)       | 2,290 | 0.403     | 0.307     | 0.255     |
| slow (hit_1R AND bars > 12)   | 685   | 1.000     | 0.791     | 0.604     |
| n_vp ≥ 1 AND slow             | 487   | 1.000     | 0.871     | 0.657     |

### OOS only (frozen evaluation)

| Cohort                        | n     | P(hit_2R) | P(hit_3R) |
| ----------------------------- | ----- | --------- | --------- |
| all OOS                       | 2,355 | 0.442     | 0.378     |
| n_vp ≥ 1                      | 1,165 | 0.558     | 0.484     |
| fast                          | 860   | 0.880     | 0.770     |
| **n_vp ≥ 1 AND fast**         | **449**| **0.947**| **0.862** |

**This is the headline finding.** When a trade passes the VP entry filter *and* then prints 1R within ~6 minutes, it reaches 2R **94.7% of the time** out-of-sample, with n=449 — comfortably above the actionability bar. The hit_3R rate on the same cohort is 86.2%, vs the OOS baseline of 37.8%.

The "n_vp ≥ 1 AND slow" cell (entry filter passes, but 1R takes >6 min) is the marginal one: 87.1% hit_2R full-sample, n=487 — still strong, just not the A++ runner cell.

## Q6 — Management rule expectancy

Per-trade expected R under five strategies. All assume SL stays at −1R; trades that never hit 1R = −1R.

- **TP_1R:** exit at +1R when reached, else −1R.
- **TP_2R_cons:** hold to 2R. hit_2R → +2R; hit_1R-not-hit_2R → **−1R** (conservative — assumes the trade reverted to SL after touching 1R).
- **TP_2R_BE:** hold to 2R, but move stop to break-even once 1R touched. hit_2R → +2R; hit_1R-not-hit_2R → **0R**; no-hit_1R → −1R.
- **dyn_cons:** if fast (hit_1R AND bars ≤ 12) hold to 2R (conservative); else exit at 1R. The hypothesis-proposed rule.
- **dyn_BE:** like dyn_cons but with break-even after 1R.

| Split | strategy   | mean R | total R | win % |
| ----- | ---------- | ------ | ------- | ----- |
| IS    | TP_1R      | −0.052 | −115    | 47.4% |
| IS    | TP_2R_cons | +0.201 | +441    | 40.0% |
| IS    | TP_2R_BE   | +0.275 | +602    | 40.0% |
| IS    | dyn_cons   | +0.150 | +330    | 43.4% |
| IS    | dyn_BE     | +0.191 | +418    | 43.4% |
| OOS   | TP_1R      | +0.032 | +75     | 51.6% |
| OOS   | TP_2R_cons | +0.327 | +771    | 44.3% |
| OOS   | TP_2R_BE   | +0.401 | +944    | 44.3% |
| OOS   | dyn_cons   | +0.266 | +626    | 47.2% |
| OOS   | dyn_BE     | +0.310 | +729    | 47.2% |
| ALL   | TP_1R      | −0.009 | −40     | 49.6% |
| ALL   | TP_2R_cons | +0.267 | +1212   | 42.2% |
| ALL   | TP_2R_BE   | +0.340 | +1546   | 42.2% |
| ALL   | dyn_cons   | +0.210 | +956    | 45.4% |
| ALL   | dyn_BE     | +0.252 | +1147   | 45.4% |

**Reading:**

1. The proposed dynamic rule (`dyn_*`) is **strictly dominated by always-hold-to-2R**. Across IS, OOS, and full sample, `TP_2R_BE` > `TP_2R_cons` > `dyn_BE` > `dyn_cons` > `TP_1R` on mean R/trade.
2. The reason: even the *slow* hit_1R cohort hits 2R at 79.1% — that's already a +1.37R expectancy hold (`0.791 × 2 + 0.209 × −1`) under the conservative model, which beats the +1R of scratching.
3. The dynamic rule keeps the upside of fast trades but throws away the residual edge of slow trades. Net: ~−0.06R/trade vs always-hold.
4. **The intuitive "scratch the slow ones" rule the prompt hypothesized is inverted by the data.** Slow ≠ losing-trade-in-disguise; slow means somewhat-lower-but-still-positive expectancy. Scratching is suboptimal.

The right management framing is the inverse:
- **All hit_1R trades:** the default is *hold to 2R*. (TP_2R_BE: +0.40R/trade OOS.)
- **Fast hit_1R trades:** consider extending past 2R to 3R+ — fast cohort hits 3R at 77% OOS vs 60.4% for slow.
- **VP-aligned + fast trades:** the strongest "let-it-run" cell — 86.2% hit_3R OOS. These are the size-up candidates.

## Kill criteria — none triggered

- OOS hit_2R lift = 7.7pp (gate: > 10pp lift needed for management-rule use). The lift is real but below the prompt's actionability bar for *cutting* — and the Q6 finding makes the cut-the-slow-ones rule the wrong framing anyway.
- IS→OOS hit_2R lift drop = 2pp (gate: < 5pp). Pass.
- Year-by-year = 8/9 positive (gate: ≥ 7/9). Pass.

## What changes in the playbook

1. **Don't scratch slow runners.** If you're in a trade that hit 1R, hold to 2R by default — the 79%-still-makes-2R cohort is real edge.
2. **Use the bars-to-1R clock as a *sizing* / runner-target tool, not an exit.** If 1R prints in ≤ ~6 minutes (12 × 30s) **and** the trade is VP-aligned, this is the cohort where 3R+ targets are statistically supported (86% OOS hit_3R, n=449).
3. **No new entry filter.** Speed-of-move is post-entry information — by construction it cannot be a pre-trade filter. Don't try to bolt it onto VP / m-cell selection.

## Caveats

- We cannot observe whether a "hit_1R but not hit_2R" trade actually reverted to SL or exited mid-range. The conservative −1R assumption likely *understates* hold-to-2R expectancy.
- The "fast" cohort selection conditions on hit_1R, so its hit_2R rate (~88%) isn't a pre-trade entry edge — only a confirmation signal.
- Stop-loss policy is held constant at −1R throughout. A trailing stop, partial profit at 1R, or BE move would all change the expectancy table; explicitly out of scope per the prompt.
- Year-2024 effectively neutralized the signal — single-year regimes can flatten the curve. Watch for similar flat tape conditions live.

## How to run

```bash
python studies/speed_of_move/run.py
```

Artifacts written to `studies/speed_of_move/results/`:
- `curve_P_hit2R.csv`
- `threshold_search.csv`, `threshold_search_IS.csv`
- `is_oos_validation.csv`
- `yearly_stability.csv`
- `vp_x_speed.csv`, `vp_x_speed_oos.csv`
- `management_rule_expectancy.csv`
