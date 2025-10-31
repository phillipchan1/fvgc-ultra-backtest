"""
Generate test configurations for parameter sweep
"""
from typing import Dict, Any
import copy


def generate_test_config(param_set) -> Dict[str, Any]:
    """
    Generate a CONFIG dictionary for a specific parameter set.
    
    Args:
        param_set: ParameterSet with test parameters
    
    Returns:
        CONFIG dictionary with appropriate settings
    """
    from ..core.config import CONFIG
    
    # Start with base config
    config = copy.deepcopy(CONFIG)
    
    # Always test on full dataset
    config['test_period'] = 'full_dataset'
    
    # Set trade management strategy
    config['trade_management_strategy'] = param_set.trade_management
    
    # Set gap size filters (will be applied in entry models)
    if param_set.gap_size_range != "ALL":
        config['gap_size_filter'] = param_set.gap_size_range
    else:
        config['gap_size_filter'] = None
    
    # Set touch range filter (will be applied in entry models)
    if param_set.touch_range != "ALL":
        config['touch_range_filter'] = param_set.touch_range
    else:
        config['touch_range_filter'] = None
    
    # Entry model selection (handled post-backtest via filtering)
    config['entry_model_filter'] = param_set.entry_model
    
    # Gap closure filter (handled post-backtest)
    config['gap_closure_filter'] = param_set.gap_closure_filter
    
    # Time window filter (handled post-backtest)
    config['time_window_filter'] = param_set.time_window
    
    return config
