"""Phase B: Re-mine factor stacks on 8yr IS, validate OOS, compare to old.

For each cell:
1. Fit quantiles on 8yr IS (2018-2024).
2. Build full mask set on 8yr IS.
3. Univariate lift per safe factor (already cell-scoped).
4. Greedy stack: K_PRO pros (uncorrelated +lift) + K_VETO vetos (uncorrelated -lift).
5. Acceptance gates:
   - IS WR @ primary tier >= 58%
   - OOS WR @ primary tier >= 55%  (n>=20 required, else verdict=insufficient)
   - |IS - OOS WR| <= 10pp
   - Year-floor at primary tier: worst year WR >= 45% (n>=10 required per year)
   - Regime spread <= 15pp (bull/bear/neutral)
6. Output: new cell_configs.json (8yr) + comparison table vs old stack.

Output: results/cell_configs_8yr.json
        results/phase_b_comparison.csv
        results/phase_b_per_cell.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.factor_mining import (  # noqa: E402
    ALWAYS_SAFE_PREFIXES,
    build_factor_masks,
    compute_lift,
    factor_safe_for_cell,
    fit_quantiles,
)
from studies.multi_cell_confluence.tier_construction import greedy_select  # noqa: E402
from studies.multi_cell_confluence.utils import cell_filter  # noqa: E402
from studies.multi_cell_8yr_v2.utils import (  # noqa: E402
    ALL_CELLS_OLD,
    ANALYSIS_FRAME_PATH,
    OLD_CELL_CONFIGS_PATH,
    RESULTS_DIR,
    TIER_BINS,
    TIER_LABELS,
)


K_PRO = 7
K_VETO = 3
CORR_THRESHOLD = 0.5
MIN_LIFT_PP = 5.0
MIN_BUCKET_N = 30  # tighter than original (was 20) — 8yr gives us the room

# Per-cell "primary tier minimum confluences": 3 for most, 2 for M1_short (legacy)
PRIMARY_TIER_MIN = {'M1_long': 3, 'M1_short': 2, 'M2_long': 3, 'M2_short': 3,
                    'M3_long': 3, 'M3_short': 3}

# Gates
GATE_IS_WR = 58.0
GATE_OOS_WR = 55.0
GATE_IS_OOS_DELTA = 10.0
GATE_YEAR_FLOOR = 45.0
GATE_YEAR_MIN_N = 10
GATE_REGIME_SPREAD = 15.0


def stack_and_score(cell_df: pd.DataFrame, masks: dict, pros: list[str],
                    vetos: list[str], primary_min: int) -> dict:
    """Apply pros+vetos, return WR/PF/year/regime breakdown for clean view at primary tier."""
    cell_df = cell_df.copy()
    idx = cell_df.index
    conf = pd.Series(0, index=idx, dtype=int)
    for p in pros:
        if p in masks:
            conf += masks[p].reindex(idx).fillna(False).astype(int)
    veto = pd.Series(0, index=idx, dtype=int)
    for v in vetos:
        if v in masks:
            veto += masks[v].reindex(idx).fillna(False).astype(int)
    cell_df['conf_count'] = conf.values
    cell_df['veto_count'] = veto.values

    clean = cell_df[(cell_df['conf_count'] >= primary_min) &
                    (cell_df['veto_count'] == 0)].copy()

    def _metrics(slc):
        n = len(slc)
        if n == 0:
            return {'n': 0, 'wr': float('nan'), 'pf_2r': float('nan')}
        wins = int((slc['outcome'] == 'win').sum())
        hits_2r = int(slc.get('hit_2_0R', pd.Series(False, index=slc.index)).astype(bool).sum())
        wr = round(100 * wins / n, 1)
        losses_in_2r = n - hits_2r
        pf = round((hits_2r * 2.0) / losses_in_2r, 2) if losses_in_2r else float('inf')
        return {'n': n, 'wr': wr, 'pf_2r': pf}

    out = {
        'all': _metrics(clean),
        'is': _metrics(clean[clean['split'] == 'IS']),
        'oos': _metrics(clean[clean['split'] == 'OOS']),
    }

    # Year-by-year
    out['by_year'] = {}
    for yr, grp in clean.groupby('year'):
        out['by_year'][int(yr)] = _metrics(grp)

    # Regime
    out['by_regime'] = {}
    for rg, grp in clean.groupby('regime_60d'):
        if pd.notna(rg):
            out['by_regime'][str(rg)] = _metrics(grp)

    # Year-floor: worst WR among years with n >= GATE_YEAR_MIN_N
    qual_years = {y: m for y, m in out['by_year'].items() if m['n'] >= GATE_YEAR_MIN_N}
    out['year_floor'] = min(m['wr'] for m in qual_years.values()) if qual_years else float('nan')
    out['qualifying_years'] = len(qual_years)

    # Regime spread
    qual_reg = {r: m for r, m in out['by_regime'].items() if m['n'] >= 20}
    if len(qual_reg) >= 2:
        wrs = [m['wr'] for m in qual_reg.values()]
        out['regime_spread'] = round(max(wrs) - min(wrs), 1)
    else:
        out['regime_spread'] = float('nan')

    return out


def remine_cell(cell_name: str, df: pd.DataFrame, masks: dict) -> dict:
    """Mine pros+vetos for one cell on IS, return scored stack."""
    window, direction = cell_name.split('_')
    primary_min = PRIMARY_TIER_MIN[cell_name]

    is_excl = df[(df['split'] == 'IS') & (df['variant'] != 'protected_swing')]
    cell_is = cell_filter(is_excl, window=window, direction=direction,
                          exclude_protected_swing=True)
    cell_all = cell_filter(df, window=window, direction=direction,
                           exclude_protected_swing=True)

    print(f'  IS pool: n={len(cell_is)}')

    # Univariate lift for safe factors
    candidates = []
    for fid, mask in masks.items():
        if not factor_safe_for_cell(fid, window):
            continue
        m = mask.reindex(cell_is.index).fillna(False)
        if m.sum() < MIN_BUCKET_N or (~m).sum() < MIN_BUCKET_N:
            continue
        lift = compute_lift(cell_is, mask)
        candidates.append((fid, lift['lift_pp'], lift))

    pos = sorted([(f, l) for f, l, _ in candidates if pd.notna(l) and l >= MIN_LIFT_PP],
                 key=lambda x: -x[1])
    neg = sorted([(f, l) for f, l, _ in candidates if pd.notna(l) and l <= -MIN_LIFT_PP],
                 key=lambda x: x[1])

    print(f'  Cands: +lift {len(pos)} | -lift {len(neg)}')

    pros = greedy_select(pos, masks, cell_is.index, [], K_PRO, CORR_THRESHOLD)
    vetos = greedy_select(neg, masks, cell_is.index, pros, K_VETO, CORR_THRESHOLD)

    print(f'  Selected: pros={pros} | vetos={vetos}')

    pro_lifts = {p: dict(pos).get(p) for p in pros}
    veto_lifts = {v: dict(neg).get(v) for v in vetos}

    # Score the stack on 8yr (clean view, primary tier)
    score = stack_and_score(cell_all, masks, pros, vetos, primary_min)

    # Gate evaluation
    gates = {
        'is_wr': score['is']['wr'] >= GATE_IS_WR if pd.notna(score['is']['wr']) else False,
        'oos_wr': score['oos']['wr'] >= GATE_OOS_WR if (
            pd.notna(score['oos']['wr']) and score['oos']['n'] >= 20
        ) else False,
        'is_oos_delta': (abs(score['is']['wr'] - score['oos']['wr']) <= GATE_IS_OOS_DELTA) if (
            pd.notna(score['is']['wr']) and pd.notna(score['oos']['wr']) and score['oos']['n'] >= 20
        ) else False,
        'year_floor': score['year_floor'] >= GATE_YEAR_FLOOR if pd.notna(score['year_floor']) else False,
        'regime_spread': score['regime_spread'] <= GATE_REGIME_SPREAD if pd.notna(score['regime_spread']) else True,
    }
    score['gates'] = gates
    score['gates_passed'] = sum(gates.values())
    score['gates_total'] = len(gates)
    if score['oos']['n'] < 20:
        score['note'] = f'OOS sample thin (n={score["oos"]["n"]})'

    return {
        'cell': cell_name,
        'pros': pros,
        'vetos': vetos,
        'pro_lifts': pro_lifts,
        'veto_lifts': veto_lifts,
        'primary_tier_min': primary_min,
        'score_new': score,
        'tier_bins': TIER_BINS,
        'tier_labels': TIER_LABELS,
        'n_is': int(len(cell_is)),
    }


def main():
    print('=' * 70)
    print('PHASE B: Re-mine factor stacks on 8yr')
    print('=' * 70)

    df = pd.read_csv(ANALYSIS_FRAME_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = pd.to_datetime(df['date'])
    print(f'Loaded {len(df)} trades')

    # Re-fit quantiles on 8yr IS (2018-2024)
    is_excl = df[(df['split'] == 'IS') & (df['variant'] != 'protected_swing')]
    print(f'Fitting NEW quantiles on 8yr IS (n={len(is_excl)})...')
    quantiles_8yr = fit_quantiles(is_excl)
    masks_8yr = build_factor_masks(df, quantiles_8yr)
    print(f'Built {len(masks_8yr)} factor masks (8yr quantiles)')

    # Also build OLD-quantile masks for scoring the OLD stacks (apples-to-apples
    # vs Phase A — old stack scored with old quantiles)
    notion_train = df[(df['date'] >= '2023-10-01') &
                      (df['date'] <= '2025-09-30') &
                      (df['variant'] != 'protected_swing')]
    quantiles_old = fit_quantiles(notion_train)
    masks_old = build_factor_masks(df, quantiles_old)

    with open(OLD_CELL_CONFIGS_PATH) as f:
        old_configs = json.load(f)

    print('\n--- Re-mining cells ---')
    results = []
    for cell_name in ALL_CELLS_OLD:
        print(f'\n{cell_name}:')
        r = remine_cell(cell_name, df, masks_8yr)
        # Also score OLD stack on 8yr (using OLD quantile masks) for apples-to-apples
        old = old_configs[cell_name]
        cell_all = cell_filter(df, window=cell_name.split('_')[0],
                               direction=cell_name.split('_')[1],
                               exclude_protected_swing=True)
        r['score_old_stack'] = stack_and_score(cell_all, masks_old,
                                                old['pros'], old['vetos'],
                                                PRIMARY_TIER_MIN[cell_name])
        r['old_pros'] = old['pros']
        r['old_vetos'] = old['vetos']
        results.append(r)

    # Save full results
    out_json = RESULTS_DIR / 'phase_b_per_cell.json'
    with open(out_json, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'\nWrote {out_json}')

    # New cell_configs.json (8yr stacks)
    new_configs = {}
    for r in results:
        new_configs[r['cell']] = {
            'pros': r['pros'],
            'pro_lifts': r['pro_lifts'],
            'vetos': r['vetos'],
            'veto_lifts': r['veto_lifts'],
            'tier_bins': TIER_BINS,
            'tier_labels': TIER_LABELS,
            'n_is': r['n_is'],
            'primary_tier_min': r['primary_tier_min'],
            'gates_passed': r['score_new']['gates_passed'],
            'gates': r['score_new']['gates'],
        }
    out_cfg = RESULTS_DIR / 'cell_configs_8yr.json'
    with open(out_cfg, 'w') as f:
        json.dump(new_configs, f, indent=2, default=str)
    print(f'Wrote {out_cfg}')

    # Comparison CSV: old vs new, clean view, primary tier
    rows = []
    for r in results:
        s_old = r['score_old_stack']
        s_new = r['score_new']
        rows.append({
            'cell': r['cell'],
            'tier_min': r['primary_tier_min'],
            'old_pros': '|'.join(r['old_pros']),
            'new_pros': '|'.join(r['pros']),
            'old_vetos': '|'.join(r['old_vetos']),
            'new_vetos': '|'.join(r['vetos']),
            'old_n_all': s_old['all']['n'],
            'old_wr_all': s_old['all']['wr'],
            'old_pf_all': s_old['all']['pf_2r'],
            'new_n_all': s_new['all']['n'],
            'new_wr_all': s_new['all']['wr'],
            'new_pf_all': s_new['all']['pf_2r'],
            'old_year_floor': s_old['year_floor'],
            'new_year_floor': s_new['year_floor'],
            'new_is_wr': s_new['is']['wr'],
            'new_oos_wr': s_new['oos']['wr'],
            'new_oos_n': s_new['oos']['n'],
            'new_gates_passed': f"{s_new['gates_passed']}/{s_new['gates_total']}",
        })
    cmp_df = pd.DataFrame(rows)
    out_cmp = RESULTS_DIR / 'phase_b_comparison.csv'
    cmp_df.to_csv(out_cmp, index=False)
    print(f'Wrote {out_cmp}')

    # Console summary
    print('\n' + '=' * 70)
    print('NEW vs OLD STACKS — 8yr clean view, primary tier')
    print('=' * 70)
    for r in results:
        s_old = r['score_old_stack']['all']
        s_new = r['score_new']['all']
        floor_old = r['score_old_stack']['year_floor']
        floor_new = r['score_new']['year_floor']
        gates = r['score_new']['gates_passed']
        print(f'\n{r["cell"]}  (min conf {r["primary_tier_min"]}+)')
        print(f'  OLD: n={s_old["n"]:3d}  WR={s_old["wr"]}%  PF={s_old["pf_2r"]}  YearFloor={floor_old}%')
        print(f'  NEW: n={s_new["n"]:3d}  WR={s_new["wr"]}%  PF={s_new["pf_2r"]}  YearFloor={floor_new}%  gates {gates}/5')
        print(f'  NEW pros : {r["pros"]}')
        print(f'  NEW vetos: {r["vetos"]}')

    print('\nPhase B done.')


if __name__ == '__main__':
    main()
