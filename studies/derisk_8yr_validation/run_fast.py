#!/usr/bin/env python3
"""Derisk + exit-policy validation on FULL 8yr — derived from existing baseline.

Reuses studies/baseline/results/trades.csv (already full 8yr 30s, with entry_idx,
direction, entry_price, sl_dist precomputed) so we DON'T regenerate signals.

PART B (reach: when to go for more R) is pure baseline columns — no walk.
PART A (exact derisk PF per era) needs intra-path ordering, which baseline
discards, so we do a lightweight high/low walk keyed on the stored entry_idx.

Validation gate: reconstructed WINDOW (2023-10 -> 2026-03) PF for lock0.5_tp3R
must match the worktree's exact sim (1.367 / WR 68.6% / n=1575). If it does,
the PRE-2018-2023 split is trustworthy.
"""
import sys, datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from fvgc.data import load_candles

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / 'studies/baseline/results/trades.csv'
CANDLES  = ROOT / 'data/consolidated/nq-front-month.ohlcv-30s.csv'
RESULTS  = Path(__file__).resolve().parent / 'results'

WIN_START = pd.Timestamp('2023-10-01', tz='America/New_York')
WIN_END   = pd.Timestamp('2026-03-26', tz='America/New_York')


class Policy:
    __slots__ = ('name', 'tp_r', 'arm', 'lock')
    def __init__(self, name, tp_r=1.0, arm=None, lock=None):
        self.name, self.tp_r, self.arm, self.lock = name, tp_r, arm, lock

POLICIES = [
    Policy('baseline_1R',  tp_r=1.0),
    Policy('fixed_tp_3R',  tp_r=3.0),
    Policy('lock0.5_tp1R', tp_r=1.0,  arm=0.5, lock=0.5),
    Policy('lock0.5_tp2R', tp_r=2.0,  arm=0.5, lock=0.5),
    Policy('lock0.5_tp3R', tp_r=3.0,  arm=0.5, lock=0.5),
    Policy('lock0.5_no_tp',tp_r=None, arm=0.5, lock=0.5),
]


def eval_policy(p, fav_R, adv_R, prior_mfe, last_close_R):
    if p.arm is None:
        sl = np.full_like(fav_R, -1.0)
    else:
        sl = np.where(prior_mfe >= p.arm, p.lock, -1.0)
    sl_hit = adv_R >= -sl
    tp_hit = (np.zeros_like(fav_R, bool) if p.tp_r is None else fav_R >= p.tp_r)
    m = sl_hit | tp_hit
    if m.any():
        j = int(m.argmax())
        return float(sl[j]) if sl_hit[j] else p.tp_r
    return last_close_R


