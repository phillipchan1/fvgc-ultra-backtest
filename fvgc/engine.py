"""Backtesting engine — trade simulation, statistics, and logging."""

import pandas as pd
from pathlib import Path
from typing import List, Dict


# ===================================================================
# Trade simulation
# ===================================================================

R_LEVELS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]


def simulate_trades(signals: List[Dict], candles: pd.DataFrame) -> List[Dict]:
    """Walk forward from each entry to determine W/L outcome.

    For each signal with valid SL/TP, check subsequent candles to see
    whether TP or SL is hit first.  Tracks MFE (max favorable excursion)
    and MAE (max adverse excursion) through the end of the trading day,
    plus whether each R-level target was reached before the stop loss.

    Returns signals with outcome, exit, pnl, MFE/MAE, and R-level fields.
    """
    results = []
    for sig in signals:
        sl = sig.get('sl', '')
        tp = sig.get('tp', '')
        if sl == '' or tp == '':
            sig['outcome'] = 'skip'
            sig['exit_price'] = ''
            sig['exit_time'] = ''
            sig['pnl'] = ''
            results.append(sig)
            continue

        entry_idx = sig['entry_idx']
        direction = sig['direction']
        entry_price = sig['entry_price']
        entry_date = sig['timestamp'].date()
        sl_dist = sig.get('sl_dist', abs(entry_price - sl))

        outcome = 'open'
        exit_price = ''
        exit_time = ''
        pnl = ''

        max_fav = 0.0
        max_adv = 0.0
        sl_hit = False
        r_hit_bars = {}

        for j in range(entry_idx + 1, len(candles)):
            bar = candles.iloc[j]
            if bar['timestamp_ny'].date() != entry_date:
                if outcome == 'open':
                    outcome = 'eod'
                    exit_price = bar_prev['close']
                    exit_time = bar_prev['timestamp_ny']
                    if direction == 'short':
                        pnl = entry_price - exit_price
                    else:
                        pnl = exit_price - entry_price
                break

            bar_prev = bar
            bars_held = j - entry_idx

            # Track MFE/MAE (full day from entry)
            if direction == 'long':
                fav = bar['high'] - entry_price
                adv = entry_price - bar['low']
            else:
                fav = entry_price - bar['low']
                adv = bar['high'] - entry_price

            max_fav = max(max_fav, fav)
            max_adv = max(max_adv, adv)

            # Track R-level hits before SL
            if not sl_hit and sl_dist > 0:
                for r in R_LEVELS:
                    if r not in r_hit_bars and fav >= sl_dist * r:
                        r_hit_bars[r] = bars_held

            # Determine 1R outcome
            if outcome == 'open':
                if direction == 'short':
                    if bar['high'] >= sl and bar['low'] <= tp:
                        outcome = 'ambiguous'
                        exit_price = sl
                        exit_time = bar['timestamp_ny']
                        pnl = -(sl - entry_price)
                        sl_hit = True
                        break
                    if bar['high'] >= sl:
                        outcome = 'loss'
                        exit_price = sl
                        exit_time = bar['timestamp_ny']
                        pnl = -(sl - entry_price)
                        sl_hit = True
                        break
                    if bar['low'] <= tp:
                        outcome = 'win'
                        exit_price = tp
                        exit_time = bar['timestamp_ny']
                        pnl = entry_price - tp
                        # Don't break — continue tracking MFE through end of day
                else:
                    if bar['low'] <= sl and bar['high'] >= tp:
                        outcome = 'ambiguous'
                        exit_price = sl
                        exit_time = bar['timestamp_ny']
                        pnl = -(entry_price - sl)
                        sl_hit = True
                        break
                    if bar['low'] <= sl:
                        outcome = 'loss'
                        exit_price = sl
                        exit_time = bar['timestamp_ny']
                        pnl = -(entry_price - sl)
                        sl_hit = True
                        break
                    if bar['high'] >= tp:
                        outcome = 'win'
                        exit_price = tp
                        exit_time = bar['timestamp_ny']
                        pnl = tp - entry_price
                        # Don't break — continue tracking MFE through end of day

        # MFE/MAE in R-multiples
        mfe_r = round(max_fav / sl_dist, 2) if sl_dist > 0 else 0
        mae_r = round(max_adv / sl_dist, 2) if sl_dist > 0 else 0

        sig['outcome'] = outcome
        sig['exit_price'] = exit_price
        sig['exit_time'] = exit_time
        sig['pnl'] = pnl
        sig['mfe_pts'] = round(max_fav, 2)
        sig['mae_pts'] = round(max_adv, 2)
        sig['mfe_r'] = mfe_r
        sig['mae_r'] = mae_r

        for r in R_LEVELS:
            r_key = str(r).replace('.', '_')
            sig[f'hit_{r_key}R'] = r in r_hit_bars
            sig[f'bars_to_{r_key}R'] = r_hit_bars.get(r, '')

        results.append(sig)
    return results


