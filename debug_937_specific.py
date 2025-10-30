import pandas as pd
import sys
sys.path.insert(0, '.')
from src.core.data_loader import load_processed_30s_csv
from src.core.fvg_detection import detect_fvgs, create_fvg_from_row
from src.core.config import CONFIG
from src.models.fvg_continuation_no_fvg import FVGContinuationNoFVGModel

# Load Oct 24
CONFIG['test_period'] = 'single_day'
CONFIG['test_date'] = '2025-10-24'
df = load_processed_30s_csv('data/processed/data_30s.csv')
df = df.reset_index(drop=True)
df = detect_fvgs(df)

# Find the 9:37 bar
for i in range(len(df)):
    if df.iloc[i]['timestamp'].strftime('%H:%M:%S') == '09:37:00':
        bar_index = i
        break

print(f"Bar #{bar_index} @ 09:37:00 - Entry candidate")
current_bar = df.iloc[bar_index]
previous_bar = df.iloc[bar_index - 1]

print(f"\nCurrent bar (9:37): close={current_bar['close']:.2f}")
print(f"Previous bar (9:36:30): high={previous_bar['high']:.2f}, close={previous_bar['close']:.2f}")

# Find bullish FVGs before this bar
print(f"\nBullish FVGs created before bar #{bar_index}:")
for i in range(bar_index):
    if df.iloc[i]['bull_fvg']:
        print(f"  FVG at bar #{i} @ {df.iloc[i]['timestamp'].strftime('%H:%M:%S')}: {df.iloc[i]['bull_lower']:.2f} - {df.iloc[i]['bull_upper']:.2f}")

# Try to evaluate with the model
# Find a bullish FVG to test with
test_fvg = None
for i in range(bar_index-1, max(0, bar_index-10), -1):
    if df.iloc[i]['bull_fvg']:
        test_fvg = create_fvg_from_row(df.iloc[i], i, 'bullish')
        print(f"\nTesting with FVG from bar #{i}: {test_fvg.lower:.2f} - {test_fvg.upper:.2f}")
        break

if test_fvg:
    model = FVGContinuationNoFVGModel()
    
    # Check swing high manually
    print(f"\nFinding swing high after FVG (bar #{test_fvg.created_idx})...")
    swing_idx = model._find_swing_high(test_fvg.created_idx + 1, df)
    
    if swing_idx:
        swing_high_price = df.iloc[swing_idx]['high']
        print(f"Swing high found at bar #{swing_idx} @ {df.iloc[swing_idx]['timestamp'].strftime('%H:%M:%S')}")
        print(f"Swing high price: {swing_high_price:.2f}")
        
        print(f"\nChecking BOS exclusion...")
        print(f"Previous candle close: {previous_bar['close']:.2f}")
        print(f"Previous candle closed through swing? {previous_bar['close'] > swing_high_price}")
        
        print(f"\nCandles between swing and current:")
        for check_idx in range(swing_idx, bar_index):
            check_bar = df.iloc[check_idx]
            closed_through = check_bar['close'] > swing_high_price
            marker = ' ← CLOSES THROUGH SWING' if closed_through else ''
            print(f"  Bar #{check_idx} @ {check_bar['timestamp'].strftime('%H:%M:%S')}: close={check_bar['close']:.2f}{marker}")
    
    else:
        print("No swing high found!")

