# permutations.py
# ---------------------------------------------------------------------------
# Clean permutation definitions for systematic testing
# ---------------------------------------------------------------------------

from typing import Dict, Any, List, Union
from ..core.config import CONFIG

# =============================
# PERMUTATION DEFINITIONS
# =============================

PERMUTATIONS = {
    # Gap size filters
    "small_gaps": {
        "description": "Filter for small gap sizes",
        "filter_type": "range",
        "param": "gap_size_pts",
        "min": 0.75,
        "max": 5.0,
        "increment": 0.25,
        "default_value": 5.0
    },
    
    "medium_gaps": {
        "description": "Filter for medium gap sizes",
        "filter_type": "range",
        "param": "gap_size_pts",
        "min": 5.0,
        "max": 15.0,
        "increment": 1.0,
        "default_value": 15.0
    },
    
    "large_gaps": {
        "description": "Filter for large gap sizes",
        "filter_type": "range",
        "param": "gap_size_pts",
        "min": 15.0,
        "max": 40.0,
        "increment": 2.0,
        "default_value": 40.0
    },
    
    # Entry touch types
    "tap_only": {
        "description": "Only entries that tap gap without closing inside",
        "filter_type": "categorical",
        "param": "entry_touch_type",
        "value": "tap_only"
    },
    
    "close_inside_only": {
        "description": "Only entries that close inside the gap",
        "filter_type": "categorical",
        "param": "entry_touch_type",
        "value": "close_inside_only"
    },
    
    # Gap tap counts
    "no_gap_taps": {
        "description": "No prior bars touched the gap",
        "filter_type": "range",
        "param": "gap_taps_before_entry",
        "min": 0,
        "max": 0,
        "increment": 1,
        "default_value": 0
    },
    
    "one_gap_tap": {
        "description": "Exactly one prior bar touched the gap",
        "filter_type": "range",
        "param": "gap_taps_before_entry",
        "min": 1,
        "max": 1,
        "increment": 1,
        "default_value": 1
    },
    
    "multiple_gap_taps": {
        "description": "Multiple bars touched the gap",
        "filter_type": "range",
        "param": "gap_taps_before_entry",
        "min": 2,
        "max": 5,
        "increment": 1,
        "default_value": 3
    },
    
    # Midline penetration
    "penetrated_midline": {
        "description": "Entry bar penetrated beyond 50% of gap",
        "filter_type": "categorical",
        "param": "penetrated_midline",
        "value": True
    },
    
    "no_midline_penetration": {
        "description": "Entry bar did NOT penetrate beyond 50% of gap",
        "filter_type": "categorical",
        "param": "penetrated_midline",
        "value": False
    },
    
    # Time-based filters
    "first_five_minutes": {
        "description": "Only entries in first 5 minutes (09:30-09:35)",
        "filter_type": "categorical",
        "param": "first_five",
        "value": True
    },
    
    "early_session": {
        "description": "Only entries in 09:30-09:45 time bucket",
        "filter_type": "categorical",
        "param": "time_bucket",
        "value": "0930-0945"
    },
    
    "mid_session": {
        "description": "Only entries in 09:45-10:00 time bucket",
        "filter_type": "categorical",
        "param": "time_bucket",
        "value": "0945-1000"
    },
    
    "late_session": {
        "description": "Only entries in 10:00-10:15 time bucket",
        "filter_type": "categorical",
        "param": "time_bucket",
        "value": "1000-1015"
    },
    
    # Delivery speed
    "fast_delivery": {
        "description": "Fast delivery - breaks previous bar within 2 bars",
        "filter_type": "range",
        "param": "bars_to_prev_break",
        "min": 0,
        "max": 2,
        "increment": 1,
        "default_value": 2
    },
    
    "slow_delivery": {
        "description": "Slow delivery - takes 3+ bars to break previous",
        "filter_type": "range",
        "param": "bars_to_prev_break",
        "min": 3,
        "max": 10,
        "increment": 1,
        "default_value": 5
    },
    
    # Risk management
    "tight_stops": {
        "description": "Tighter stops (10 points)",
        "filter_type": "config_change",
        "param": "points_tp",
        "value": 10.0,
        "secondary_param": "points_sl",
        "secondary_value": 10.0
    },
    
    "wide_stops": {
        "description": "Wider stops (30 points)",
        "filter_type": "config_change",
        "param": "points_tp",
        "value": 30.0,
        "secondary_param": "points_sl",
        "secondary_value": 30.0
    },
    
    # Model-specific
    "ifvg_only": {
        "description": "Only iFVG model",
        "filter_type": "config_change",
        "param": "models_to_eval",
        "value": ["fvg_ifvg"]
    },
    
    "bos_only": {
        "description": "Only BOS model",
        "filter_type": "config_change",
        "param": "models_to_eval",
        "value": ["fvg_bos"]
    },
    
    "no_fvg_only": {
        "description": "Only no-FVG model",
        "filter_type": "config_change",
        "param": "models_to_eval",
        "value": ["fvg_no_fvg"]
    }
}


def get_permutation(name: str) -> Dict[str, Any]:
    """Get a specific permutation by name."""
    if name not in PERMUTATIONS:
        available = list(PERMUTATIONS.keys())
        raise ValueError(f"Unknown permutation '{name}'. Available: {available}")
    
    return PERMUTATIONS[name]


def list_permutations() -> List[str]:
    """List all available permutation names."""
    return list(PERMUTATIONS.keys())


def get_permutations_by_type(filter_type: str) -> List[str]:
    """Get permutations by filter type."""
    return [name for name, perm in PERMUTATIONS.items() if perm["filter_type"] == filter_type]


def print_permutation_info(name: str):
    """Print information about a permutation."""
    perm = get_permutation(name)
    print(f"\n=== Permutation: {name} ===")
    print(f"Description: {perm['description']}")
    print(f"Filter Type: {perm['filter_type']}")
    print(f"Parameter: {perm['param']}")
    
    if perm["filter_type"] == "range":
        print(f"Range: {perm['min']} - {perm['max']} (increment: {perm['increment']})")
        print(f"Default Value: {perm['default_value']}")
    elif perm["filter_type"] == "categorical":
        print(f"Value: {perm['value']}")
    elif perm["filter_type"] == "config_change":
        print(f"Value: {perm['value']}")
        if "secondary_param" in perm:
            print(f"Secondary Parameter: {perm['secondary_param']} = {perm['secondary_value']}")
    print()


if __name__ == "__main__":
    # Demo: list all permutations
    print("Available permutations:")
    for name in list_permutations():
        perm = PERMUTATIONS[name]
        print(f"  {name:25s} - {perm['description']} ({perm['filter_type']})")