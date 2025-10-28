# test_permutation.py
# ---------------------------------------------------------------------------
# Test script for running individual permutations
# ---------------------------------------------------------------------------

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.models.permutations import list_permutations, print_permutation_info, apply_permutation, restore_config
from src.main import main

def test_permutation(perm_name: str):
    """Test a specific permutation."""
    print(f"Testing permutation: {perm_name}")
    print_permutation_info(perm_name)
    
    # Apply the permutation
    original_config = apply_permutation(perm_name)
    
    try:
        # Run the backtest
        main()
        print(f"\n✅ Permutation '{perm_name}' completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Permutation '{perm_name}' failed: {e}")
        
    finally:
        # Always restore original config
        restore_config(original_config)
        print(f"Restored original configuration.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        perm_name = sys.argv[1]
        if perm_name == "list":
            print("Available permutations:")
            for name in list_permutations():
                print(f"  {name}")
        else:
            test_permutation(perm_name)
    else:
        print("Usage:")
        print("  python test_permutation.py list                    # List all permutations")
        print("  python test_permutation.py <permutation_name>      # Test specific permutation")
        print("\nExample:")
        print("  python test_permutation.py tap_only")
