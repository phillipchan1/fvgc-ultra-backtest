#!/usr/bin/env python3
"""Trade Explorer — look up our model's view of a specific (date, time, direction).

For each demonstrated Tempo trade, answer: did our model emit a signal nearby?
If yes — which factors were lit, what was the confluence score?
If no — why not (out of cohort, wrong direction, no qualifying sweep, etc.)?

Usage:
  python studies/tempo_recaps/trade_explorer.py --date 2026-05-14 --time "08:30"
  python studies/tempo_recaps/trade_explorer.py --demonstrations  # match all from CSV
"""

import argparse
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

POP_PATH = Path('studies/ifvg_reversal_population/results/population_scored.csv')
DEMOS_PATH = Path('studies/tempo_recaps/demonstrations.csv')

# Look-up window: trades within this many minutes count as a match.
MATCH_WINDOW_MIN = 5


def find_matches(pop: pd.DataFrame, date: str, time_str: str,
                 direction: str = None, window_min: int = MATCH_WINDOW_MIN):
    """Find population rows near a given (date, time)."""
    pop = pop.copy()
    pop['entry_ts_parsed'] = pd.to_datetime(pop['entry_ts'], utc=True, format='mixed')
    pop['date'] = pop['entry_ts_parsed'].dt.date.astype(str)

    if date not in pop['date'].values:
        return pop.iloc[0:0]  # empty frame

    day = pop[pop['date'] == date].copy()

    # Parse target time
    if time_str.startswith('~') or time_str in {'morning', 'mid-AM', 'later', 'AM', 'PM', 'early', 'late', ''}:
        # Vague — match full day or by direction
        target_secs = None
    else:
        try:
            t = datetime.strptime(time_str, '%H:%M').time()
            target_secs = t.hour * 3600 + t.minute * 60
        except ValueError:
            target_secs = None

    if direction:
        day = day[day['direction'] == direction]

    if target_secs is None:
        return day  # all matches on the date

    day['secs_of_day'] = (day['entry_ts_parsed'].dt.hour * 3600 +
                          day['entry_ts_parsed'].dt.minute * 60 +
                          day['entry_ts_parsed'].dt.second)
    day['delta_min'] = (day['secs_of_day'] - target_secs).abs() / 60.0
    return day[day['delta_min'] <= window_min].sort_values('delta_min')