# ===================================================================
# Statistics
# ===================================================================

def summarize_results(results: List[Dict]) -> Dict:
    """Compute summary statistics from simulated trade results."""
    tradeable = [s for s in results if s.get('outcome') not in ('skip', '', None)]
    skipped = len(results) - len(tradeable)
    wins = sum(1 for s in tradeable if s['outcome'] == 'win')
    losses = sum(1 for s in tradeable if s['outcome'] == 'loss')
    eod = sum(1 for s in tradeable if s['outcome'] == 'eod')
    ambiguous = sum(1 for s in tradeable if s['outcome'] == 'ambiguous')
    total_pnl = sum(s['pnl'] for s in tradeable if s.get('pnl', '') != '')
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else None

    by_variant: Dict[str, Dict] = {}
    for s in tradeable:
        v = s.get('variant', 'unknown')
        if v not in by_variant:
            by_variant[v] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
        if s['outcome'] == 'win':
            by_variant[v]['wins'] += 1
        elif s['outcome'] == 'loss':
            by_variant[v]['losses'] += 1
        if s.get('pnl', '') != '':
            by_variant[v]['pnl'] += s['pnl']

    return {
        'total': len(tradeable),
        'skipped': skipped,
        'wins': wins,
        'losses': losses,
        'eod': eod,
        'ambiguous': ambiguous,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'by_variant': by_variant,
    }


def print_summary(stats: Dict) -> None:
    """Print a human-readable summary to stdout."""
    print(f"\n  Summary: {stats['total']} trades executed, "
          f"{stats['skipped']} skipped (no SL/TP)")
    print(f"  Wins: {stats['wins']}  Losses: {stats['losses']}  "
          f"EOD: {stats['eod']}  Ambiguous: {stats['ambiguous']}")
    if stats['win_rate'] is not None:
        print(f"  Win rate: {stats['win_rate']:.0f}%")
    else:
        print("  Win rate: N/A")
    print(f"  Total P&L: {stats['total_pnl']:+.2f} pts")

    if stats['by_variant']:
        print("\n  By variant:")
        for v, d in sorted(stats['by_variant'].items()):
            vw, vl = d['wins'], d['losses']
            vr = f"{vw/(vw+vl)*100:.0f}%" if (vw + vl) > 0 else "N/A"
            print(f"    {v:15s}  W={vw} L={vl} rate={vr}  P&L={d['pnl']:+.2f}")


# ===================================================================
# Logging
# ===================================================================

def log_fvgs(fvgs: List[Dict], path: Path) -> None:
    rows = []
    for f in fvgs:
        rows.append({
            'fvg_id': f['id'], 'direction': f['direction'],
            'top': f['top'], 'bottom': f['bottom'], 'mid': f['mid'],
            'created_at': f['created_ts'].strftime('%Y-%m-%d %H:%M:%S'),
            'inversed_at': (f['inversed_at_ts'].strftime('%Y-%m-%d %H:%M:%S')
                            if 'inversed_at_ts' in f else ''),
        })
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"Logged {len(rows)} FVGs -> {path}")


def log_signals(signals: List[Dict], path: Path) -> None:
    rows = []
    for s in signals:
        exit_t = s.get('exit_time', '')
        row = {
            'timestamp': s['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            'direction': s['direction'], 'entry_price': s['entry_price'],
            'variant': s['variant'],
            'sl': s.get('sl', ''), 'tp': s.get('tp', ''),
            'sl_dist': s.get('sl_dist', ''),
            'outcome': s.get('outcome', ''),
            'pnl': s.get('pnl', ''),
            'exit_price': s.get('exit_price', ''),
            'exit_time': exit_t.strftime('%Y-%m-%d %H:%M:%S') if hasattr(exit_t, 'strftime') else '',
            'fvg_id': s['fvg_id'], 'fvg_direction': s['fvg_direction'],
            'fvg_top': s['fvg_top'], 'fvg_bottom': s['fvg_bottom'],
            'fvg_mid': s['fvg_mid'],
            'fvg_created_at': s['fvg_created_ts'].strftime('%Y-%m-%d %H:%M:%S'),
            'entry_idx': s.get('entry_idx', ''),
            'mfe_pts': s.get('mfe_pts', ''),
            'mae_pts': s.get('mae_pts', ''),
            'mfe_r': s.get('mfe_r', ''),
            'mae_r': s.get('mae_r', ''),
        }
        # R-level hit flags
        for r in R_LEVELS:
            r_key = str(r).replace('.', '_')
            row[f'hit_{r_key}R'] = s.get(f'hit_{r_key}R', '')
            row[f'bars_to_{r_key}R'] = s.get(f'bars_to_{r_key}R', '')
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"Logged {len(rows)} signals -> {path}")
