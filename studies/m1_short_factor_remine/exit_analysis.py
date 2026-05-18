"""Exit-strategy analysis on the 8-year M1 short cohort with the new
4-factor stack. Can the right exit strategy push PF higher despite
modest WR?"""
import pandas as pd

df = pd.read_csv('/Users/philchan/Work/fvgc-backtest/studies/m1_short_factor_remine/results/trades_tagged.csv')

# Cohorts
print("Cohort sizes:")
print(f"  All M1 short (vetoes applied): {len(df)}")
for col, label in [('conf_count', 'conf')]:
    if col in df.columns:
        pass
print(df['conf_count'].value_counts().sort_index() if 'conf_count' in df.columns else 'no conf_count col')
print()

# Verify column names
print("Columns:", [c for c in df.columns if 'hit' in c or 'conf' in c or 'split' in c])
print()

def ev_analysis(sub, label):
    if len(sub) == 0:
        return
    n = len(sub)
    wins = (sub['outcome']=='win').sum()
    h1 = sub['hit_1_0R'].mean()
    h2 = sub['hit_2_0R'].mean() if 'hit_2_0R' in sub.columns else None
    h3 = sub['hit_3_0R'].mean() if 'hit_3_0R' in sub.columns else None
    h5 = sub['hit_5_0R'].mean() if 'hit_5_0R' in sub.columns else None

    print(f"\n{'='*72}")
    print(f"  {label} — n={n}, WR={wins/n*100:.1f}%")
    print(f"  Hit rates: 1R={h1*100:.0f}%  2R={h2*100:.0f}%  3R={h3*100:.0f}%  5R={h5*100:.0f}%")
    print(f"{'='*72}")
    print()

    # Strategy 1: Fixed TP, no BE (full risk on every trade)
    print(f"  {'Strategy':<48} {'EV/trade':<12} {'PF@1R':<8}")
    print(f"  {'-'*48} {'-'*12} {'-'*8}")
    for tp_r, hit_tp in [(1.0, h1), (2.0, h2), (3.0, h3), (5.0, h5)]:
        if hit_tp is None: continue
        ev = hit_tp * tp_r - (1 - hit_tp) * 1.0
        pf = (hit_tp * tp_r) / max(1 - hit_tp, 1e-9)
        print(f"  {'Fixed TP @ '+str(tp_r)+'R, no BE':<48} {ev:+.2f}R{'':<6} {pf:.2f}")

    # Strategy 2: BE@1R then ride to X (optimistic — assume no BE-out before TP)
    print()
    for tp_r, hit_tp in [(2.0, h2), (3.0, h3), (5.0, h5)]:
        if hit_tp is None: continue
        win_r = hit_tp * tp_r
        scratch = (h1 - hit_tp) * 0.0
        loss = (1 - h1) * (-1.0)
        ev = win_r + scratch + loss
        pf = win_r / max((1-h1), 1e-9)
        print(f"  {'BE@1R → TP@'+str(tp_r)+'R (optimistic)':<48} {ev:+.2f}R{'':<6} {pf:.2f}")

    # Strategy 3: Scale strategies
    print()
    # 50% @ 2R + 50% rides to 5R, no BE on runner
    if h2 is not None and h5 is not None:
        half1 = 0.5 * (h2 * 2.0 + (1 - h2) * (-1.0))
        half2 = 0.5 * (h5 * 5.0 + (1 - h5) * (-1.0))
        ev = half1 + half2
        # PF for this is tricky; approximate
        gross_wins = 0.5 * (h2 * 2.0) + 0.5 * (h5 * 5.0)
        gross_losses = 0.5 * (1-h2) + 0.5 * (1-h5)
        pf = gross_wins / max(gross_losses, 1e-9)
        print(f"  {'Scale 50% @ 2R + 50% rides to 5R (no BE)':<48} {ev:+.2f}R{'':<6} {pf:.2f}")
    # 1/3 at 1R + 1/3 at 3R + 1/3 to 5R, BE@1R after first scale
    if h1 is not None and h3 is not None and h5 is not None:
        third = 1/3
        # Third 1 (1R): wins 1R if hit_1R else loses 1R
        ev_1 = third * (h1 * 1.0 + (1 - h1) * (-1.0))
        # Third 2 (3R): wins 3R if hit_3R, scratch if hit_1R but not 3R (BE), loses 1R else
        ev_2 = third * (h3 * 3.0 + (h1 - h3) * 0.0 + (1 - h1) * (-1.0))
        # Third 3 (5R): wins 5R if hit_5R, scratch if hit_1R but not 5R, loses 1R else
        ev_3 = third * (h5 * 5.0 + (h1 - h5) * 0.0 + (1 - h1) * (-1.0))
        ev = ev_1 + ev_2 + ev_3
        gross_wins = third * (h1 * 1.0 + h3 * 3.0 + h5 * 5.0)
        # Losses: 3 thirds × (1-h1) × 1R = (1-h1) total
        gross_losses = (1 - h1)
        pf = gross_wins / max(gross_losses, 1e-9)
        print(f"  {'1/3@1R + 1/3@3R + 1/3@5R, BE@1R after first':<48} {ev:+.2f}R{'':<6} {pf:.2f}")
    # 25% at 1R + 25% at 2R + 25% at 3R + 25% to 5R (smoother)
    if h1 is not None and h2 is not None and h3 is not None and h5 is not None:
        q = 0.25
        ev_1 = q * (h1 * 1.0 + (1 - h1) * (-1.0))
        ev_2 = q * (h2 * 2.0 + (h1 - h2) * 0.0 + (1 - h1) * (-1.0))
        ev_3 = q * (h3 * 3.0 + (h1 - h3) * 0.0 + (1 - h1) * (-1.0))
        ev_5 = q * (h5 * 5.0 + (h1 - h5) * 0.0 + (1 - h1) * (-1.0))
        ev = ev_1 + ev_2 + ev_3 + ev_5
        gross_wins = q * (h1 + 2*h2 + 3*h3 + 5*h5)
        gross_losses = (1-h1)
        pf = gross_wins / max(gross_losses, 1e-9)
        print(f"  {'25% @ each of 1R/2R/3R/5R, BE@1R after first':<48} {ev:+.2f}R{'':<6} {pf:.2f}")


# Run on each cohort
# All trades after vetoes
print("\n" + "="*72)
print("  COHORT 1: All M1 shorts after vetoes (baseline)")
print("="*72)
ev_analysis(df, "ALL TRADES (post-veto)")

# 2+ confluence trades
if 'conf_count' in df.columns:
    sub = df[df['conf_count'] >= 2]
    ev_analysis(sub, "2+ CONFLUENCE TIER (combined IS+OOS)")
    sub_is = df[(df['conf_count'] >= 2) & (df.get('split', 'IS') == 'IS')]
    if len(sub_is) > 0:
        ev_analysis(sub_is, "2+ CONFLUENCE TIER (IS only)")
    sub_oos = df[(df['conf_count'] >= 2) & (df.get('split', 'IS') == 'OOS')]
    if len(sub_oos) > 0:
        ev_analysis(sub_oos, "2+ CONFLUENCE TIER (OOS only)")

print("\n\nNOTE: Optimistic BE@1R model assumes BE never gets hit before TP.")
print("Real-world BE@1R will be LOWER than these numbers because of retraces.")
print("Use the 'No BE' and 'Scale ... no BE on runner' rows as realistic estimates.")