def print_match_summary(row: pd.Series):
    """Compact print of a population row's relevant fields."""
    factor_cols = [
        'sweep_level', 'sweep_tier', 'sweep_penetration_pts',
        'gap_size_pts', 'gap_tf', 'inversion_body_fraction',
        'pd_position', 'pd_correct_side',
        'prior_same_dir_sweep_count', 'is_chop_day',
        'r_multiple', 'exit_reason',
    ]
    score_cols = [c for c in row.index if c.startswith('score_')]
    print(f"  entry_ts={row.get('entry_ts','?')}  direction={row.get('direction','?')}  "
          f"price={row.get('entry_price','?')}")
    print("  factors:")
    for c in factor_cols:
        if c in row.index:
            val = row[c]
            print(f"    {c:32} = {val}")
    print("  scores:")
    for c in score_cols:
        print(f"    {c:32} = {row[c]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', type=str, help='YYYY-MM-DD')
    ap.add_argument('--time', type=str, default='', help='HH:MM (NY)')
    ap.add_argument('--direction', type=str, choices=['long', 'short'])
    ap.add_argument('--window', type=int, default=MATCH_WINDOW_MIN, help='Match window in minutes')
    ap.add_argument('--demonstrations', action='store_true',
                    help='Match all rows in demonstrations.csv against the population')
    args = ap.parse_args()

    pop = pd.read_csv(POP_PATH)
    print(f"Population: {len(pop):,} rows, "
          f"{pop['entry_ts'].min()[:10]} -> {pop['entry_ts'].max()[:10]}\n")

    if args.demonstrations:
        run_demonstrations(pop, args.window)
        return

    if not args.date:
        print("--date required (or use --demonstrations).")
        return

    matches = find_matches(pop, args.date, args.time, args.direction, args.window)
    print(f"Matches for {args.date} {args.time} {args.direction or 'either'} "
          f"(±{args.window} min): {len(matches)}")
    for _, r in matches.iterrows():
        print()
        print_match_summary(r)


def run_demonstrations(pop: pd.DataFrame, window: int):
    """Match every demonstration row against the population."""
    demos = pd.read_csv(DEMOS_PATH)
    # Restrict to in-cohort dates
    pop_dates = set(pd.to_datetime(pop['entry_ts'], utc=True, format='mixed').dt.date.astype(str))
    demos['in_cohort'] = demos['recap_date'].isin(pop_dates)

    in_cohort = demos[demos['in_cohort']]
    out_cohort = demos[~demos['in_cohort']]

    print(f"Demonstrations: {len(demos)} total, "
          f"{len(in_cohort)} in-cohort, {len(out_cohort)} post-cohort\n")

    results = []
    for _, demo in in_cohort.iterrows():
        # Skip non-NQ trades for now (population is NQ-only)
        if demo['instrument'] not in ('NQ',):
            results.append({
                **demo.to_dict(),
                'match_status': 'skipped_non_nq',
                'n_matches': 0,
                'best_match_id': None,
                'best_score_v2': None,
            })
            continue

        matches = find_matches(pop, demo['recap_date'], str(demo['entry_time_ny']),
                                demo['direction'] if demo['direction'] in ('long', 'short') else None,
                                window)
        if matches.empty:
            results.append({
                **demo.to_dict(),
                'match_status': 'no_match',
                'n_matches': 0,
                'best_match_id': None,
                'best_score_v2': None,
            })
        else:
            best = matches.iloc[0]
            results.append({
                **demo.to_dict(),
                'match_status': 'matched',
                'n_matches': len(matches),
                'best_match_id': best.name,
                'best_match_entry_ts': best['entry_ts'],
                'best_confluence_score': best.get('confluence_score'),
                'best_has_ob_confirm': best.get('has_ob_confirm'),
                'best_distance_to_ath_pts': best.get('distance_to_ath_pts'),
                'best_match_direction': best['direction'],
                'best_match_r': best['r_multiple'],
            })

    out_df = pd.DataFrame(results)
    out_path = DEMOS_PATH.with_name('coverage_check.csv')
    out_df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}\n")

    matched = out_df[out_df['match_status'] == 'matched']
    no_match = out_df[out_df['match_status'] == 'no_match']
    skipped = out_df[out_df['match_status'] == 'skipped_non_nq']

    print(f"In-cohort NQ trades: {len(in_cohort) - len(skipped)}")
    print(f"  Matched: {len(matched)} ({len(matched)/(len(in_cohort)-len(skipped))*100:.0f}%)")
    print(f"  No match: {len(no_match)} ({len(no_match)/(len(in_cohort)-len(skipped))*100:.0f}%)")
    print(f"\nNon-NQ skipped (ES, GC): {len(skipped)}")
    print(f"\nPost-cohort (need data refresh): {len(out_cohort)}")

    if len(matched):
        print(f"\n=== Matched trades — confluence_score distribution ===")
        if 'best_confluence_score' in matched.columns:
            print(matched['best_confluence_score'].value_counts().sort_index().to_string())

        print(f"\n=== Per-demo match table ===")
        cols_to_show = ['recap_id', 'recap_date', 'trade_seq', 'entry_time_ny',
                        'direction', 'setup_type', 'outcome', 'match_status',
                        'best_confluence_score', 'best_has_ob_confirm',
                        'best_distance_to_ath_pts', 'best_match_r']
        print(matched[cols_to_show].to_string(index=False))

    if len(no_match):
        print(f"\n=== No-match demos (model missed) ===")
        cols = ['recap_id', 'recap_date', 'trade_seq', 'entry_time_ny',
                'direction', 'setup_type', 'triggering_sweep', 'confluences', 'outcome']
        print(no_match[cols].to_string(index=False))


if __name__ == '__main__':
    main()
