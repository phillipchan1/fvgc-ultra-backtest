# permutation_validator.py
# ---------------------------------------------------------------------------
# Utilities for validating and applying permutation filters
# ---------------------------------------------------------------------------

import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from ..models.permutations import get_permutation, PERMUTATIONS
from ..core.config import CONFIG


def validate_permutation_definition(perm_name: str) -> bool:
    """Validate that a permutation definition is correct."""
    try:
        perm = get_permutation(perm_name)
        
        # Check required fields
        required_fields = ["description", "filter_type", "param"]
        for field in required_fields:
            if field not in perm:
                print(f"❌ Missing required field '{field}' in permutation '{perm_name}'")
                return False
        
        # Validate filter_type
        valid_types = ["range", "categorical", "config_change"]
        if perm["filter_type"] not in valid_types:
            print(f"❌ Invalid filter_type '{perm['filter_type']}' in permutation '{perm_name}'")
            return False
        
        # Validate range type
        if perm["filter_type"] == "range":
            range_fields = ["min", "max", "increment", "default_value"]
            for field in range_fields:
                if field not in perm:
                    print(f"❌ Missing range field '{field}' in permutation '{perm_name}'")
                    return False
            if perm["min"] >= perm["max"]:
                print(f"❌ Invalid range: min ({perm['min']}) >= max ({perm['max']}) in permutation '{perm_name}'")
                return False
        
        # Validate categorical type
        elif perm["filter_type"] == "categorical":
            if "value" not in perm:
                print(f"❌ Missing 'value' field in categorical permutation '{perm_name}'")
                return False
        
        # Validate config_change type
        elif perm["filter_type"] == "config_change":
            if "value" not in perm:
                print(f"❌ Missing 'value' field in config_change permutation '{perm_name}'")
                return False
        
        print(f"✅ Permutation '{perm_name}' is valid")
        return True
        
    except Exception as e:
        print(f"❌ Error validating permutation '{perm_name}': {e}")
        return False


def apply_single_filter(trades_df: pd.DataFrame, perm_name: str) -> Tuple[pd.DataFrame, List[str]]:
    """Apply a single permutation filter to trades dataframe.
    
    Returns:
        - Filtered dataframe
        - List of filter reasons for excluded trades
    """
    perm = get_permutation(perm_name)
    filter_reasons = []
    
    if trades_df.empty:
        return trades_df, filter_reasons
    
    # Create a copy to avoid modifying original
    filtered_df = trades_df.copy()
    
    if perm["filter_type"] == "range":
        param = perm["param"]
        min_val = perm["min"]
        max_val = perm["max"]
        
        if param in filtered_df.columns:
            # Apply range filter
            mask = (filtered_df[param] >= min_val) & (filtered_df[param] <= max_val)
            
            # Record reasons for excluded trades
            excluded_indices = filtered_df[~mask].index
            for idx in excluded_indices:
                value = filtered_df.loc[idx, param]
                reason = f"{param} = {value} not in range [{min_val}, {max_val}]"
                filter_reasons.append(reason)
            
            filtered_df = filtered_df[mask]
        else:
            print(f"⚠️  Column '{param}' not found in trades data")
    
    elif perm["filter_type"] == "categorical":
        param = perm["param"]
        value = perm["value"]
        
        if param in filtered_df.columns:
            # Apply categorical filter
            mask = filtered_df[param] == value
            
            # Record reasons for excluded trades
            excluded_indices = filtered_df[~mask].index
            for idx in excluded_indices:
                actual_value = filtered_df.loc[idx, param]
                reason = f"{param} = {actual_value} != {value}"
                filter_reasons.append(reason)
            
            filtered_df = filtered_df[mask]
        else:
            print(f"⚠️  Column '{param}' not found in trades data")
    
    elif perm["filter_type"] == "config_change":
        # Config changes don't filter trades directly, they change the backtest behavior
        # This would be handled by modifying CONFIG before running backtest
        print(f"ℹ️  Config change permutation '{perm_name}' - no direct trade filtering")
    
    return filtered_df, filter_reasons


