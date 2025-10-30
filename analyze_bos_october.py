#!/usr/bin/env python3
"""
Analyze BOS trades from October backtest
"""
import pandas as pd

# Load trades
df = pd.read_csv('outputs/trades/trades.csv')

# Filter for BOS trades
bos_trades = df[df['entry_model'] == 'fvg_continuation_bos'].copy()

print("=" * 100)
print("BOS TRADES ANALYSIS - OCTOBER 2025")
print("=" * 100)

print(f"\nTotal Trades: {len(df)}")
print(f"BOS Trades: {len(bos_trades)}")

if len(bos_trades) == 0:
    print("\nNO BOS TRADES FOUND")
    exit()

# Calculate metrics
wins = len(bos_trades[bos_trades['pnl'] > 0])
losses = len(bos_trades[bos_trades['pnl'] < 0])
win_rate = wins / len(bos_trades) * 100

gross_profit = bos_trades[bos_trades['pnl'] > 0]['pnl'].sum() if wins > 0 else 0
gross_loss = abs(bos_trades[bos_trades['pnl'] < 0]['pnl'].sum()) if losses > 0 else 0
net_pnl = bos_trades['pnl'].sum()
pf = gross_profit / gross_loss if gross_loss > 0 else 0

print(f"\nBOS Model Performance:")
print(f"  Wins/Losses:     {wins}/{losses}")
print(f"  Win Rate:        {win_rate:.2f}%")
print(f"  Net P&L:         {net_pnl:.2f}")
print(f"  Profit Factor:   {pf:.3f}")

# Show each trade
print("\n" + "=" * 100)
print("DETAILED BOS TRADES (sorted by date)")
print("=" * 100)
print(f"\n{'Entry Time':<25} {'Dir':<6} {'Entry':<10} {'Exit':<10} {'P&L':<8} {'Exit Reason':<12} {'FVG Size':<10} {'Gap Close?':<12} {'Beyond 50%?'}")
print("-" * 100)

for idx, row in bos_trades.iterrows():
    entry_time = row['entry_time']
    direction = row['direction']
    entry_price = row['entry_price']
    exit_price = row['exit_price']
    pnl = row['pnl']
    exit_reason = row['exit_reason']
    fvg_size = row['fvg_size_pts']
    gap_close = "YES" if row['retraced_closed_in_gap'] else "NO"
    beyond_50 = "YES" if row['retraced_beyond_50pct'] else "NO"
    
    pnl_str = f"{pnl:+.2f}"
    print(f"{entry_time:<25} {direction:<6} {entry_price:<10.2f} {exit_price:<10.2f} {pnl_str:<8} {exit_reason:<12} {fvg_size:<10.2f} {gap_close:<12} {beyond_50}")

# Summary by direction
print("\n" + "=" * 100)
print("BREAKDOWN BY DIRECTION")
print("=" * 100)

for direction in ['long', 'short']:
    dir_trades = bos_trades[bos_trades['direction'] == direction]
    if len(dir_trades) == 0:
        continue
    
    dir_wins = len(dir_trades[dir_trades['pnl'] > 0])
    dir_losses = len(dir_trades[dir_trades['pnl'] < 0])
    dir_wr = dir_wins / len(dir_trades) * 100 if len(dir_trades) > 0 else 0
    dir_net = dir_trades['pnl'].sum()
    
    print(f"\n{direction.upper()}:")
    print(f"  Trades:    {len(dir_trades)}")
    print(f"  Win Rate:  {dir_wr:.2f}%")
    print(f"  Net P&L:   {dir_net:.2f}")

# Check gap closure correlation
print("\n" + "=" * 100)
print("GAP CLOSURE CORRELATION")
print("=" * 100)

no_closure = bos_trades[bos_trades['retraced_closed_in_gap'] == False]
with_closure = bos_trades[bos_trades['retraced_closed_in_gap'] == True]

for label, subset in [("NO Gap Closure", no_closure), ("WITH Gap Closure", with_closure)]:
    if len(subset) == 0:
        continue
    
    wins = len(subset[subset['pnl'] > 0])
    wr = wins / len(subset) * 100 if len(subset) > 0 else 0
    net = subset['pnl'].sum()
    
    print(f"\n{label}:")
    print(f"  Trades:    {len(subset)}")
    print(f"  Win Rate:  {wr:.2f}%")
    print(f"  Net P&L:   {net:.2f}")

print("\n")

