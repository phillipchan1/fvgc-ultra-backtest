"""Condition-vs-Entry analysis: how often does the FVGC engine fire on
"perfect setup" days for each play?

For each play (M1 Short / M2 Long / M3 Long), cross-references all trading
days against the engine's actual fires to answer:
- What % of days have the play's conditions live (no veto + at threshold)?
- What % of those setup-days actually print an FVGC trade?
- Expected R per setup-day (combining EV/trade × P(fire))

Why it matters: tells the trader whether sitting at the screen with conditions
live is worth it (expected value), and how much "wasted screen time" to expect.

Output: results/condition_vs_entry.csv with per-play, per-tier breakdown.
        results/expectancy_per_play.json for downstream consumption (briefing).
"""

from __future__ import annotations

import calendar as _cal
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

from studies.multi_cell_confluence.utils import RESULTS_DIR, TRADING_DAYS_PATH  # noqa: E402

# Same play stacks used in tools/morning_briefing.py MATRIX_PLAYS.
# Excludes signal-time-only factors like variant_no_fvg (can't be known
# without a trade firing).
PLAYS = {
    'M1 Short': {
        'pros': ['bear_930', 'gap_large_down', 'c930_body_top_q', 'prior_day_weak',
                 'is_fomc_week', 'vixy_high', 'dow_friday'],
        'vetos': ['vixy_low', 'dow_monday'],
        'window_min': 9 * 60 + 30,
        'window_max': 9 * 60 + 45,
        'direction': 'short',
        'tradeable_threshold': 2,
        'ev_per_trade_R': 0.77,  # from results/ev_M1_short_2plus.csv (recommended scale)
    },
    'M2 Long': {
        'pros': ['bull_930', 'dow_thursday', 'has_pre_rth_news', 'macro_1_2plus_fvgs',
                 'regime_bull', 'has_5m_bear_fvg', 'gap_up'],
        'vetos': ['is_opex_week', 'dow_wednesday', 'regime_bear'],
        'window_min': 9 * 60 + 45,
        'window_max': 10 * 60,
        'direction': 'long',
        'tradeable_threshold': 3,
        'ev_per_trade_R': 0.58,
    },
    'M3 Long': {
        'pros': ['c930_range_bot_q', 'or_5m_bot_q', 'no_5m_bear_fvg', 'dow_friday',
                 'not_fomc_week', 'prior_day_weak'],  # variant_no_fvg dropped (signal-time)
        'vetos': ['dow_tuesday', 'or_5m_top_q', 'prior_day_mid'],
        'window_min': 10 * 60,
        'window_max': 10 * 60 + 15,
        'direction': 'long',
        'tradeable_threshold': 3,
        'ev_per_trade_R': 0.20,
    },
}


def _is_opex_week(d: date) -> bool:
    cal = _cal.monthcalendar(d.year, d.month)
    fridays = [w[4] for w in cal if w[4] != 0]
    if len(fridays) < 3:
        return False
    third_fri = date(d.year, d.month, fridays[2])
    return -4 <= (d - third_fri).days <= 0


def build_day_factors(td: pd.DataFrame) -> pd.DataFrame:
    """Augment trading_days frame with all derived factor columns."""
    out = td.sort_values('date').reset_index(drop=True).copy()

    # 60d NQ regime
    out['ret_60d'] = out['rth_close'].pct_change(60)
    out['regime_bull'] = out['ret_60d'] > 0.05
    out['regime_bear'] = out['ret_60d'] < -0.05

    # VIXY quartiles
    vp25 = out['vixy_prior_close'].quantile(0.25)
    vp75 = out['vixy_prior_close'].quantile(0.75)
    out['vixy_low'] = out['vixy_prior_close'] <= vp25
    out['vixy_high'] = out['vixy_prior_close'] >= vp75

    # 9:30-candle quartiles
    body_q75 = out['candle_930_body'].quantile(0.75)
    range_q25 = out['candle_930_range'].quantile(0.25)
    out['c930_body_top_q'] = out['candle_930_body'] >= body_q75
    out['c930_range_bot_q'] = out['candle_930_range'] <= range_q25

    # 5min OR quartiles
    or5_q25 = out['or_5min_range'].quantile(0.25)
    or5_q75 = out['or_5min_range'].quantile(0.75)
    out['or_5m_bot_q'] = out['or_5min_range'] <= or5_q25
    out['or_5m_top_q'] = out['or_5min_range'] >= or5_q75

    # Day of week
    for dow in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
        out[f'dow_{dow}'] = out['day_of_week_name'] == dow.capitalize()

    # Calendar
    out['is_opex_week'] = out['date'].apply(_is_opex_week)

    # Gap buckets
    out['gap_up'] = out['gap_from_prior_close'] > 10
    out['gap_down'] = out['gap_from_prior_close'] < -10
    out['gap_large_down'] = out['gap_from_prior_close'] < -100
    out['gap_large_up'] = out['gap_from_prior_close'] > 100

    # 9:30 candle direction
    out['bear_930'] = out['candle_930_direction'] == 'bearish'
    out['bull_930'] = out['candle_930_direction'] == 'bullish'

    # Prior day position thirds
    out['prior_day_weak'] = out['prior_day_close_position'] < 1 / 3
    out['prior_day_strong'] = out['prior_day_close_position'] > 2 / 3
    out['prior_day_mid'] = ((out['prior_day_close_position'] >= 1 / 3)
                            & (out['prior_day_close_position'] <= 2 / 3))

    # First-5min FVG
    out['has_5m_bear_fvg'] = out['fvgs_first_5min_bearish'].fillna(0) >= 1
    out['no_5m_bear_fvg'] = out['fvgs_first_5min_bearish'].fillna(0) == 0

    # Macro_1 FVG count
    out['macro_1_2plus_fvgs'] = out['macro_1_num_fvgs'].fillna(0) >= 2

    # News + FOMC (booleanize whatever string format the CSV used)
    for col in ['has_pre_rth_news', 'is_fomc_week']:
        out[col] = out[col].astype(str).str.lower().isin(['true', '1', 'yes'])
    out['no_pre_rth_news'] = ~out['has_pre_rth_news']
    out['not_fomc_week'] = ~out['is_fomc_week']

    return out


