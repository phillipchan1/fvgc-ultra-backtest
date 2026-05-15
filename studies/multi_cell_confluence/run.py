"""End-to-end orchestrator for the multi-cell confluence matrix study.

Run all phases in sequence:
    python -m studies.multi_cell_confluence.run
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from studies.multi_cell_confluence import (  # noqa: E402
    build_analysis_frame,
    baseline,
    factor_mining,
    tier_construction,
    oos_validation,
    regime_breakdown,
    build_report,
)


PHASES = [
    ('A', 'Build analysis frame', build_analysis_frame.main),
    ('B', 'Per-cell baseline', baseline.main),
    ('C', 'Factor mining', factor_mining.main),
    ('D', 'Tier construction', tier_construction.main),
    ('E', 'OOS validation', oos_validation.main),
    ('F', 'Regime breakdown', regime_breakdown.main),
    ('G', 'Build report artifacts', build_report.main),
]


def main():
    for label, name, fn in PHASES:
        print('\n' + '#' * 80)
        print(f'#  PHASE {label} — {name}')
        print('#' * 80 + '\n')
        fn()
    print('\nAll phases complete. See studies/multi_cell_confluence/analysis.md')


if __name__ == '__main__':
    main()