def pf_wr(arr):
    arr = np.asarray(arr, float)
    if not len(arr): return dict(n=0, wr=np.nan, pf=np.nan, avg=np.nan, tot=0.0)
    gp = arr[arr > 0].sum(); gl = -arr[arr < 0].sum()
    w = int((arr > 0).sum()); l = int((arr < 0).sum())
    return dict(n=len(arr), wr=100*w/(w+l) if w+l else np.nan,
                pf=gp/gl if gl > 0 else np.inf, avg=float(arr.mean()), tot=float(arr.sum()))


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(BASELINE)
    df = df[df['outcome'].isin(['win', 'loss'])].copy()   # tradeable only
    df['ts'] = pd.to_datetime(df['timestamp']).dt.tz_localize('America/New_York')
    df['entry_idx'] = df['entry_idx'].astype(int)
    print(f"Baseline tradeable trades: {len(df)}  ({df.ts.min().date()} -> {df.ts.max().date()})")

    cand = load_candles(CANDLES)
    highs = cand['high'].to_numpy(float); lows = cand['low'].to_numpy(float)
    closes = cand['close'].to_numpy(float)
    days = cand['timestamp_ny'].dt.normalize().astype('int64').to_numpy()
    n_bars = len(cand)

    # OR width (45m RTH 09:30-10:15) per session
    t = cand['timestamp_ny'].dt.time
    rth = cand[(t >= dt.time(9, 30)) & (t <= dt.time(10, 15))]
    g = rth.groupby(rth['timestamp_ny'].dt.normalize())
    or_w = (g['high'].max() - g['low'].min())
    or_by = {d.date(): float(w) for d, w in or_w.items()}

    # sanity: entry_idx alignment
    sample = df.iloc[len(df)//2]
    ei = sample['entry_idx']
    assert lows[ei] - 2 <= sample['entry_price'] <= highs[ei] + 2, \
        f"entry_idx misaligned: idx={ei} entry={sample['entry_price']} bar=[{lows[ei]},{highs[ei]}]"
    print("entry_idx alignment OK")

    pol = {p.name: np.full(len(df), np.nan) for p in POLICIES}
    eod_float = np.zeros(len(df))   # last_close_R for diagnostics

    for r, (_, row) in enumerate(df.iterrows()):
        ei = int(row['entry_idx']); is_long = row['direction'] == 'long'
        entry = row['entry_price']; sld = row['sl_dist']
        if sld <= 0: continue
        d0 = days[ei]; e = ei + 1
        while e < n_bars and days[e] == d0: e += 1
        if e <= ei + 1: continue
        hi = highs[ei+1:e]; lo = lows[ei+1:e]; lc = closes[e-1]
        if is_long:
            fav = (hi-entry)/sld; adv = (entry-lo)/sld
        else:
            fav = (entry-lo)/sld; adv = (hi-entry)/sld
        cum = np.maximum.accumulate(np.maximum(fav, 0.0))
        prior = np.empty_like(cum); prior[0]=0.0; prior[1:]=cum[:-1]
        lcR = ((lc-entry) if is_long else (entry-lc))/sld
        eod_float[r] = lcR
        for p in POLICIES:
            pol[p.name][r] = eval_policy(p, fav, adv, prior, lcR)

    for p in POLICIES:
        df[p.name] = pol[p.name]
    df['or_width'] = df['ts'].dt.date.map(or_by)
    df['fvg_size'] = (df['fvg_top'] - df['fvg_bottom']).abs()
    df.to_csv(RESULTS / 'derived_trades_30s.csv', index=False)

    # ---- VALIDATION GATE ----
    win = df[(df['ts'] >= WIN_START) & (df['ts'] < WIN_END)]
    v = pf_wr(win['lock0.5_tp3R'].to_numpy())
    print("\n" + "="*72)
    print("VALIDATION GATE (window 2023-10..2026-03, lock0.5_tp3R)")
    print(f"  reconstructed: n={v['n']}  WR={v['wr']:.1f}%  PF={v['pf']:.3f}  avgR={v['avg']:+.3f}")
    print(f"  worktree sim : n=1575     WR=68.6%   PF=1.367  avgR=+0.115")
    print("="*72)

    # ---- PART A: policy PF per era ----
    eras = {
        'ALL_8yr':       df,
        'PRE_2018-2023': df[df['ts'] < WIN_START],
        'WINDOW(Notion)':df[(df['ts'] >= WIN_START) & (df['ts'] < WIN_END)],
        'POST_2026+':    df[df['ts'] >= WIN_END],
    }
    print("\nPART A — exit-policy PF by era (30s):")
    print(f"  {'era':16s} {'policy':14s} {'n':>5s} {'WR':>6s} {'PF':>6s} {'avgR':>7s} {'totR':>8s}")
    print('  '+'-'*68)
    rows=[]
    for en, sub in eras.items():
        for pn in ['baseline_1R','lock0.5_tp1R','lock0.5_tp3R','lock0.5_no_tp','fixed_tp_3R']:
            s = pf_wr(sub[pn].to_numpy())
            rows.append(dict(era=en, policy=pn, **s))
            pf = f"{s['pf']:.3f}" if np.isfinite(s['pf']) else 'inf'
            wr = f"{s['wr']:.1f}" if s['wr']==s['wr'] else 'nan'
            print(f"  {en:16s} {pn:14s} {s['n']:>5d} {wr:>6s} {pf:>6s} {s['avg']:>+7.3f} {s['tot']:>+8.1f}")
        print()
    pd.DataFrame(rows).to_csv(RESULTS / 'policy_by_era.csv', index=False)

    # ---- PART B: reach (pure baseline mfe) ----
    print("="*72)
    print("PART B — REACH: when do trades run multiple R? (full 8yr, 30s)")
    print("="*72)
    for col in ['hit_2_0R','hit_3_0R','hit_5_0R']:
        df[col] = df[col].fillna(0).astype(bool)
    df['r2'] = df['mfe_r'] >= 2; df['r3'] = df['mfe_r'] >= 3; df['r5'] = df['mfe_r'] >= 5

    def reach_block(title, buckets):
        print(f"\n--- {title} ---")
        print(f"  {'bucket':16s} {'n':>5s} {'bWR':>5s} {'bPF':>5s} | {'P2R':>5s} {'P3R':>5s} {'P5R':>5s} |"
              f" {'tp1R':>6s} {'tp3R':>6s} {'Δ':>6s} {'tp3PF':>6s}")
        print('  '+'-'*86)
        for label, mask in buckets:
            sub = df[mask]
            if len(sub) < 25:
                print(f"  {label:16s} {len(sub):>5d}  (n<25)"); continue
            b = pf_wr(sub['baseline_1R'].to_numpy())
            t1 = pf_wr(sub['lock0.5_tp1R'].to_numpy()); t3 = pf_wr(sub['lock0.5_tp3R'].to_numpy())
            def f(x): return f"{x:.2f}" if np.isfinite(x) and x==x else 'nan'
            print(f"  {label:16s} {len(sub):>5d} {b['wr']:>5.1f} {f(b['pf']):>5s} | "
                  f"{100*sub['r2'].mean():>5.1f} {100*sub['r3'].mean():>5.1f} {100*sub['r5'].mean():>5.1f} | "
                  f"{t1['avg']:>+6.3f} {t3['avg']:>+6.3f} {t3['avg']-t1['avg']:>+6.3f} {f(t3['pf']):>6s}")

    ov = df
    print(f"\nOverall (n={len(ov)}): P2R={100*ov['r2'].mean():.1f}%  P3R={100*ov['r3'].mean():.1f}%  P5R={100*ov['r5'].mean():.1f}%")

    # reach by era (does multi-R generalize pre-2023?)
    reach_block('REACH BY ERA', [
        ('PRE_2018-2023', df['ts'] < WIN_START),
        ('WINDOW(Notion)',(df['ts']>=WIN_START)&(df['ts']<WIN_END)),
        ('POST_2026+',    df['ts']>=WIN_END),
    ])
    b = df['bars_to_1_0R']
    reach_block('SPEED to 1R', [
        ('never hit 1R', df['hit_1_0R'].fillna(0).astype(bool)==False),
        ('fast <=4',  (b>=1)&(b<=4)),
        ('med 5-12',  (b>=5)&(b<=12)),
        ('slow >12',  b>12),
    ])
    ow = df['or_width']; q = ow.quantile([.2,.4,.6,.8]).to_dict()
    reach_block('OPENING RANGE width', [
        ('Q1 narrow', ow<=q[.2]), ('Q2',(ow>q[.2])&(ow<=q[.4])),
        ('Q3',(ow>q[.4])&(ow<=q[.6])), ('Q4',(ow>q[.6])&(ow<=q[.8])),
        ('Q5 wide', ow>q[.8]),
    ])
    fs = df['fvg_size']
    reach_block('FVG size', [
        ('<=5pt', fs<=5), ('5-10', (fs>5)&(fs<=10)),
        ('10-20',(fs>10)&(fs<=20)), ('>20', fs>20),
    ])
    sd = df['sl_dist']
    reach_block('SL distance', [
        ('<=20', sd<=20), ('20-35',(sd>20)&(sd<=35)),
        ('35-50',(sd>35)&(sd<=50)), ('>50', sd>50),
    ])
    reach_block('DIRECTION', [('long', df['direction']=='long'), ('short', df['direction']=='short')])
    reach_block('VARIANT', [(v, df['variant']==v) for v in ['bos','protected_swing','ifvg','no_fvg']])
    hm = df['ts'].dt.hour*60 + df['ts'].dt.minute
    reach_block('ENTRY TIME ET', [
        ('pre 09:30', hm<570), ('09:30-45',(hm>=570)&(hm<585)),
        ('09:45-10:00',(hm>=585)&(hm<600)), ('10:00-15',(hm>=600)&(hm<=615)),
    ])
    fast=(b>=1)&(b<=12); wide=ow>q[.6]; narrow=ow<=q[.4]
    reach_block('COMBO', [
        ('fast+wideOR', fast&wide), ('fast+narrowOR', fast&narrow), ('slow+wideOR',(b>12)&wide),
    ])
    print("\nWrote results/derived_trades_30s.csv, policy_by_era.csv")


if __name__ == '__main__':
    main()
