# setup.py
# ---------------------------------------------------------------------------
# Setup script for FVG Backtest project
# ---------------------------------------------------------------------------

import os
import sys

def create_directories():
    """Create necessary directories if they don't exist."""
    dirs = [
        "data/processed",
        "outputs/trades",
        "outputs/analysis", 
        "outputs/sweeps",
        "configs",
        "tests"
    ]
    
    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)
        print(f"✓ Created directory: {dir_path}")

def check_data_files():
    """Check if required data files exist."""
    required_files = [
        "data/raw/glbx-mdp3-20250911-20251010.ohlcv-1s.csv"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
        else:
            print(f"✓ Found data file: {file_path}")
    
    if missing_files:
        print(f"\n⚠️  Missing data files:")
        for file_path in missing_files:
            print(f"   - {file_path}")
        print("\nPlease ensure your data files are in the correct location.")
        return False
    
    return True

def main():
    """Main setup function."""
    print("🚀 Setting up FVG Backtest project...")
    print()
    
    # Create directories
    print("Creating directory structure...")
    create_directories()
    print()
    
    # Check data files
    print("Checking data files...")
    data_ok = check_data_files()
    print()
    
    if data_ok:
        print("✅ Setup complete! You can now run:")
        print("   python src/main.py                    # Run baseline backtest")
        print("   python test_permutation.py list       # List available permutations")
        print("   python test_permutation.py tap_only   # Test specific permutation")
    else:
        print("❌ Setup incomplete. Please add missing data files and run again.")

if __name__ == "__main__":
    main()
