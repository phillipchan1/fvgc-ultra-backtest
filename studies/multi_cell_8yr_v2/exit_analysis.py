"""Exit-strategy EV comparison on the 8yr new stacks.

For each (cell, primary_tier) pair: simulate 9 exit policies against the
hit_1R..hit_5R ladder. Reports EV/trade and PF.

Output: results/exit_analysis_per_cell.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np
import pandas as pd

from studies.multi_cell_confluence.factor_mining import (  # noqa: E402
    build_factor_masks, fit_quantiles,
)
from studies.multi_cell_confluence.utils import cell_filter  # noqa: E402
from studies.multi_cell_8yr_v2.utils import (  # noqa: E402
    ANALYSIS_FRAME_PATH, RESULTS_DIR,
)


CELLS_AND_TIERS = [
    ('M3_long', [3, 4, 5]),
    ('M1_long', [3, 4]),
]


def apply_stack(df: pd.DataFrame, masks: dict, cfg: dict, cell: str) -> pd.DataFrame:
    win, dirn = cell.split('_')
    c = cell_filter(df, window=win, direction=dirn,
                    exclude_protected_swing=True).copy()
    idx = c.index
    conf = pd.Series(0, index=idx, dtype=int)
    for p in cfg[cell]['pros']:
        if p in masks:
            conf += masks[p].reindex(idx).fillna(False).astype(int)
    veto = pd.Series(0, index=idx, dtype=int)
    for v in cfg[cell]['vetos']:
        if v in masks:
            veto += masks[v].reindex(idx).fillna(False).astype(int)
    c['conf_count'] = conf.values
    c['veto_count'] = veto.values
    return c


def exit_evs(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {}
    h1 = sub['hit_1_0R'].astype(bool).to_numpy()
    h2 = sub['hit_2_0R'].astype(bool).to_numpy()
    h3 = sub['hit_3_0R'].astype(bool).to_numpy()
    h5 = sub['hit_5_0R'].astype(bool).to_numpy()

    def pf_ev(r):
        r = np.asarray(r, dtype=float)
        gains = r[r > 0].sum()
        losses = -r[r < 0].sum()
        pf = gains / losses if losses > 0 else float('inf')
        return round(float(r.mean()), 3), round(float(pf), 2)

    res = {}
    res['TP@1R fixed'] = pf_ev(np.where(h1, 1.0, -1.0))
    res['TP@2R fixed'] = pf_ev(np.where(h2, 2.0, -1.0))
    res['TP@3R fixed'] = pf_ev(np.where(h3, 3.0, -1.0))
    res['TP@5R fixed'] = pf_ev(np.where(h5, 5.0, -1.0))
    res['BE@1R -> TP@2R'] = pf_ev(np.where(h2, 2.0, np.where(h1, 0.0, -1.0)))
    res['BE@1R -> TP@3R'] = pf_ev(np.where(h3, 3.0, np.where(h1, 0.0, -1.0)))
    a = np.where(h1, 1/3, -1/3)
    b = np.where(h2, 2/3, np.where(h1, 0.0, -1/3))
    c = np.where(h5, 5/3, np.where(h1, 0.0, -1/3))
    res['1/3+1/3+1/3 runner BE'] = pf_ev(a + b + c)
    a2 = np.where(h1, 0.5, -0.5)
    b2 = np.where(h3, 1.5, np.where(h1, 0.0, -0.5))
    res['1/2 @1R + 1/2 -> 3R BE'] = pf_ev(a2 + b2)
    a3 = np.where(h1, 0.5, -0.5)
    b3 = np.where(h5, 2.5, np.where(h1, 0.0, -0.5))
    res['1/2 @1R + 1/2 -> 5R BE'] = pf_ev(a3 + b3)
    return res


def main():
    df = pd.read_csv(ANALYSIS_FRAME_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = pd.to_datetime(df['date'])

    is_excl = df[(df['split'] == 'IS') & (df['variant'] != 'protected_swing')]
    qs = fit_quantiles(is_excl)
    masks = build_factor_masks(df, qs)

    with open(RESULTS_DIR / 'cell_configs_8yr.json') as f:
        cfg = json.load(f)

    rows = []
    for cell, tiers in CELLS_AND_TIERS:
        c = apply_stack(df, masks, cfg, cell)
        for tier in tiers:
            sub = c[(c['veto_count'] == 0) & (c['conf_count'] >= tier)]
            print(f'\n{cell} conf>={tier}+, n={len(sub)}')
            res = exit_evs(sub)
            for name, (ev, pf) in sorted(res.items(), key=lambda kv: -kv[1][0]):
                rows.append({
                    'cell': cell, 'tier_min': tier, 'n': len(sub),
                    'strategy': name, 'ev_r': ev, 'pf': pf,
                })
                print(f'  {name:32s}  EV={ev:+.3f}R  PF={pf}')
            print(f'  hit ladder: 1R={sub["hit_1_0R"].mean()*100:.1f}%  '
                  f'2R={sub["hit_2_0R"].mean()*100:.1f}%  '
                  f'3R={sub["hit_3_0R"].mean()*100:.1f}%  '
                  f'5R={sub["hit_5_0R"].mean()*100:.1f}%')

    out = RESULTS_DIR / 'exit_analysis_per_cell.csv'
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f'\nWrote {out}')


if __name__ == '__main__':
    main()
