# permutations_examples.py
# ---------------------------------------------------------------------------
# EXAMPLE permutation definitions for reference
# These are the old-style permutations kept for reference
# ---------------------------------------------------------------------------

from typing import Dict, Any, List
from ..core.config import CONFIG

# =============================
# EXAMPLE PERMUTATION DEFINITIONS
# =============================

PERMUTATIONS_EXAMPLES = {
    # Baseline configuration (current main.py defaults)
    "baseline": {
        "description": "Current baseline configuration",
        "changes": {}
    },
    
    # Entry touch type variations
    "tap_only": {
        "description": "Only allow entries where bar taps gap but closes outside",
        "changes": {
            "entry_touch_type": "tap_only"
        }
    },
    
    "close_inside_only": {
        "description": "Only allow entries where bar closes inside the gap",
        "changes": {
            "entry_touch_type": "close_inside_only"
        }
    },
    
    # Gap interaction variations
    "no_gap_taps": {
        "description": "No prior bars touched the gap before entry",
        "changes": {
            "min_gap_taps": 0,
            "max_gap_taps": 0
        }
    },
    
    "one_gap_tap": {
        "description": "Exactly one prior bar touched the gap",
        "changes": {
            "min_gap_taps": 1,
            "max_gap_taps": 1
        }
    },
    
    "multiple_gap_taps": {
        "description": "Multiple bars touched the gap (2-3 taps)",
        "changes": {
            "min_gap_taps": 2,
            "max_gap_taps": 3
        }
    },
    
    # Midline penetration
    "penetrated_midline": {
        "description": "Entry bar penetrated beyond 50% of gap",
        "changes": {
            "penetrated_midline": True
        }
    },
    
    "no_midline_penetration": {
        "description": "Entry bar did NOT penetrate beyond 50% of gap",
        "changes": {
            "penetrated_midline": False
        }
    },
    
    # Time-based filters
    "first_five_minutes": {
        "description": "Only entries in first 5 minutes (09:30-09:35)",
        "changes": {
            "first_five_only": True
        }
    },
    
    "early_session": {
        "description": "Only entries in 09:30-09:45 time bucket",
        "changes": {
            "allowed_time_buckets": ["0930-0945"]
        }
    },
    
    "mid_session": {
        "description": "Only entries in 09:45-10:00 time bucket",
        "changes": {
            "allowed_time_buckets": ["0945-1000"]
        }
    },
    
    "late_session": {
        "description": "Only entries in 10:00-10:15 time bucket",
        "changes": {
            "allowed_time_buckets": ["1000-1015"]
        }
    },
    
    # Gap size filters
    "small_gaps": {
        "description": "Only small gaps (0.75-5 points)",
        "changes": {
            "gap_size_min_pts": 0.75,
            "gap_size_max_pts": 5.0
        }
    },
    
    "medium_gaps": {
        "description": "Only medium gaps (5-15 points)",
        "changes": {
            "gap_size_min_pts": 5.0,
            "gap_size_max_pts": 15.0
        }
    },
    
    "large_gaps": {
        "description": "Only large gaps (15+ points)",
        "changes": {
            "gap_size_min_pts": 15.0,
            "gap_size_max_pts": None
        }
    },
    
    # Delivery speed (bars to previous break)
    "fast_delivery": {
        "description": "Fast delivery - breaks previous bar within 2 bars",
        "changes": {
            "min_bars_to_prev_break": None,
            "max_bars_to_prev_break": 2
        }
    },
    
    "slow_delivery": {
        "description": "Slow delivery - takes 3+ bars to break previous",
        "changes": {
            "min_bars_to_prev_break": 3,
            "max_bars_to_prev_break": None
        }
    },
    
    # Risk management variations
    "tight_stops": {
        "description": "Tighter stops (10 points)",
        "changes": {
            "points_tp": 10.0,
            "points_sl": 10.0
        }
    },
    
    "wide_stops": {
        "description": "Wider stops (30 points)",
        "changes": {
            "points_tp": 30.0,
            "points_sl": 30.0
        }
    },
    
    # Model-specific variations
    "ifvg_only": {
        "description": "Only iFVG model",
        "changes": {
            "models_to_eval": ["fvg_ifvg"]
        }
    },
    
    "bos_only": {
        "description": "Only BOS model",
        "changes": {
            "models_to_eval": ["fvg_bos"]
        }
    },
    
    "no_fvg_only": {
        "description": "Only no-FVG model",
        "changes": {
            "models_to_eval": ["fvg_no_fvg"]
        }
    },
    
    # Combined scenarios (more complex)
    "tap_only_first_five": {
        "description": "Tap-only entries in first 5 minutes",
        "changes": {
            "entry_touch_type": "tap_only",
            "first_five_only": True
        }
    },
    
    "small_gaps_fast_delivery": {
        "description": "Small gaps with fast delivery",
        "changes": {
            "gap_size_min_pts": 0.75,
            "gap_size_max_pts": 5.0,
            "max_bars_to_prev_break": 2
        }
    },
    
    "early_session_tight_stops": {
        "description": "Early session with tight stops",
        "changes": {
            "allowed_time_buckets": ["0930-0945"],
            "points_tp": 10.0,
            "points_sl": 10.0
        }
    }
}


def get_example_permutation(name: str) -> Dict[str, Any]:
    """Get a specific example permutation by name."""
    if name not in PERMUTATIONS_EXAMPLES:
        available = list(PERMUTATIONS_EXAMPLES.keys())
        raise ValueError(f"Unknown example permutation '{name}'. Available: {available}")
    
    return PERMUTATIONS_EXAMPLES[name]


def list_example_permutations() -> List[str]:
    """List all available example permutation names."""
    return list(PERMUTATIONS_EXAMPLES.keys())


if __name__ == "__main__":
    # Demo: list all example permutations
    print("Available example permutations:")
    for name in list_example_permutations():
        perm = PERMUTATIONS_EXAMPLES[name]
        print(f"  {name:25s} - {perm['description']}")
