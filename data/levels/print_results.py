#!/usr/bin/env python3
"""Read all CSVs in data/levels/results/ and print each as a formatted table to stdout."""

from pathlib import Path

import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / 'results'

for csv_path in sorted(RESULTS_DIR.glob('*.csv')):
    df = pd.read_csv(csv_path)
    print(f'\n{"=" * 60}')
    print(f'{csv_path.name}')
    print(f'{"=" * 60}')
    print(df.to_string(index=False))
