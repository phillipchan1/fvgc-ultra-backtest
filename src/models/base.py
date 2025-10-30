# base.py
# ---------------------------------------------------------------------------
# Base classes and interfaces for entry models
# ---------------------------------------------------------------------------

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List
import pandas as pd
from ..core.fvg_detection import FVG


@dataclass
class TradeSignal:
    """Represents a trade entry signal."""
    entry_time: pd.Timestamp
    entry_price: float
    direction: str  # 'long' or 'short'
    entry_model: str  # Name of the model that generated this signal
    fvg_id: int  # ID of the FVG this entry is based on
    fvg_lower: float
    fvg_upper: float
    
    # Metadata for analysis
    fvg_direction: str  # 'bullish' or 'bearish'
    fvg_size_pts: float


class EntryModel(ABC):
    """Base class for entry models."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this entry model."""
        pass
    
    @abstractmethod
    def evaluate(
        self,
        fvg: FVG,
        active_fvgs: List[FVG],
        current_bar: pd.Series,
        bar_index: int,
        dataframe: pd.DataFrame
    ) -> Optional[TradeSignal]:
        """
        Evaluate if this entry model generates a trade signal.
        
        Args:
            fvg: The FVG being evaluated for entry
            active_fvgs: List of all currently active FVGs
            current_bar: Current bar data (pandas Series)
            bar_index: Index of current bar in dataframe
            dataframe: Full dataframe for lookback/lookahead
            
        Returns:
            TradeSignal if entry condition met, None otherwise
        """
        pass