def main():
    print(f'Loading {TRADING_DAYS_PATH}...')
    td = pd.read_csv(TRADING_DAYS_PATH)
    td['date'] = pd.to_datetime(td['date']).dt.date

    # Match the trade-study window
    trades = pd.read_csv(RESULTS_DIR / 'trades_analysis.csv')
    trades['date'] = pd.to_datetime(trades['date']).dt.date
    date_min, date_max = trades['date'].min(), trades['date'].max()
    td = td[(td['date'] >= date_min) & (td['date'] <= date_max)]
    print(f'  {len(td)} trading days in window {date_min} -> {date_max}')

    td = build_day_factors(td)

    trades_no_ps = trades[trades['variant'] != 'protected_swing'].copy()
    trades_no_ps['minute'] = (pd.to_datetime(trades_no_ps['timestamp']).dt.hour * 60
                              + pd.to_datetime(trades_no_ps['timestamp']).dt.minute)

    rows = []
    expectancy_summary = {}

    for name, play in PLAYS.items():
        td[f'{name}_conf'] = td[play['pros']].sum(axis=1)
        td[f'{name}_veto'] = td[play['vetos']].any(axis=1)

        play_trades = trades_no_ps[
            (trades_no_ps['direction'] == play['direction'])
            & (trades_no_ps['minute'] >= play['window_min'])
            & (trades_no_ps['minute'] < play['window_max'])
        ]
        fired_dates = set(play_trades['date'].unique())
        td[f'{name}_fired'] = td['date'].isin(fired_dates)

        days_total = len(td)
        veto_days = int(td[f'{name}_veto'].sum())
        no_veto = ~td[f'{name}_veto']

        per_tier = {}
        for thr in (0, 1, 2, 3, 4):
            mask = no_veto & (td[f'{name}_conf'] >= thr)
            d = int(mask.sum())
            f = int((mask & td[f'{name}_fired']).sum())
            per_tier[thr] = {
                'setup_days': d,
                'pct_of_all_days': round(100 * d / days_total, 1),
                'fired_days': f,
                'no_fire_days': d - f,
                'fire_rate_pct': round(100 * f / d, 1) if d else None,
            }
            rows.append({'play': name, 'tier_min_conf': thr, **per_tier[thr]})

        # Tradeable-threshold expectancy
        thr = play['tradeable_threshold']
        cell = per_tier[thr]
        avg_trades_per_fired_day = (
            len(play_trades[play_trades['date'].isin(set(td[no_veto & (td[f'{name}_conf'] >= thr)]['date']))])
            / cell['fired_days']
        ) if cell['fired_days'] else 0
        ev_per_setup_day = (cell['fire_rate_pct'] / 100) * avg_trades_per_fired_day * play['ev_per_trade_R']

        expectancy_summary[name] = {
            'tradeable_threshold': thr,
            'window': f'{play["window_min"]//60}:{play["window_min"]%60:02d}-'
                      f'{play["window_max"]//60}:{play["window_max"]%60:02d}',
            'direction': play['direction'],
            'days_total': days_total,
            'veto_days': veto_days,
            'veto_pct': round(100 * veto_days / days_total, 1),
            'setup_days_at_threshold': cell['setup_days'],
            'setup_pct_of_all_days': cell['pct_of_all_days'],
            'fired_days_at_threshold': cell['fired_days'],
            'fire_rate_pct': cell['fire_rate_pct'],
            'no_fire_days': cell['no_fire_days'],
            'avg_trades_per_fired_day': round(avg_trades_per_fired_day, 2),
            'ev_per_trade_R': play['ev_per_trade_R'],
            'ev_per_setup_day_R': round(ev_per_setup_day, 3),
            'fire_rate_by_tier_pct': {k: v['fire_rate_pct'] for k, v in per_tier.items()},
        }

        print(f'\n{"=" * 60}\n{name}  (no veto + conf >= {thr})\n{"=" * 60}')
        print(f'  Veto active on {veto_days}/{days_total} days ({100*veto_days/days_total:.1f}%) — auto-skip')
        print(f'  Setup days at threshold: {cell["setup_days"]} ({cell["pct_of_all_days"]}% of all days)')
        print(f'  FVGC fires: {cell["fired_days"]} ({cell["fire_rate_pct"]}% of setup days)')
        print(f'  No-fire: {cell["no_fire_days"]} ({100 - cell["fire_rate_pct"]:.1f}% of setup days)')
        print(f'  Avg trades on fired days: {avg_trades_per_fired_day:.2f}')
        print(f'  EV per trade: +{play["ev_per_trade_R"]}R')
        print(f'  >>> Expectancy when sitting at screen with setup live: +{ev_per_setup_day:.3f}R per setup-day <<<')

    out_df = pd.DataFrame(rows)
    out_path = RESULTS_DIR / 'condition_vs_entry.csv'
    out_df.to_csv(out_path, index=False)
    print(f'\nWrote {out_path}')

    json_path = RESULTS_DIR / 'expectancy_per_play.json'
    with open(json_path, 'w') as f:
        json.dump(expectancy_summary, f, indent=2)
    print(f'Wrote {json_path}')


if __name__ == '__main__':
    main()