def generate_comparison_report(baseline_df: pd.DataFrame, filtered_df: pd.DataFrame, 
                             perm_name: str, filter_reasons: List[str]) -> pd.DataFrame:
    """Generate a comparison report showing baseline vs filtered trades."""
    
    if baseline_df.empty:
        return pd.DataFrame()
    
    # Create comparison dataframe
    comparison_df = baseline_df.copy()
    
    # Add comparison columns
    comparison_df["in_baseline"] = True
    comparison_df["in_permutation"] = False
    comparison_df["filter_reason"] = ""
    
    # Mark trades that are in the filtered set
    if not filtered_df.empty:
        # Create a set of trade identifiers for faster lookup
        # Using entry_time_utc as unique identifier
        filtered_times = set(filtered_df["entry_time_utc"].values)
        
        for idx, row in comparison_df.iterrows():
            if row["entry_time_utc"] in filtered_times:
                comparison_df.loc[idx, "in_permutation"] = True
    
    # Add filter reasons for excluded trades
    reason_idx = 0
    for idx, row in comparison_df.iterrows():
        if not row["in_permutation"] and reason_idx < len(filter_reasons):
            comparison_df.loc[idx, "filter_reason"] = filter_reasons[reason_idx]
            reason_idx += 1
    
    # Add summary row at the top
    summary_row = {
        "entry_time_utc": f"SUMMARY_{perm_name}",
        "entry_model": f"Baseline: {len(baseline_df)}, Filtered: {len(filtered_df)}, Excluded: {len(baseline_df) - len(filtered_df)}",
        "side": "",
        "entry_price": "",
        "exit_price": "",
        "outcome": "",
        "in_baseline": True,
        "in_permutation": len(filtered_df) > 0,
        "filter_reason": f"Permutation: {perm_name}"
    }
    
    # Convert to DataFrame and prepend
    summary_df = pd.DataFrame([summary_row])
    comparison_df = pd.concat([summary_df, comparison_df], ignore_index=True)
    
    return comparison_df


def explain_filter_logic(perm_name: str) -> str:
    """Generate a human-readable explanation of what a filter does."""
    perm = get_permutation(perm_name)
    
    explanation = f"Filter: {perm_name}\n"
    explanation += f"Description: {perm['description']}\n"
    explanation += f"Type: {perm['filter_type']}\n"
    
    if perm["filter_type"] == "range":
        explanation += f"Parameter: {perm['param']}\n"
        explanation += f"Range: {perm['min']} to {perm['max']} (increment: {perm['increment']})\n"
        explanation += f"Default value: {perm['default_value']}\n"
        explanation += f"Logic: Keep trades where {perm['param']} is between {perm['min']} and {perm['max']}\n"
    
    elif perm["filter_type"] == "categorical":
        explanation += f"Parameter: {perm['param']}\n"
        explanation += f"Value: {perm['value']}\n"
        explanation += f"Logic: Keep trades where {perm['param']} equals {perm['value']}\n"
    
    elif perm["filter_type"] == "config_change":
        explanation += f"Parameter: {perm['param']}\n"
        explanation += f"Value: {perm['value']}\n"
        explanation += f"Logic: Changes backtest configuration - {perm['param']} = {perm['value']}\n"
    
    return explanation


def validate_all_permutations() -> Dict[str, bool]:
    """Validate all permutation definitions."""
    results = {}
    for perm_name in PERMUTATIONS.keys():
        results[perm_name] = validate_permutation_definition(perm_name)
    return results


if __name__ == "__main__":
    # Demo: validate all permutations
    print("Validating all permutations...")
    results = validate_all_permutations()
    
    valid_count = sum(results.values())
    total_count = len(results)
    
    print(f"\nValidation complete: {valid_count}/{total_count} permutations are valid")
    
    if valid_count < total_count:
        print("\nInvalid permutations:")
        for perm_name, is_valid in results.items():
            if not is_valid:
                print(f"  - {perm_name}")
