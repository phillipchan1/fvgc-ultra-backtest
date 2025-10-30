# Technical Implementation Guide

## FVG + noFVG Setup (30s Timeframe) - Code-Ready Specification

### Setup Overview

**Name:** Fair Value Gap Continuation with No Fair Value Gap (Bread and Butter Setup)

**Timeframe:** 30 seconds

**Probability:** High

**Type:** Continuation model (bidirectional)

---

### Step 1: Identify Fair Value Gap (FVG) – Bullish or Bearish#### Bullish FVG (For Long Entries)

**FVG Definition:**

- **Candle Count:** Exactly 3 candles required
- **Gap Calculation:**
    - `gap_high = candle[1].high` (first candle's high)
    - `gap_low = candle[3].low` (third candle's low)
    - `gap_exists = gap_high < gap_low` (no overlap between wicks)

**FVG Box Coordinates:**

- `top = candle[3].low`
- `bottom = candle[1].high`
- Store FVG as: `{top, bottom, candle_index, direction: "bullish", mitigated: false}`

**Bullish FVG Requirements:**

- Candle 2 (middle candle) shows strong upward displacement
- Typically large body relative to surrounding candles
- No wick overlap between candle 1 high and candle 3 low

---

### Bearish FVG (For Short Entries)

**FVG Definition:**

- **Candle Count:** Exactly 3 candles required
- **Gap Calculation:**
    - `gap_low = candle[1].low` (first candle's low)
    - `gap_high = candle[3].high` (third candle's high)
    - `gap_exists = gap_low > gap_high` (no overlap between wicks)

**FVG Box Coordinates:**

- `top = candle[1].low`
- `bottom = candle[3].high`
- Store FVG as: `{top, bottom, candle_index, direction: "bearish", mitigated: false}`

**Bearish FVG Requirements:**

- Candle 2 (middle candle) shows strong downward displacement
- Typically large body relative to surrounding candles
- No wick overlap between candle 1 low and candle 3 high

---

### Step 2: Identify Swing Point Target

### For Bullish Setups (Longs)

**Swing High Definition:**

- Local high formed **after** the bullish FVG
- Must be a pivot high: `high[n] > high[n-1] AND high[n] > high[n+1]`
- Minimum lookback: 3 candles on each side for 30s chart
- Store as: `swing_high = price_level`

**Selection Criteria:**

- Use the **nearest obvious swing high** above current price
- Must be clearly visible structure
- Avoid micro swings (use pivot strength filter if coding)

### For Bearish Setups (Shorts)

**Swing Low Definition:**

- Local low formed **after** the bearish FVG
- Must be a pivot low: `low[n] < low[n-1] AND low[n] < low[n+1]`
- Minimum lookback: 3 candles on each side for 30s chart
- Store as: `swing_low = price_level`

**Selection Criteria:**

- Use the **nearest obvious swing low** below current price
- Must be clearly visible structure
- Avoid micro swings (use pivot strength filter if coding)

---

### Step 3: Define the "Leg" Zone

### For Bullish Setups (Longs)

**Leg Definition:**

- **Start Point:** Lowest low between FVG formation and swing point
    - `leg_low = min(low[i] for i in range(fvg_end_index, swing_high_index))`
- **End Point:** Swing high identified in Step 2
    - `leg_high = swing_high`

**Leg Box Coordinates:**

- `top = leg_high`
- `bottom = leg_low`
- `left_boundary = candle_index_at_leg_start`
- `right_boundary = candle_index_at_swing_high`

### For Bearish Setups (Shorts)

**Leg Definition:**

- **Start Point:** Highest high between FVG formation and swing point
    - `leg_high = max(high[i] for i in range(fvg_end_index, swing_low_index))`
- **End Point:** Swing low identified in Step 2
    - `leg_low = swing_low`

**Leg Box Coordinates:**

- `top = leg_high`
- `bottom = leg_low`
- `left_boundary = candle_index_at_leg_start`
- `right_boundary = candle_index_at_swing_low`

---

### Step 4: Scan for Conflicting FVGs in Leg Zone

### For Bullish Setups – Scan for Bearish FVGs

**Bearish FVG Definition:**

- **Candle Count:** Exactly 3 candles
- **Gap Calculation:**
    - `gap_low_bearish = candle[1].low` (first candle's low)
    - `gap_high_bearish = candle[3].high` (third candle's high)
    - `bearish_gap_exists = gap_low_bearish > gap_high_bearish`

**Conflict Detection:**

```jsx
FOR each 3-candle sequence within leg zone:
    IF bearish FVG exists:
        IF (bearish_[fvg.top](http://fvg.top) >= leg_low) AND (bearish_fvg.bottom <= leg_high):
            RETURN INVALID  // Conflict found
        END IF
    END IF
END FOR
```

**Result:** If **any** bearish FVG exists within the leg zone → **INVALID**

### For Bearish Setups – Scan for Bullish FVGs

**Bullish FVG Definition:**

- **Candle Count:** Exactly 3 candles
- **Gap Calculation:**
    - `gap_high_bullish = candle[1].high` (first candle's high)
    - `gap_low_bullish = candle[3].low` (third candle's low)
    - `bullish_gap_exists = gap_high_bullish < gap_low_bullish`

**Conflict Detection:**

```jsx
FOR each 3-candle sequence within leg zone:
    IF bullish FVG exists:
        IF (bullish_fvg.bottom <= leg_high) AND (bullish_[fvg.top](http://fvg.top) >= leg_low):
            RETURN INVALID  // Conflict found
        END IF
    END IF
END FOR
```

**Result:** If **any** bullish FVG exists within the leg zone → **INVALID**

---

### Step 5: Wait for Entry Candle

### For Bullish Setups (Longs)

**Entry Candle Criteria:**

1. **Closure Rule:**
    - `current_candle.close > previous_candle.high`
    - This confirms bullish continuation intent
2. **Distance Rule (30s Chart):**
    
    ```jsx
    distance = current_candle.close - previous_candle.high
    IF distance > 7.5:
        RETURN INVALID_ENTRY
    END IF
    ```
    
    - **Maximum allowed:** 7.5 points
    - Measure from previous candle's **high** (not close) to current candle's **close**
3. **No Equal Highs:**
    
    ```jsx
    IF abs(current_candle.high - swing_high) < 0.5:
        RETURN INVALID_ENTRY
    END IF
    ```
    
4. **No Swing Point Sweep:**
    - `IF current_candle.high > swing_high: RETURN INVALID_ENTRY`
    - Entry must occur **before** swing point is reached
5. **No Body Close Through Swing:**
    
    ```jsx
    IF current_candle.close > swing_high:
        RETURN INVALID_ENTRY
    END IF
    ```
    
    - Wick can touch/exceed swing high
    - **Body close** must remain below swing high

### For Bearish Setups (Shorts)

**Entry Candle Criteria:**

1. **Closure Rule:**
    - `current_candle.close < previous_candle.low`
    - This confirms bearish continuation intent
2. **Distance Rule (30s Chart):**
    
    ```jsx
    distance = previous_candle.low - current_candle.close
    IF distance > 7.5:
        RETURN INVALID_ENTRY
    END IF
    ```
    
    - **Maximum allowed:** 7.5 points
    - Measure from previous candle's **low** (not close) to current candle's **close**
3. **No Equal Lows:**
    
    ```jsx
    IF abs(current_candle.low - swing_low) < 0.5:
        RETURN INVALID_ENTRY
    END IF
    ```
    
4. **No Swing Point Sweep:**
    - `IF current_candle.low < swing_low: RETURN INVALID_ENTRY`
    - Entry must occur **before** swing point is reached
5. **No Body Close Through Swing:**
    
    ```jsx
    IF current_candle.close < swing_low:
        RETURN INVALID_ENTRY
    END IF
    ```
    
    - Wick can touch/exceed swing low
    - **Body close** must remain above swing low

---

### Step 6: Entry Execution

### For Bullish Setups (Longs)

**Entry Trigger:**

- **Type:** Market order at candle close (BUY)
- **Timing:** Execute on close of candle that meets all Step 5 criteria
- **Entry Price:** `entry_price = current_candle.close`

**Alternative (Aggressive):**

- If candle is pushing through previous high during formation, can enter before close
- Risk: Candle may close back inside, invalidating setup

### For Bearish Setups (Shorts)

**Entry Trigger:**

- **Type:** Market order at candle close (SELL)
- **Timing:** Execute on close of candle that meets all Step 5 criteria
- **Entry Price:** `entry_price = current_candle.close`

**Alternative (Aggressive):**

- If candle is pushing through previous low during formation, can enter before close
- Risk: Candle may close back inside, invalidating setup

---

### Step 7: Stop Loss Placement

### For Bullish Setups (Longs)

**Stop Loss Rules:**

```jsx
sl_price = entry_price - 20.0  // 20 points below entry
```

**Validation:**

- `sl_price` should be below the low of the entry candle
- `sl_price` should ideally be below the FVG low
- Never place SL above the previous candle's low

### For Bearish Setups (Shorts)

**Stop Loss Rules:**

```jsx
sl_price = entry_price + 20.0  // 20 points above entry
```

**Validation:**

- `sl_price` should be above the high of the entry candle
- `sl_price` should ideally be above the FVG high
- Never place SL below the previous candle's high

---

### Step 8: Take Profit Target

### For Bullish Setups (Longs)

**Primary Target:**

```jsx
tp_price = entry_price + 20.0  // 20 points above entry (1:1 RR)
```

**Alternative Target:**

```jsx
tp_price = swing_high  // Use swing point as target
```

**Dynamic Management:**

- **Swing Point Reached:** Move SL to break even
- **Strong momentum:** Trail stop or partial profit at swing high, let runner continue

### For Bearish Setups (Shorts)

**Primary Target:**

```jsx
tp_price = entry_price - 20.0  // 20 points below entry (1:1 RR)
```

**Alternative Target:**

```jsx
tp_price = swing_low  // Use swing point as target
```

**Dynamic Management:**

- **Swing Point Reached:** Move SL to break even
- **Strong momentum:** Trail stop or partial profit at swing low, let runner continue

---

### Complete Entry Checklist (Boolean Logic)

### Bullish Setup Validation

```jsx
FUNCTION is_valid_bullish_fvg_no_fvg_setup():
    
    // 1. Valid Bullish FVG exists
    IF NOT bullish_fvg_exists:
        RETURN FALSE
    
    // 2. Swing high identified above price
    IF NOT swing_high_exists:
        RETURN FALSE
    
    // 3. Define leg zone from FVG to swing
    leg_low = get_lowest_low_in_range(fvg_end, swing_high_index)
    leg_high = swing_high
    
    // 4. NO bearish FVGs in leg zone
    IF any_bearish_fvg_in_zone(leg_low, leg_high):
        RETURN FALSE
    
    // 5. Entry candle closes above previous high
    IF current_close <= previous_high:
        RETURN FALSE
    
    // 6. Close distance <= 7.5 points
    distance = current_close - previous_high
    IF distance > 7.5:
        RETURN FALSE
    
    // 7. No equal highs
    IF abs(current_high - swing_high) < 0.5:
        RETURN FALSE
    
    // 8. No swing point sweep
    IF current_high > swing_high:
        RETURN FALSE
    
    // 9. No body close through swing
    IF current_close > swing_high:
        RETURN FALSE
    
    // All conditions met
    RETURN TRUE
    
END FUNCTION
```

### Bearish Setup Validation

```jsx
FUNCTION is_valid_bearish_fvg_no_fvg_setup():
    
    // 1. Valid Bearish FVG exists
    IF NOT bearish_fvg_exists:
        RETURN FALSE
    
    // 2. Swing low identified below price
    IF NOT swing_low_exists:
        RETURN FALSE
    
    // 3. Define leg zone from FVG to swing
    leg_high = get_highest_high_in_range(fvg_end, swing_low_index)
    leg_low = swing_low
    
    // 4. NO bullish FVGs in leg zone
    IF any_bullish_fvg_in_zone(leg_low, leg_high):
        RETURN FALSE
    
    // 5. Entry candle closes below previous low
    IF current_close >= previous_low:
        RETURN FALSE
    
    // 6. Close distance <= 7.5 points
    distance = previous_low - current_close
    IF distance > 7.5:
        RETURN FALSE
    
    // 7. No equal lows
    IF abs(current_low - swing_low) < 0.5:
        RETURN FALSE
    
    // 8. No swing point sweep
    IF current_low < swing_low:
        RETURN FALSE
    
    // 9. No body close through swing
    IF current_close < swing_low:
        RETURN FALSE
    
    // All conditions met
    RETURN TRUE
    
END FUNCTION
```

---

### Execution Parameters (30s Chart)

| Parameter | Bullish Value | Bearish Value | Unit |
| --- | --- | --- | --- |
| Timeframe | 30 | 30 | seconds |
| FVG Candle Count | 3 | 3 | candles |
| Max Close Distance | 7.5 | 7.5 | points |
| Stop Loss | -20.0 (below) | +20.0 (above) | points |
| Take Profit | +20.0 (above) | -20.0 (below) | points |
| Equal High/Low Tolerance | 0.5 | 0.5 | points |
| Pivot Strength | 3 | 3 | candles (each side) |

---

### Invalidation Scenarios

### Bullish Setup Invalidation

**Immediate Invalidation:**

1. Bearish FVG detected in leg zone
2. Entry candle closes >7.5 pts above previous high
3. Equal high formed with swing point
4. Swing high swept before entry
5. Body closes through swing high

**Post-Entry Invalidation:**

1. Price closes below previous candle low after entry
2. Stop loss hit (20 points below entry)
3. Bearish structure break below entry zone

### Bearish Setup Invalidation

**Immediate Invalidation:**

1. Bullish FVG detected in leg zone
2. Entry candle closes >7.5 pts below previous low
3. Equal low formed with swing point
4. Swing low swept before entry
5. Body closes through swing low

**Post-Entry Invalidation:**

1. Price closes above previous candle high after entry
2. Stop loss hit (20 points above entry)
3. Bullish structure break above entry zone

---

### Visual Confirmation (For Manual Review)

### Bullish Setup "Two Feet Test"

Stand 2 feet from screen and confirm:

- ✅ Clean bullish FVG gap (candle 1 high < candle 3 low, no wick overlap)
- ✅ Clear path from FVG to swing high (no bearish gaps)
- ✅ Entry candle closes tight to previous high (≤7.5 pts)
- ✅ Swing high clearly above entry

**If any element is unclear or "messy" → SKIP TRADE**

### Bearish Setup "Two Feet Test"

Stand 2 feet from screen and confirm:

- ✅ Clean bearish FVG gap (candle 1 low > candle 3 high, no wick overlap)
- ✅ Clear path from FVG to swing low (no bullish gaps)
- ✅ Entry candle closes tight to previous low (≤7.5 pts)
- ✅ Swing low clearly below entry

**If any element is unclear or "messy" → SKIP TRADE**

---

### Code Implementation Notes

**Data Structure for FVG:**

```python
class FVG:
    def __init__(self, top, bottom, index, direction):
        [self.top](http://self.top) = top
        self.bottom = bottom
        self.index = index
        self.direction = direction  # 'bullish' or 'bearish'
        self.mitigated = False
```

**Distance Calculation (Bullish):**

```python
def calculate_bullish_close_distance(current_candle, previous_candle):
    return current_candle['close'] - previous_candle['high']
```

**Distance Calculation (Bearish):**

```python
def calculate_bearish_close_distance(current_candle, previous_candle):
    return previous_candle['low'] - current_candle['close']
```

**Leg Zone Scanner (Bullish - Scan for Bearish FVGs):**

```python
def scan_for_bearish_fvgs_in_bullish_leg(candles, start_idx, end_idx, leg_low, leg_high):
    for i in range(start_idx, end_idx - 2):
        # Check for 3-candle bearish FVG
        gap_low = candles[i]['low']
        gap_high = candles[i + 2]['high']
        
        if gap_low > gap_high:  # Bearish gap exists
            # Check if gap overlaps with leg zone
            if (gap_high >= leg_low) and (gap_low <= leg_high):
                return True  # Conflict found
    
    return False  # No conflicts
```

**Leg Zone Scanner (Bearish - Scan for Bullish FVGs):**

```python
def scan_for_bullish_fvgs_in_bearish_leg(candles, start_idx, end_idx, leg_low, leg_high):
    for i in range(start_idx, end_idx - 2):
        # Check for 3-candle bullish FVG
        gap_high = candles[i]['high']
        gap_low = candles[i + 2]['low']
        
        if gap_high < gap_low:  # Bullish gap exists
            # Check if gap overlaps with leg zone
            if (gap_low <= leg_high) and (gap_high >= leg_low):
                return True  # Conflict found
    
    return False  # No conflicts
```

---

### Example Trade Flows

### Bullish Trade Example

**T0:** Bullish FVG forms (3 candles)

**T1:** Swing high identified at +37 points

**T2:** Scan leg zone → No bearish FVGs detected ✅

**T3:** Price retraces into FVG, respects it

**T4:** Entry candle closes 4.2 pts above previous high ✅

**T5:** Enter long at close

**T6:** SL = entry - 20, TP = entry + 20

**T7:** Price runs to TP in 6 candles

**Result:** +20 points, 1:1 RR

### Bearish Trade Example

**T0:** Bearish FVG forms (3 candles)

**T1:** Swing low identified at -37 points

**T2:** Scan leg zone → No bullish FVGs detected ✅

**T3:** Price retraces into FVG, respects it

**T4:** Entry candle closes 5.1 pts below previous low ✅

**T5:** Enter short at close

**T6:** SL = entry + 20, TP = entry - 20

**T7:** Price drops to TP in 8 candles

**Result:** +20 points, 1:1 RR

---

### Frequency and Session Timing

**Optimal Windows:**

- 9:45–10:15 AM EST (primary macro)
- 10:45–11:15 AM EST (secondary macro)

**Expected Frequency:**

- 2-4 setups per week during macro windows
- May appear outside macros but with lower probability

**Session Context:**

- Works best during NY AM session (9:30 AM–11:15 AM EST)
- Avoid during low volume periods or after 11:15 AM
- Avoid during low volume periods or after 11:15 AM

---

### Trade Management Rules

### Rule 1: One Trade Per FVG

**Problem:** System may attempt multiple entries on the same FVG if price returns to it repeatedly.

**Solution:**

```python
class FVG:
    def __init__(self, top, bottom, index, direction):
        [self.top](http://self.top) = top
        self.bottom = bottom
        self.index = index
        self.direction = direction  # 'bullish' or 'bearish'
        self.mitigated = False
        [self.trade](http://self.trade)_taken = False  # NEW: Track if trade was already taken
        self.entry_candle_index = None  # Track when trade was entered
```

**Implementation:**

- When entry criteria are met and trade is executed, set [`fvg.trade](http://fvg.trade)_taken = True`
- Mark `fvg.entry_candle_index = current_candle_index`
- **Skip this FVG** for all future entry checks
- This prevents multiple trades on the same gap

**Example:**

```python
def can_trade_fvg(fvg):
    if [fvg.trade](http://fvg.trade)_taken:
        return False  # Already traded this gap
    return True

# After taking entry:
[fvg.trade](http://fvg.trade)_taken = True
fvg.entry_candle_index = current_index
```

---

### Rule 2: Multiple Stacked FVGs (Gap Resolution)

**Problem:** Price may retrace into multiple stacked bullish FVGs simultaneously. Which one should trigger entry?

**Solution: Use the LOWEST gap (for longs) or HIGHEST gap (for shorts)**

**For Bullish Setups (Longs):**

```python
def select_entry_fvg_for_long(active_fvgs, current_price):
    # Filter: Only untapped FVGs that haven't been traded
    valid_fvgs = [fvg for fvg in active_fvgs 
                  if fvg.direction == 'bullish' 
                  and not [fvg.trade](http://fvg.trade)_taken
                  and current_price <= [fvg.top](http://fvg.top)]  # Price is at or below gap
    
    if not valid_fvgs:
        return None
    
    # Select the LOWEST gap (best risk/reward)
    return min(valid_fvgs, key=lambda fvg: fvg.bottom)
```

**For Bearish Setups (Shorts):**

```python
def select_entry_fvg_for_short(active_fvgs, current_price):
    # Filter: Only untapped FVGs that haven't been traded
    valid_fvgs = [fvg for fvg in active_fvgs 
                  if fvg.direction == 'bearish' 
                  and not [fvg.trade](http://fvg.trade)_taken
                  and current_price >= fvg.bottom]  # Price is at or above gap
    
    if not valid_fvgs:
        return None
    
    # Select the HIGHEST gap (best risk/reward)
    return max(valid_fvgs, key=lambda fvg: [fvg.top](http://fvg.top))
```

**Alternative: Scale to Higher Timeframe (Setup #4)**

If 3+ FVGs are stacked on 30s chart:

1. Scale up to 1m, then 2m, then 3m
2. Find the timeframe where gaps collapse into a **single FVG**
3. Wait for price to tap that **singular higher-timeframe FVG**
4. Then scale back down to 30s for precise entry

This is covered in detail in **Setup #4: Scaled-Down Gap Resolution Setup**.

---

### Rule 3: Maximum Touches Before FVG Becomes Invalid

**Problem:** If price taps into an FVG 10+ times without giving entry signal, the gap loses its effectiveness.

**Solution: Maximum 3 touches before invalidation**

**Implementation:**

```python
class FVG:
    def __init__(self, top, bottom, index, direction):
        [self.top](http://self.top) = top
        self.bottom = bottom
        self.index = index
        self.direction = direction
        self.mitigated = False
        [self.trade](http://self.trade)_taken = False
        self.touch_count = 0  # NEW: Track number of touches
        self.max_touches = 3   # Maximum allowed touches
        [self.is](http://self.is)_valid = True   # NEW: Validity flag
```

**Touch Detection:**

```python
def check_fvg_touch(fvg, candle):
    # For bullish FVG
    if fvg.direction == 'bullish':
        # Check if candle wick touches gap
        if candle['low'] <= [fvg.top](http://fvg.top) and candle['low'] >= fvg.bottom:
            fvg.touch_count += 1
            
            # Invalidate if exceeded max touches
            if fvg.touch_count > fvg.max_touches:
                [fvg.is](http://fvg.is)_valid = False
                return False
    
    # For bearish FVG
    elif fvg.direction == 'bearish':
        # Check if candle wick touches gap
        if candle['high'] >= fvg.bottom and candle['high'] <= [fvg.top](http://fvg.top):
            fvg.touch_count += 1
            
            # Invalidate if exceeded max touches
            if fvg.touch_count > fvg.max_touches:
                [fvg.is](http://fvg.is)_valid = False
                return False
    
    return True
```

**Entry Validation:**

```python
def is_fvg_valid_for_entry(fvg):
    if not [fvg.is](http://fvg.is)_valid:
        return False
    if [fvg.trade](http://fvg.trade)_taken:
        return False
    if fvg.touch_count > fvg.max_touches:
        return False
    return True
```

**Rationale:**

- **Touch 1**: Initial interaction - fresh gap
- **Touch 2**: Second test - still valid
- **Touch 3**: Third test - last chance
- **Touch 4+**: Gap is "overworked" and no longer reliable

**Exception:** If price **fully rebalances** the gap (closes through it completely), reset touch count or mark as inverted.

---

### Rule 4: FVG Age/Expiry

**Optional Enhancement:** Limit how many candles old an FVG can be before it expires.

**Recommended Maximum Age: 20-30 candles (30s TF)**

```python
class FVG:
    def __init__(self, top, bottom, index, direction):
        [self.top](http://self.top) = top
        self.bottom = bottom
        self.index = index
        self.direction = direction
        self.mitigated = False
        [self.trade](http://self.trade)_taken = False
        self.touch_count = 0
        self.max_touches = 3
        [self.is](http://self.is)_valid = True
        self.max_age_candles = 30  # NEW: Expiry setting

def check_fvg_age(fvg, current_candle_index):
    age = current_candle_index - fvg.index
    if age > fvg.max_age_candles:
        [fvg.is](http://fvg.is)_valid = False
        return False
    return True
```

**Rationale:** Gaps older than 10-15 minutes (30 candles on 30s TF) lose relevance in fast-moving markets.

---

### Complete FVG Validation Function

```python
def is_fvg_valid_for_entry(fvg, current_candle_index):
    """
    Complete validation check for FVG before allowing entry.
    Returns True if FVG is still valid for trading.
    """
    # Check 1: Already traded?
    if [fvg.trade](http://fvg.trade)_taken:
        return False
    
    # Check 2: Valid flag still true?
    if not [fvg.is](http://fvg.is)_valid:
        return False
    
    # Check 3: Too many touches?
    if fvg.touch_count > fvg.max_touches:
        [fvg.is](http://fvg.is)_valid = False
        return False
    
    # Check 4: Too old?
    age = current_candle_index - fvg.index
    if age > fvg.max_age_candles:
        [fvg.is](http://fvg.is)_valid = False
        return False
    
    # Check 5: Has it been mitigated/inverted?
    if fvg.mitigated:
        # Depending on your strategy, you may want to invalidate
        # OR allow entry on mitigated gaps (see Pattern #4)
        pass
    
    # All checks passed
    return True
```

---

### Summary: Trade Management Checklist

**Before Taking Entry:**

1. ✅ Verify FVG has **not been traded** (`trade_taken == False`)
2. ✅ Verify FVG **touch count ≤ 3** (`touch_count <= max_touches`)
3. ✅ Verify FVG **age ≤ 30 candles** (optional but recommended)
4. ✅ If multiple gaps exist, select **lowest (long)** or **highest (short)**
5. ✅ Verify FVG is **still valid** (`is_valid == True`)

**After Taking Entry:**

1. ✅ Mark FVG as traded: [`fvg.trade](http://fvg.trade)_taken = True`
2. ✅ Record entry candle: `fvg.entry_candle_index = current_index`
3. ✅ **Do not** take another trade on this FVG

**During Price Action:**

1. ✅ Track touches on each candle close
2. ✅ Invalidate FVG if `touch_count > 3`
3. ✅ Check age on each candle
4. ✅ Update validity flags appropriately

**Quick Reading – Key Points**

- **Setup Type:** Valid but **very low probability**
- **Definition:** A fair value gap continuation where the entry candle is the **first to reach an unmitigated FVG**
- **Why it’s risky:** The **first touch of an unmitigated FVG** often results in **rejection or reversal**, not continuation
- **Common mistake:** Traders see the entry signal (closure above prior high) and enter **without noticing** they’ve tapped into an unmitigated bearish FVG
- **Correct play:** Wait for either:
    - The gap to be mitigated **before** the continuation signal
    - **iFVG confirmation** instead
- **Avoid if:**
    - It’s the **first candle** to reach a bearish FVG
    - There’s a **conflict between bullish and bearish gaps**
    - No prior wick/interaction with the bearish FVG
- **Better setup:** Use the **same continuation logic** after mitigation or **combine with iFVG** confirmation

---

**Detailed Breakdown**

**Definition and Structure of the Setup**

This is a **valid but very low probability** continuation setup. It occurs when price **closes above a prior candle’s high**, showing a fair value gap continuation signal — but **enters an unmitigated FVG for the first time**. That unmitigated gap (bearish in this case) hasn’t been interacted with or absorbed by price yet.

**Why It’s Low Probability**

When price enters an unmitigated gap for the first time, there is typically **a surge of resting orders** being filled (often on the **opposing side** of your trade). This creates volatility and increases the likelihood that price **rejects the gap** rather than continues through it.

Traders often get “cooked” because they focus on the **bullish signal** (e.g., FVG continuation) and ignore the context — namely, the **unmitigated bearish FVG** they’re stepping into. That context suggests **price has a higher chance to reverse**.

**Correct Response to the Setup**

Avoid entering simply because there’s a continuation candle. You need one of the following:

- **Prior mitigation**: Price must **interact with the bearish FVG first** (wick, tap, or partial fill) **before** the candle that gives the entry signal
- **iFVG confirmation**: Use an inversion setup to strengthen the idea that price will deliver through the bearish FVG
- **Avoid first touch**: Never enter on the candle that **first touches** the unmitigated gap **and** provides the entry signal — that’s the trap

**Risk Elements to Check For**

- **Conflicting gaps**: If a bullish and bearish FVG exist in close proximity, be aware of the conflict. The bullish gap might be valid, but the bearish one might still overpower it.
- **Unconfirmed delivery**: Until a bearish gap is **used once**, you don’t know if price will respect or reject it. That unknown is the entire issue.
- **No iFVG = No confidence**: In the absence of a proper iFVG to back it up, this setup lacks structural conviction.

**Example Breakdown**

- On a 30-second chart, price closes above a previous high, respecting a bullish FVG. But this same candle is the **first to enter a bearish unmitigated FVG**. Result: price reverses and dumps.
- On the 1-minute chart, a very similar structure occurs. Price enters the gap for the first time **and** gives the bullish continuation signal. Result again: a reversal.

In both examples, **had the trader waited** for either the gap to be mitigated **before** the entry signal, or for a clear iFVG setup to form, they would’ve avoided a loss.

**Conclusion**

This pattern underscores a key ICT principle: **context matters more than signal**. The presence of an unmitigated gap — especially on the **first interaction** — invalidates the reliability of an otherwise clean continuation signal. This is a setup that is **best left alone unless paired with an iFVG or prior mitigation**.