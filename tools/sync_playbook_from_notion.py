#!/usr/bin/env python3
"""
Sync playbook/plays.json from the Notion FVGC Playbook database.

Notion is the source of truth. This script:
1. Reads the raw Notion query result from a JSON file
2. Reads existing playbook/plays.json
3. Builds a new plays.json mirroring Notion, preserving the local-only
   `pre_market_factors` array (matched by Notion page ID)
4. Drops plays not in Notion (treats them as artifacts)
5. Writes plays.json

The Notion query result is produced by the Claude Code morning routine
via the Notion MCP `notion-query-database-view` tool. The raw output is
expected as JSON with a `results` array of play objects.

Usage:
    python tools/sync_playbook_from_notion.py <path_to_notion_raw.json>
    python tools/sync_playbook_from_notion.py -        # read from stdin

Mapping reference (Notion → plays.json):
    Strategy Name           → name
    Direction               → direction (lowercase)
    Status                  → status (verified / backtesting / idea / rejected)
    WR                      → wr_base
    Sample Size             → sample_size
    Description             → description
    Pre-Market Conditions   → pre_market_conditions (free text)
    Intraday Conditions     → action_plan (concatenated with Exit Strategy)
    Exit Strategy           → action_plan (suffix)
    Tier (A/B)              → tier
    Confidence              → confidence (lowercase)
    Frequency               → frequency
    Best PF                 → pf_base
    Avg MFE (R)             → avg_mfe_r
    Macro                   → window (array of macro windows)
    url                     → notion_url
    —                       → pre_market_factors (LOCAL-ONLY, preserved)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLAYS_JSON = REPO / 'playbook' / 'plays.json'

STATUS_MAP = {
    'Verified & Active Play': 'verified',
    'Backtesting': 'backtesting',
    'Idea': 'idea',
    'Rejected': 'rejected',
}
DIRECTION_MAP = {'Short': 'short', 'Long': 'long', 'Both': 'both'}
CONFIDENCE_MAP = {'High': 'high', 'Medium': 'medium', 'Low': 'low'}


def page_id(url: str | None) -> str | None:
    """Extract the 32-char hex page ID from any Notion URL format.

    Works for both www.notion.so/<id> and app.notion.com/p/<id>.
    """
    if not url:
        return None
    m = re.search(r'([0-9a-f]{32})', url.lower().replace('-', ''))
    return m.group(1) if m else None


def normalize_play(n: dict) -> dict:
    """Map a Notion row to a plays.json entry. pre_market_factors is filled
    in separately by the caller (it's preserved from existing plays.json)."""
    name = (n.get('Strategy Name') or '').strip()
    if not name:
        return None

    intraday = n.get('Intraday Conditions') or ''
    exit_strategy = n.get('Exit Strategy') or ''
    action_plan_parts = []
    if intraday:
        action_plan_parts.append(intraday)
    if exit_strategy:
        action_plan_parts.append(f'Exit Strategy: {exit_strategy}')
    action_plan = '\n\n'.join(action_plan_parts) or None

    return {
        'name': name,
        'direction': DIRECTION_MAP.get(n.get('Direction'), 'both'),
        'status': STATUS_MAP.get(n.get('Status'), 'idea'),
        'wr_base': n.get('WR'),
        'sample_size': n.get('Sample Size'),
        'description': n.get('Description') or None,
        'pre_market_conditions': n.get('Pre-Market Conditions') or None,
        'action_plan': action_plan,
        'tier': n.get('Tier'),
        'confidence': CONFIDENCE_MAP.get(n.get('Confidence')),
        'frequency': n.get('Frequency'),
        'pf_base': n.get('Best PF'),
        'avg_mfe_r': n.get('Avg MFE (R)'),
        'window': n.get('Macro') or [],
        'notion_url': n.get('url'),
        'pre_market_factors': [],  # filled in by caller
    }


def sync(notion_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Build new plays list from Notion rows. Preserves pre_market_factors
    from the existing plays.json by Notion page ID, with name-prefix fallback.

    Returns (new_plays, deleted_plays).
    """
    if PLAYS_JSON.exists():
        existing = json.loads(PLAYS_JSON.read_text())
    else:
        existing = []

    by_id = {page_id(p.get('notion_url')): p
             for p in existing if page_id(p.get('notion_url'))}
    by_name = {p.get('name'): p for p in existing}

    def find_prior(name: str, pid: str | None) -> dict:
        # Primary: exact page ID match
        if pid and pid in by_id:
            return by_id[pid]
        # Secondary: exact name match
        if name in by_name:
            return by_name[name]
        # Tertiary: name prefix (before any parenthetical)
        prefix = name.split('(')[0].strip()
        for k, v in by_name.items():
            k_prefix = k.split('(')[0].strip()
            if k_prefix and (prefix.startswith(k_prefix) or k_prefix.startswith(prefix)):
                return v
        return {}

    new_plays = []
    for n in notion_rows:
        p = normalize_play(n)
        if not p:
            continue
        prior = find_prior(p['name'], page_id(p.get('notion_url')))
        p['pre_market_factors'] = list(prior.get('pre_market_factors', []))
        new_plays.append(p)

    notion_ids = {page_id(p['notion_url']) for p in new_plays if p.get('notion_url')}
    notion_names = {p['name'] for p in new_plays}

    deleted = []
    for p in existing:
        pid = page_id(p.get('notion_url'))
        if pid and pid in notion_ids:
            continue
        if p.get('name') in notion_names:
            continue
        deleted.append(p)

    return new_plays, deleted


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', help='Path to Notion query JSON (or - for stdin)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show diff but do not write plays.json')
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == '-' else Path(args.input).read_text()
    data = json.loads(raw)
    # MCP returns {"results": [...]} but accept a bare array too.
    rows = data.get('results') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        print(f'[sync] expected array or {{"results": [...]}}', file=sys.stderr)
        sys.exit(1)

    new_plays, deleted = sync(rows)

    from collections import Counter
    counts = Counter(p['status'] for p in new_plays)
    print(f'[sync] Notion → plays.json')
    print(f'[sync] Synced {len(new_plays)} plays — '
          + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    if deleted:
        print(f'[sync] Removed {len(deleted)} artifact(s) not in Notion:')
        for p in deleted:
            print(f"          - {p.get('name')}")

    preserved = [p for p in new_plays if p['pre_market_factors']]
    if preserved:
        print(f'[sync] Preserved pre_market_factors on {len(preserved)} play(s):')
        for p in preserved:
            print(f"          · {p['name']}: {p['pre_market_factors']}")

    if args.dry_run:
        print('[sync] --dry-run: not writing plays.json')
        return

    PLAYS_JSON.write_text(
        json.dumps(new_plays, indent=2, ensure_ascii=False) + '\n')
    print(f'[sync] Wrote {PLAYS_JSON.relative_to(REPO)}')


if __name__ == '__main__':
    main()
