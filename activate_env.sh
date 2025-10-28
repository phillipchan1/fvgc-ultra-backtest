#!/bin/bash
# activate_env.sh
# ---------------------------------------------------------------------------
# Quick activation script for FVG Backtest environment
# ---------------------------------------------------------------------------

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to project directory
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

echo "🚀 FVG Backtest environment activated!"
echo ""
echo "Available commands:"
echo "  python src/main.py                    # Run baseline backtest"
echo "  python test_permutation.py list       # List available permutations"
echo "  python test_permutation.py <name>     # Test specific permutation"
echo "  python src/sweep.py --top 20          # Run parameter sweep"
echo "  python setup.py                       # Setup project"
echo ""
echo "Current directory: $(pwd)"
echo "Virtual environment: $(which python)"
