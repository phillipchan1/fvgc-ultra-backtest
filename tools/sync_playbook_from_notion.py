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


def _load_dotenv() -> None:
    """Load KEY=value pairs from .env in the repo root into os.environ.
    Existing env vars take precedence so GitHub Actions secrets aren't
    overridden. Stdlib only."""
    import os
    env_path = REPO / '.env'
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or \
           (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

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


def _as_list(v) -> list:
    """Defensive list coercion. Notion's MCP path sometimes returns
    multi_select fields as a JSON-encoded string (e.g. '["9:45-10:00"]')
    rather than a real list. Without this guard the bad shape persists
    through plays.json → briefing.json → dashboard, where it causes
    silent play drops because window-bucketing groups become unknown
    keys. Accepts list, stringified-JSON-list, single string, or None.
    """
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.startswith('['):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
        return [v] if v else []
    return []


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
        'window': _as_list(n.get('Macro')),
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


# ---------------------------------------------------------------------------
# Direct Notion HTTP API path — used by GitHub Actions cron so the morning
# briefing can run fully autonomously without Claude Code / MCP.
#
# Requires:
#   - NOTION_API_TOKEN env var (an Internal Integration secret)
#   - The integration must be shared with the FVGC Playbook database in Notion
#     (Database → ⋯ → Connections → invite the integration)
# ---------------------------------------------------------------------------

FVGC_PLAYBOOK_DB_ID = '33de2f0e7760802f8cf3e82d8cf2f8a3'


def fetch_from_notion_api(database_id: str, token: str) -> list[dict]:
    """Query the FVGC Playbook database via Notion's HTTP API. Returns a list
    of flat dicts matching the structure produced by the MCP path so the rest
    of the sync pipeline doesn't need to know which fetch was used."""
    import json as _json
    import urllib.request
    import urllib.error

    url = f'https://api.notion.com/v1/databases/{database_id}/query'
    all_pages: list[dict] = []
    cursor: str | None = None

    while True:
        body: dict = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        req = urllib.request.Request(
            url,
            data=_json.dumps(body).encode('utf-8'),
            method='POST',
            headers={
                'Authorization': f'Bearer {token}',
                'Notion-Version': '2022-06-28',
                'Content-Type': 'application/json',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = _json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')[:500]
            raise RuntimeError(
                f'Notion API HTTP {e.code}: {err_body}\n'
                f'Check that NOTION_API_TOKEN is valid and the integration '
                f'is shared with the database.'
            )
        for page in payload.get('results', []):
            all_pages.append(_notion_page_to_play_row(page))
        if not payload.get('has_more'):
            break
        cursor = payload.get('next_cursor')
    return all_pages


def _notion_page_to_play_row(page: dict) -> dict:
    """Flatten Notion's rich property structure into the same shape that the
    cached MCP JSON uses, so normalize_play() can consume either source
    interchangeably."""
    props = page.get('properties', {}) or {}

    def _title(name: str) -> str | None:
        items = (props.get(name) or {}).get('title') or []
        text = ''.join(t.get('plain_text', '') for t in items)
        return text or None

    def _text(name: str) -> str | None:
        items = (props.get(name) or {}).get('rich_text') or []
        text = ''.join(t.get('plain_text', '') for t in items)
        return text or None

    def _select(name: str) -> str | None:
        sel = (props.get(name) or {}).get('select')
        return sel.get('name') if sel else None

    def _multi(name: str) -> list[str]:
        items = (props.get(name) or {}).get('multi_select') or []
        return [it.get('name') for it in items if it.get('name')]

    def _number(name: str) -> float | None:
        return (props.get(name) or {}).get('number')

    def _url(name: str) -> str | None:
        return (props.get(name) or {}).get('url')

    return {
        'Strategy Name': _title('Strategy Name'),
        'Direction': _select('Direction'),
        'Status': _select('Status'),
        'WR': _text('WR'),
        'Sample Size': _number('Sample Size'),
        'Description': _text('Description'),
        'Pre-Market Conditions': _text('Pre-Market Conditions'),
        'Intraday Conditions': _text('Intraday Conditions'),
        'Exit Strategy': _text('Exit Strategy'),
        'Tier': _select('Tier'),
        'Confidence': _select('Confidence'),
        'Frequency': _text('Frequency'),
        'Best PF': _number('Best PF'),
        'Avg MFE (R)': _number('Avg MFE (R)'),
        'Macro': _multi('Macro'),
        'Manual Backtest Notes': _text('Manual Backtest Notes'),
        'Analysis': _url('Analysis'),
        'Trade List': _url('Trade List'),
        'url': page.get('url'),
    }


def main():
    import os
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', nargs='?',
                    help='Path to Notion query JSON (or - for stdin). Omit when '
                         'using --from-api.')
    ap.add_argument('--from-api', action='store_true',
                    help='Fetch directly from Notion HTTP API. Requires '
                         'NOTION_API_TOKEN env var.')
    ap.add_argument('--database-id', default=FVGC_PLAYBOOK_DB_ID,
                    help=f'Notion database ID (default: FVGC Playbook).')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show diff but do not write plays.json')
    args = ap.parse_args()

    if args.from_api:
        token = os.environ.get('NOTION_API_TOKEN')
        if not token:
            print('[sync] NOTION_API_TOKEN env var not set', file=sys.stderr)
            sys.exit(1)
        print(f'[sync] Querying Notion API: db={args.database_id}')
        rows = fetch_from_notion_api(args.database_id, token)
    else:
        if not args.input:
            print('[sync] Must provide input file or --from-api', file=sys.stderr)
            sys.exit(1)
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
