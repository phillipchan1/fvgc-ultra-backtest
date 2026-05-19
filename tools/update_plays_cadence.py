#!/usr/bin/env python3
"""Add `cadence` text to each play in playbook/plays.json.

For plays with computed cadence (from trade_lists), use the data.
For plays without trade_lists, synthesize from existing frequency_per_month
field, or skip with a note.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYS_JSON  = ROOT / 'playbook' / 'plays.json'
CADENCE_JSON = ROOT / 'playbook' / 'cadence_cache.json'


def phrase_from_per_month(per_month: float, label: str = '') -> str:
    yr = per_month * 12
    if per_month >= 4:
        return f"~{yr:.0f}/yr (~{per_month:.1f}/mo) — about every {30/per_month:.0f}-{30/per_month*1.5:.0f} days{label}"
    elif per_month >= 1:
        return f"~{yr:.0f}/yr (~{per_month:.1f}/mo) — roughly 1 every {30/per_month:.0f} days{label}"
    else:
        gap = 30 / max(per_month, 0.1)
        return f"~{yr:.0f}/yr (~{per_month:.2f}/mo) — about 1 every {gap:.0f} days{label}"


def phrase_from_cadence(c: dict) -> str:
    if c.get('n', 0) == 0:
        return ""
    parts = [f"~{c['trades_per_yr']:.0f}/yr (~{c['trades_per_month']:.1f}/mo)"]
    med = c.get('median_gap_days')
    if med is not None and med > 1:
        if med < 14:
            parts.append(f"~1 every {med:.0f}d (median)")
        elif med < 31:
            parts.append(f"~1 every {med:.0f}d (~{med/7:.1f}wk median)")
        else:
            parts.append(f"~1 every {med/30:.1f}mo (median)")
    p90 = c.get('p90_gap_days')
    if p90 and p90 > 30:
        parts.append(f"longest typical wait {p90:.0f}d (90th pct)")
    return "; ".join(parts)


def main():
    plays = json.load(open(PLAYS_JSON))
    cadence = json.load(open(CADENCE_JSON))

    for p in plays:
        name = p['name']

        # 1) Computed from trade_lists
        if name in cadence and cadence[name].get('n', 0) > 0:
            c = cadence[name]
            p['cadence'] = phrase_from_cadence(c)
            p['cadence_stats'] = {
                'trades_per_yr': c['trades_per_yr'],
                'trades_per_month': c['trades_per_month'],
                'median_gap_days': c.get('median_gap_days'),
                'p90_gap_days': c.get('p90_gap_days'),
                'max_gap_days': c.get('max_gap_days'),
                'source': 'computed_from_trade_list',
            }
            continue

        # 2) Synthesize from existing frequency_per_month
        fpm = p.get('frequency_per_month')
        if isinstance(fpm, dict):
            sub_phrases = []
            for k, v in fpm.items():
                if isinstance(v, (int, float)):
                    sub_phrases.append(f"{k}: {phrase_from_per_month(v)}")
            if sub_phrases:
                p['cadence'] = " | ".join(sub_phrases)
                p['cadence_stats'] = {'source': 'derived_from_frequency_per_month'}
                continue
        if isinstance(fpm, (int, float)):
            p['cadence'] = phrase_from_per_month(fpm)
            p['cadence_stats'] = {'source': 'derived_from_frequency_per_month'}
            continue

        # 3) Fall back to existing 'frequency' string
        if p.get('frequency'):
            p['cadence'] = p['frequency']
            p['cadence_stats'] = {'source': 'existing_frequency_field'}
            continue

        p['cadence'] = "(unknown — no trade list or frequency field)"
        p['cadence_stats'] = {'source': 'missing'}

    PLAYS_JSON.write_text(json.dumps(plays, indent=2, ensure_ascii=False))
    print(f"Updated {len(plays)} plays.")
    for p in plays:
        print(f"  {p['name'][:62]:62s}  {p['cadence']}")


if __name__ == '__main__':
    main()
