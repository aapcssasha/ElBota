import requests
import csv
from io import StringIO
import os
import json  # For webhook payload
from datetime import datetime  # For timestamp in embed
from openai import OpenAI
from dotenv import load_dotenv
import pandas as pd
import mplfinance as mpf
from io import BytesIO
import re

# Load environment variables from .env file
load_dotenv()


# ============================================================================
# POSITION MANAGEMENT FUNCTIONS
# ============================================================================

def load_positions():
    """Load current position state from positions.json"""
    positions_file = "positions.json"

    # Create file if it doesn't exist
    if not os.path.exists(positions_file):
        default_state = {
            "current_position": {
                "status": "none",
                "entry_price": None,
                "entry_time": None,
                "stop_loss": None,
                "take_profit": None,
                "trade_id": None,
                "action": None
            },
            "last_signal": "hold",
            "trade_history": [],
            "paper_trading_balance": 10000.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0
        }
        with open(positions_file, 'w') as f:
            json.dump(default_state, f, indent=2)
        return default_state

    with open(positions_file, 'r') as f:
        return json.load(f)


def save_positions(positions_data):
    """Save position state to positions.json"""
    with open("positions.json", 'w') as f:
        json.dump(positions_data, f, indent=2)


def check_stop_target(positions_data, csv_data):
    """Check if stop-loss or take-profit has been hit by analyzing candle highs/lows

    Returns:
        tuple: (should_close, reason, exit_price) - reason is 'stop_hit', 'target_hit', or None
    """
    pos = positions_data["current_position"]

    if pos["status"] == "none":
        return False, None, None

    # Parse CSV data to get candles
    lines = csv_data.strip().split('\n')[1:]  # Skip header
    candles = []
    for line in lines:
        parts = line.split(',')
        candles.append({
            'timestamp': int(parts[0]),
            'high': float(parts[2]),
            'low': float(parts[3])
        })

    # Filter candles after entry_time
    from dateutil import parser
    entry_timestamp = int(parser.parse(pos["entry_time"]).timestamp())
    relevant_candles = [c for c in candles if c['timestamp'] >= entry_timestamp]

    # For LONG positions: check each candle chronologically
    if pos["status"] == "long":
        for candle in relevant_candles:
            # Check BOTH stop and target in the same candle (chronological order)
            # If target hit in this candle, return it
            if pos["take_profit"] and candle['high'] >= pos["take_profit"]:
                return True, "target_hit", pos["take_profit"]

            # If stop hit in this candle, return it
            if pos["stop_loss"] and candle['low'] <= pos["stop_loss"]:
                return True, "stop_hit", pos["stop_loss"]

    # For SHORT positions: check each candle chronologically
    elif pos["status"] == "short":
        for candle in relevant_candles:
            # Check BOTH stop and target in the same candle (chronological order)
            # If target hit in this candle, return it
            if pos["take_profit"] and candle['low'] <= pos["take_profit"]:
                return True, "target_hit", pos["take_profit"]

            # If stop hit in this candle, return it
            if pos["stop_loss"] and candle['high'] >= pos["stop_loss"]:
                return True, "stop_hit", pos["stop_loss"]

    return False, None, None


def execute_paper_trade(action, price, positions_data, stop_loss=None, take_profit=None):
    """Execute a paper trade (simulate, no real money)

    Returns:
        dict: Trade result with details
    """
    result = {"success": False, "message": "", "profit_loss": 0}

    if action == "open_long":
        positions_data["current_position"] = {
            "status": "long",
            "entry_price": price,
            "entry_time": datetime.now().isoformat(),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trade_id": f"paper_{int(datetime.now().timestamp())}",
            "action": "buy"
        }
        result["success"] = True
        result["message"] = f"🟢 OPENED LONG at ${price:,.2f}"

    elif action == "open_short":
        positions_data["current_position"] = {
            "status": "short",
            "entry_price": price,
            "entry_time": datetime.now().isoformat(),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trade_id": f"paper_{int(datetime.now().timestamp())}",
            "action": "sell"
        }
        result["success"] = True
        result["message"] = f"🔴 OPENED SHORT at ${price:,.2f}"

    elif action == "close_long":
        entry_price = positions_data["current_position"]["entry_price"]
        profit_loss = price - entry_price
        positions_data["paper_trading_balance"] += profit_loss
        positions_data["total_trades"] += 1

        if profit_loss > 0:
            positions_data["winning_trades"] += 1
            emoji = "✅"
        else:
            positions_data["losing_trades"] += 1
            emoji = "❌"

        # Add to history
        positions_data["trade_history"].append({
            "type": "long",
            "entry_price": entry_price,
            "exit_price": price,
            "profit_loss": profit_loss,
            "entry_time": positions_data["current_position"]["entry_time"],
            "exit_time": datetime.now().isoformat()
        })

        # Reset position
        positions_data["current_position"] = {
            "status": "none",
            "entry_price": None,
            "entry_time": None,
            "stop_loss": None,
            "take_profit": None,
            "trade_id": None,
            "action": None
        }

        result["success"] = True
        result["profit_loss"] = profit_loss
        result["message"] = f"{emoji} CLOSED LONG at ${price:,.2f} | P/L: ${profit_loss:+,.2f}"

    elif action == "close_short":
        entry_price = positions_data["current_position"]["entry_price"]
        profit_loss = entry_price - price  # Reversed for shorts
        positions_data["paper_trading_balance"] += profit_loss
        positions_data["total_trades"] += 1

        if profit_loss > 0:
            positions_data["winning_trades"] += 1
            emoji = "✅"
        else:
            positions_data["losing_trades"] += 1
            emoji = "❌"

        # Add to history
        positions_data["trade_history"].append({
            "type": "short",
            "entry_price": entry_price,
            "exit_price": price,
            "profit_loss": profit_loss,
            "entry_time": positions_data["current_position"]["entry_time"],
            "exit_time": datetime.now().isoformat()
        })

        # Reset position
        positions_data["current_position"] = {
            "status": "none",
            "entry_price": None,
            "entry_time": None,
            "stop_loss": None,
            "take_profit": None,
            "trade_id": None,
            "action": None
        }

        result["success"] = True
        result["profit_loss"] = profit_loss
        result["message"] = f"{emoji} CLOSED SHORT at ${price:,.2f} | P/L: ${profit_loss:+,.2f}"

    return result


def manage_positions(positions_data, trade_data, current_price, csv_data):
    """Manage positions based on current state and new signal

    Returns:
        list: List of trade results (messages to send to Discord)
    """
    results = []
    current_status = positions_data["current_position"]["status"]
    new_signal = trade_data.get("action", "hold") if trade_data else "hold"

    # Check if stop-loss or take-profit hit first (checks candle highs/lows)
    should_close, reason, exit_price = check_stop_target(positions_data, csv_data)
    if should_close:
        if current_status == "long":
            result = execute_paper_trade("close_long", exit_price, positions_data)
            result["message"] += f" ({reason.replace('_', ' ').title()})"
            results.append(result)
            current_status = "none"  # Update for next logic
        elif current_status == "short":
            result = execute_paper_trade("close_short", exit_price, positions_data)
            result["message"] += f" ({reason.replace('_', ' ').title()})"
            results.append(result)
            current_status = "none"

    # Position management logic
    if current_status == "none":
        if new_signal == "buy":
            # Validate trade levels before executing
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append({"success": False, "message": f"⚠️ Invalid trade levels: {error_msg}"})
            else:
                result = execute_paper_trade(
                    "open_long", current_price, positions_data,
                    trade_data.get("stop_loss"), trade_data.get("take_profit")
                )
                results.append(result)
        elif new_signal == "sell":
            # Validate trade levels before executing
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append({"success": False, "message": f"⚠️ Invalid trade levels: {error_msg}"})
            else:
                result = execute_paper_trade(
                    "open_short", current_price, positions_data,
                    trade_data.get("stop_loss"), trade_data.get("take_profit")
                )
                results.append(result)
        elif new_signal == "hold":
            results.append({"success": True, "message": "⚪ No position | Signal: HOLD"})

    elif current_status == "long":
        if new_signal == "buy":
            entry = positions_data["current_position"]["entry_price"]
            pl = current_price - entry
            results.append({"success": True, "message": f"✅ Holding LONG (Entry: ${entry:,.2f}, Current P/L: ${pl:+,.2f})"})
        elif new_signal == "sell":
            # Close long, open short
            result1 = execute_paper_trade("close_long", current_price, positions_data)
            results.append(result1)

            # Validate before opening short
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append({"success": False, "message": f"⚠️ Invalid trade levels: {error_msg}"})
            else:
                result2 = execute_paper_trade(
                    "open_short", current_price, positions_data,
                    trade_data.get("stop_loss"), trade_data.get("take_profit")
                )
                results.append(result2)
        elif new_signal == "hold":
            result = execute_paper_trade("close_long", current_price, positions_data)
            results.append(result)

    elif current_status == "short":
        if new_signal == "sell":
            entry = positions_data["current_position"]["entry_price"]
            pl = entry - current_price  # Reversed for shorts
            results.append({"success": True, "message": f"✅ Holding SHORT (Entry: ${entry:,.2f}, Current P/L: ${pl:+,.2f})"})
        elif new_signal == "buy":
            # Close short, open long
            result1 = execute_paper_trade("close_short", current_price, positions_data)
            results.append(result1)

            # Validate before opening long
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append({"success": False, "message": f"⚠️ Invalid trade levels: {error_msg}"})
            else:
                result2 = execute_paper_trade(
                    "open_long", current_price, positions_data,
                    trade_data.get("stop_loss"), trade_data.get("take_profit")
                )
                results.append(result2)
        elif new_signal == "hold":
            result = execute_paper_trade("close_short", current_price, positions_data)
            results.append(result)

    # Update last signal
    positions_data["last_signal"] = new_signal

    return results


def fetch_btc_data():
    """Fetch BTC/USD 1-minute candles from Coinbase Exchange API"""
    import time

    # Request last 61 minutes of data (to ensure we get 60 complete candles)
    # Coinbase API: end time is exclusive, so we need current time
    end_time = int(time.time())
    start_time = end_time - (61 * 60)  # 61 minutes ago

    url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60&start={start_time}&end={end_time}"
    response = requests.get(url)
    data = response.json()  # Returns array of candles

    # Coinbase returns newest first, reverse to get oldest first
    # Format: [timestamp, low, high, open, close, volume]
    data.reverse()

    # Take last 60 candles (most recent), convert to CSV
    recent = data[-60:] if len(data) >= 60 else data
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Open", "High", "Low", "Close", "Volume"])
    for candle in recent:
        ts = int(candle[0])  # Unix seconds
        open_price = candle[3]  # Open
        high = candle[2]        # High
        low = candle[1]         # Low
        close = candle[4]       # Close
        volume = candle[5]      # Volume
        writer.writerow([ts, open_price, high, low, close, volume])
    return output.getvalue()


def generate_chart(data, trade_data=None, trade_invalid=False):
    """Generate candlestick chart from OHLCV data and return as bytes

    Args:
        data: CSV string with OHLCV data
        trade_data: Dict with entry_price, stop_loss, take_profit (optional)
        trade_invalid: Boolean indicating if trade was rejected by validation
    """
    # Parse the data into a pandas DataFrame
    lines = data.strip().split('\n')[1:]  # Skip header
    candles = []
    for line in lines:
        parts = line.split(',')
        # Create UTC timestamp, convert to local time
        utc_time = pd.to_datetime(int(parts[0]), unit='s', utc=True)
        local_time = utc_time.tz_convert('America/New_York').tz_localize(None)  # Convert to ET and remove timezone
        candles.append({
            'timestamp': local_time,
            'open': float(parts[1]),
            'high': float(parts[2]),
            'low': float(parts[3]),
            'close': float(parts[4]),
            'volume': float(parts[5])
        })

    df = pd.DataFrame(candles)
    df.set_index('timestamp', inplace=True)
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']

    # Create custom style for professional look
    mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350',
                                edge='inherit',
                                wick={'up':'#26a69a', 'down':'#ef5350'},
                                volume='in')
    style = mpf.make_mpf_style(marketcolors=mc, gridstyle=':',
                                 y_on_right=False,
                                 facecolor='#1e1e1e',
                                 figcolor='#1e1e1e',
                                 edgecolor='#555555',
                                 gridcolor='#333333',
                                 rc={
                                     'axes.labelcolor': 'white',      # X and Y axis labels
                                     'xtick.color': 'white',          # X axis tick labels
                                     'ytick.color': 'white',          # Y axis tick labels
                                     'axes.titlecolor': 'white',      # Chart title
                                     'text.color': 'white'            # All text
                                 })

    # Add horizontal lines for entry, stop-loss, and take-profit
    hlines_dict = None
    if trade_data and trade_data.get('action') != 'hold':
        values = []
        colors = []
        linestyles = []
        linewidths = []

        if trade_data.get('entry_price'):
            values.append(trade_data['entry_price'])
            colors.append('#2196F3')  # Blue for entry
            linestyles.append('--')
            linewidths.append(1.5)

        if trade_data.get('stop_loss'):
            values.append(trade_data['stop_loss'])
            colors.append('#FF5252')  # Red for stop-loss
            linestyles.append('--')
            linewidths.append(1.5)

        if trade_data.get('take_profit'):
            values.append(trade_data['take_profit'])
            colors.append('#4CAF50')  # Green for take-profit
            linestyles.append('--')
            linewidths.append(1.5)

        if values:
            hlines_dict = dict(
                hlines=values,
                colors=colors,
                linestyle=linestyles,
                linewidths=linewidths,
                alpha=0.8
            )

    # Save to BytesIO instead of file
    buf = BytesIO()
    plot_kwargs = {
        'type': 'candle',
        'style': style,
        'volume': True,
        'title': 'BTC/USD 1min Chart (Last 60 min)',
        'returnfig': True  # Return figure object so we can add text
    }

    # Only add hlines if we have trade data
    if hlines_dict:
        plot_kwargs['hlines'] = hlines_dict

    fig, axes = mpf.plot(df, **plot_kwargs)

    # Add "INVALID TRADE" text overlay if trade was rejected
    if trade_invalid and trade_data and trade_data.get('action') != 'hold':
        # Add text to the main price chart (axes[0])
        ax = axes[0]
        # Position text at top-right of chart
        ax.text(0.98, 0.95, 'INVALID TRADE',
                transform=ax.transAxes,
                fontsize=16,
                fontweight='bold',
                color='#FF5252',  # Red
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#1e1e1e', edgecolor='#FF5252', linewidth=2),
                ha='right', va='top',
                zorder=1000)

    # Save figure to buffer
    fig.savefig(buf, dpi=150, bbox_inches='tight')
    buf.seek(0)
    return buf


def analyze_with_llm(csv_data):
    """Get trading analysis and structured trade data from ChatGPT

    Returns:
        tuple: (analysis_text, trade_data_dict)
    """
    # Initialize OpenAI client
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Get current price from latest candle
    lines = csv_data.strip().split('\n')
    latest_candle = lines[-1].split(',')
    current_price = float(latest_candle[4])  # Close price

    prompt = f"""You are a crypto TA expert specializing in SHORT-TERM scalping with STRONG technical levels. Analyze this BTC/USD 1m OHLCV data from the last 60 minutes:
{csv_data}

Current BTC price: ${current_price:,.2f}

🎯 ANALYSIS FRAMEWORK - Strategy Priority:

1. **TREND FOLLOWING WITH PULLBACK ENTRIES** (PRIMARY STRATEGY):
   - Identify clear trend: higher highs/lows (uptrend) OR lower highs/lows (downtrend)
   - Enter on pullbacks/bounces: 20-80% retracement of previous swing (flexible range)

   **IDEAL SETUP (highest confidence):**
   - **For UPTREND (BUY):** Price makes higher high → pulls back to/near previous high
     * Example: $50 → drops to $25 → rallies to new high $75 → pulls back to ~$50 (near previous high)
     * This combines: trend following + ~50% pullback + previous structure support
   - **For DOWNTREND (SELL):** Price makes lower low → bounces to/near previous low
     * Example: $50 → rallies to $75 → drops to new low $25 → bounces to ~$50 (near previous low)
     * This combines: trend following + ~50% bounce + previous structure resistance

   **ACCEPTABLE SETUPS (medium confidence):**
   - Any 20-80% retracement in a clear trend, even if not at previous structure
   - Closer to 40-60% range = higher confidence
   - Landing at previous high/low = bonus confidence boost

2. **FALSE BREAKOUT REVERSAL** (SECONDARY - use if detected):
   - Price breaks strong support/resistance → quickly reverses within 3-5 candles
   - Trade the reversal direction
   - Example: Break above resistance → drops back → SELL signal
   - Example: Break below support → bounces back → BUY signal

3. **SIGNIFICANT SUPPORT/RESISTANCE ZONES** (FALLBACK):
   - Levels tested 2+ times with price consolidation
   - High volume zones
   - Clear pivot points
   - Use when no clear trend or pullback setup exists

4. **STOP-LOSS PLACEMENT** (CRITICAL - Do this FIRST):
   - After determining direction (BUY/SELL), find the STRONGEST pivot point from the FULL 60-minute data
   - Look through ALL 60 candles, not just the last 5-10 candles
   - For LONG: Find the most significant swing LOW or support zone (tested 2+ times, clear structure, meaningful level)
   - For SHORT: Find the most significant swing HIGH or resistance zone (tested 2+ times, clear structure, meaningful level)
   - Place stop just beyond this pivot (5-20 dollars past it)
   - The stop MUST be at a real structural pivot, not just a random recent candle high/low

   **STOP DISTANCE CONSTRAINTS (CRITICAL):**
   - Minimum stop distance: 0.10% from entry (|entry - stop| / entry ≥ 0.001)
   - Maximum stop distance: 0.50% from entry (|entry - stop| / entry ≤ 0.005)
   - Calculate: (|entry - stop| / entry) × 100 = percentage
   - If the nearest strong pivot is closer than 0.10%, look for the next major pivot
   - If all pivots are more than 0.50% away → use "hold"

5. **TARGET CALCULATION** (Based on market structure FIRST, ratio check SECOND):
   - **PRIORITY: Find the best target based on market structure**
   - Calculate risk distance: |entry - stop|
   - Look for the next significant support/resistance level
   - Use the actual market level as your target
   - THEN verify the ratio falls within acceptable boundaries:
     - **Minimum acceptable ratio: 1:2** (risk $400 to make $200) = 0.5:1 reward-to-risk
     - **Maximum acceptable ratio: 3:1** (risk $200 to make $600) = 3:1 reward-to-risk
   - Any ratio between 0.5:1 and 3:1 is acceptable (0.8:1, 1.5:1, 2.3:1, etc.)
   - Examples:
     - Risk $150, Target $100 away = 0.67:1 ratio ✓ (within range)
     - Risk $100, Target $250 away = 2.5:1 ratio ✓ (within range)
     - Risk $200, Target $700 away = 3.5:1 ratio ✗ (exceeds max, use "hold")
   - If no significant level exists within ratio range → use "hold"

---

Provide TWO outputs:

1. ANALYSIS (for traders):
Analyze trend and pullback structure (PRIMARY), check for false breakouts (SECONDARY), identify support/resistance zones. Give clear BUY/SELL/HOLD recommendation with reasoning. IMPORTANT: Mention which pivot point you're using for the stop-loss and why it's significant (e.g., "Stop below $121,880 pivot - tested 3 times as support").

2. TRADE_DATA (for execution):
{{
  "action": "buy" or "sell" or "hold",
  "entry_price": {current_price},
  "stop_loss": <number>,
  "take_profit": <number>,
  "confidence": 0-100
}}

⚠️ CRITICAL: Output PURE JSON ONLY. NO COMMENTS. Do NOT add // text after values.

STEP-BY-STEP PROCESS:

Step 1: Determine trade direction (BUY/SELL/HOLD) based on patterns above

Step 2: FIND THE STOP-LOSS (Most important step!)
For BUY (LONG):
  * Look through ALL 60 minutes of data for the strongest swing LOW or support pivot
  * This could be: a level tested 2+ times, a sharp bounce point, consolidation zone
  * DO NOT just use the low of the last few candles - find SIGNIFICANT pivots
  * Place stop 5-20 dollars BELOW this pivot
  * stop_loss MUST BE BELOW entry_price
  * CHECK: Is |entry - stop| / entry between 0.10% and 0.50%? If not, find different pivot

For SELL (SHORT):
  * Look through ALL 60 minutes of data for the strongest swing HIGH or resistance pivot
  * This could be: a level tested 2+ times, a sharp rejection point, consolidation zone
  * DO NOT just use the high of the last few candles - find SIGNIFICANT pivots
  * Place stop 5-20 dollars ABOVE this pivot
  * stop_loss MUST BE ABOVE entry_price
  * CHECK: Is |entry - stop| / entry between 0.10% and 0.50%? If not, find different pivot

Step 3: CALCULATE THE TARGET (Market structure is PRIORITY, ratio is just a check)
  * Calculate risk = |entry_price - stop_loss|
  * Look for the next significant support/resistance level (tested 2+ times, consolidation, etc.)
  * For LONG: Find the next resistance level above entry
  * For SHORT: Find the next support level below entry
  * Use the actual market level as your target
  * THEN check if ratio falls within range:
    - Minimum: 0.5:1 (target can be 0.5× the risk distance)
    - Maximum: 3:1 (target can be up to 3× the risk distance)
  * Any ratio between 0.5:1 and 3:1 is valid (0.67:1, 1.2:1, 2.5:1, etc.)
  * If no significant level exists within this ratio range, use "hold"

Example for LONG (good ratio):
  * Entry: $4,300
  * Looking at 60min data, find strong pivot low at $4,288 (tested 3 times)
  * Stop: $4,285 (below pivot)
  * Risk: $4,300 - $4,285 = $15 → 0.35% ✓ (between 0.10%-0.50%)
  * Looking for resistance: Strong resistance at $4,315 (consolidation zone)
  * Target: $4,315 (distance: $15 → 0.35%, ratio: 1:1 ✓) - Within 0.5:1 to 3:1 range

Example for SHORT (acceptable ratio):
  * Entry: $4,300
  * Looking at 60min data, find strong pivot high at $4,312 (tested 3 times)
  * Stop: $4,315 (above pivot)
  * Risk: $4,315 - $4,300 = $15 → 0.35% ✓ (between 0.10%-0.50%)
  * Looking for support: Strong support at $4,280 (tested 2x as support)
  * Target: $4,280 (distance: $20 → 0.47%, ratio: 1.33:1 ✓) - Within range

Example for LONG (great ratio):
  * Entry: $4,300
  * Strong pivot low at $4,280 → Stop: $4,278
  * Risk: $22 → 0.51% ✗ (exceeds 0.50% max)
  * Result: Try next pivot at $4,288 → Stop: $4,285 → 0.35% ✓
  * Next resistance at $4,320 (major level)
  * Target: $4,320 (distance: $20 → 0.47%, ratio: 1.33:1 ✓)

Example of REJECTED trade (stop too tight):
  * Entry: $4,300, nearest pivot: $4,298
  * Stop would be: $4,297
  * Risk: $3 → 0.07% ✗ (less than 0.10% minimum)
  * Result: Find a different pivot OR use "hold"

FINAL VALIDATION (Check ALL of these):
- BUY: stop_loss < entry_price < take_profit ✓
- SELL: take_profit < entry_price < stop_loss ✓
- Stop distance: 0.10% ≤ |entry - stop| / entry ≤ 0.50% ✓
- Risk-reward ratio: 0.5 ≤ ratio ≤ 3.0 (any value in range is acceptable) ✓
- Stop is at a SIGNIFICANT pivot from the full 60min data (not a random recent candle) ✓
- Target is at a real support/resistance level (not calculated artificially) ✓
- If ANY check fails → use "hold"

NOTE: Ratio range is VERY flexible:
- 0.5:1 = acceptable (risk $400 to make $200, not ideal but valid)
- 1:1 = neutral (risk $200 to make $200)
- 2:1 = good (risk $100 to make $200)
- 3:1 = excellent (risk $100 to make $300)
Priority is finding real market levels, THEN checking ratio is in range.

For "hold": set stop_loss and take_profit to null

Confidence levels:
- >70: Strong pattern (ideal trend pullback at structure, false breakout, strong zones)
- 50-70: Moderate setup (acceptable trend pullback, decent structure)
- <50: Weak/unclear → probably use "hold"

DOUBLE-CHECK before responding:
- BUY: Is stop < entry < target? ✓
- SELL: Is target < entry < stop? ✓
- Is stop placed at a SIGNIFICANT pivot from the FULL 60min data (not just last few candles)? ✓
- Is stop distance between 0.10% and 0.50% from entry? ✓
- Did I place target at an actual support/resistance level (not artificially calculated)? ✓
- Is risk-reward ratio between 0.5:1 and 3:1? ✓
- Did I prioritize market structure FIRST, then check ratio SECOND? ✓"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )

    full_response = response.choices[0].message.content

    # Parse response to extract analysis and trade data
    analysis, trade_data = parse_llm_response(full_response)

    return analysis, trade_data


def parse_llm_response(response_text):
    """Extract human analysis and structured trade data from ChatGPT response"""

    # Try to find JSON in the response
    json_match = re.search(r'\{[^}]*"action"[^}]*\}', response_text, re.DOTALL)

    if json_match:
        try:
            trade_data = json.loads(json_match.group(0))
            # Extract analysis (everything before the JSON)
            analysis = response_text[:json_match.start()].strip()
            # Clean up common markers
            analysis = re.sub(r'^\*\*?ANALYSIS\*\*?:?\s*', '', analysis, flags=re.IGNORECASE)
            analysis = re.sub(r'\*\*?TRADE_DATA\*\*?:?\s*.*$', '', analysis, flags=re.DOTALL | re.IGNORECASE)
            return analysis.strip(), trade_data
        except json.JSONDecodeError:
            pass

    # Fallback: return full text as analysis, no trade data
    return response_text, None


def validate_trade_levels(trade_data, current_price):
    """Validate that stop-loss and take-profit levels make sense

    Returns:
        tuple: (is_valid, error_message)
    """
    if not trade_data or trade_data.get('action') == 'hold':
        return True, None

    action = trade_data.get('action')
    entry = current_price  # We use current price as entry
    stop = trade_data.get('stop_loss')
    target = trade_data.get('take_profit')

    # Check that levels exist
    if stop is None or target is None:
        return False, "Missing stop_loss or take_profit"

    # Calculate distances and percentages
    stop_distance = abs(entry - stop)
    target_distance = abs(entry - target)
    stop_percentage = (stop_distance / entry) * 100  # Convert to percentage
    target_percentage = (target_distance / entry) * 100

    # Check stop distance constraints (0.10% to 0.50%)
    if stop_percentage < 0.10:
        return False, f"Stop too tight: {stop_percentage:.2f}% (minimum 0.10%)"
    if stop_percentage > 0.50:
        return False, f"Stop too wide: {stop_percentage:.2f}% (maximum 0.50%)"

    # Check target distance constraints (0.10% to 0.50%)
    if target_percentage < 0.10:
        return False, f"Target too close: {target_percentage:.2f}% (minimum 0.10%)"
    if target_percentage > 0.50:
        return False, f"Target too far: {target_percentage:.2f}% (maximum 0.50%)"

    # Check risk-reward ratio (0.5:1 to 3:1, meaning 1:2 to 3:1)
    rr_ratio = target_distance / stop_distance if stop_distance > 0 else 0
    if rr_ratio < 0.5:
        return False, f"Risk-reward too low: {rr_ratio:.2f}:1 (minimum 0.5:1, aka 1:2)"
    if rr_ratio > 3.0:
        return False, f"Risk-reward too high: {rr_ratio:.2f}:1 (maximum 3:1)"

    # For BUY (long): stop < entry < target
    if action == 'buy':
        if stop >= entry:
            return False, f"LONG: stop_loss (${stop:,.2f}) must be BELOW entry (${entry:,.2f})"
        if target <= entry:
            return False, f"LONG: take_profit (${target:,.2f}) must be ABOVE entry (${entry:,.2f})"

    # For SELL (short): target < entry < stop
    elif action == 'sell':
        if target >= entry:
            return False, f"SHORT: take_profit (${target:,.2f}) must be BELOW entry (${entry:,.2f})"
        if stop <= entry:
            return False, f"SHORT: stop_loss (${stop:,.2f}) must be ABOVE entry (${entry:,.2f})"

    return True, None


def send_to_discord(analysis, webhook_url, chart_image, trade_data=None, trade_results=None, positions_data=None):
    """Send analysis and chart to Discord with position management info"""

    # Start with analysis
    full_description = analysis

    # Add trade results (position changes)
    if trade_results:
        full_description += "\n\n**💼 Position Updates:**"
        for result in trade_results:
            full_description += f"\n{result['message']}"

    # Add trade levels ONLY if trade was accepted (check if there's an active position or if signal matches)
    # Don't show levels if validation rejected the trade
    trade_was_accepted = False
    if positions_data:
        current_status = positions_data.get('current_position', {}).get('status', 'none')
        last_signal = positions_data.get('last_signal', 'hold')
        # Trade accepted if: there's an active position OR last_signal matches trade action
        if current_status != 'none' or (trade_data and last_signal == trade_data.get('action')):
            trade_was_accepted = True

    if trade_data and trade_data.get('action') != 'hold' and trade_was_accepted:
        full_description += f"\n\n**📊 Trade Levels:**"
        full_description += f"\n🔵 Entry: ${trade_data.get('entry_price', 0):,.2f}"
        full_description += f"\n🔴 Stop Loss: ${trade_data.get('stop_loss', 0):,.2f}"
        full_description += f"\n🟢 Take Profit: ${trade_data.get('take_profit', 0):,.2f}"
        if 'confidence' in trade_data:
            full_description += f"\n📈 Confidence: {trade_data['confidence']}%"
    elif trade_data and trade_data.get('action') != 'hold' and not trade_was_accepted:
        # Trade was rejected by validation
        full_description += f"\n\n**⚠️ Trade Rejected:** Signal was {trade_data.get('action', 'unknown').upper()} but validation failed (check stop distance, risk-reward ratio, or levels)"

    # Add performance stats
    if positions_data:
        balance = positions_data.get("paper_trading_balance", 10000)
        total = positions_data.get("total_trades", 0)
        wins = positions_data.get("winning_trades", 0)
        losses = positions_data.get("losing_trades", 0)
        win_rate = (wins / total * 100) if total > 0 else 0

        # Calculate average win/loss from trade history
        trade_history = positions_data.get("trade_history", [])
        total_profit = sum(t["profit_loss"] for t in trade_history if t["profit_loss"] > 0)
        total_loss = abs(sum(t["profit_loss"] for t in trade_history if t["profit_loss"] < 0))
        avg_win = (total_profit / wins) if wins > 0 else 0
        avg_loss = (total_loss / losses) if losses > 0 else 0
        avg_ratio = (avg_win / avg_loss) if avg_loss > 0 else avg_win

        full_description += f"\n\n**📈 Paper Trading Stats:**"
        full_description += f"\n💰 Balance: ${balance:,.2f}"
        full_description += f"\n📊 Trades: {total} ({wins}W / {losses}L)"
        if total > 0:
            if losses > 0:
                full_description += f"\n📊 Avg W:L: {avg_ratio:.2f}:1 (avg win: ${avg_win:.2f}, avg loss: ${avg_loss:.2f})"
            else:
                full_description += f"\n📊 Avg W:L: Perfect! (${avg_win:.2f} avg win, no losses)"
            full_description += f"\n🎯 Win Rate: {win_rate:.1f}%"

    # Format as Discord embed for better readability
    payload = {
        "embeds": [
            {
                "title": "🪙 BTC Trading Bot Update",
                "description": full_description,
                "color": 0x00FF00
                if "buy" in analysis.lower()
                else 0xFFA500
                if "hold" in analysis.lower()
                else 0xFF0000,  # Green/Yellow/Red based on rec
                "image": {
                    "url": "attachment://chart.png"
                },
                "footer": {
                    "text": f"Paper Trading | {os.getenv('GITHUB_RUN_ID', 'Local')}"
                },
                "timestamp": datetime.now().isoformat(),
            }
        ]
    }

    # Send with file attachment
    files = {
        'file': ('chart.png', chart_image, 'image/png')
    }
    data = {
        'payload_json': json.dumps(payload)
    }

    response = requests.post(webhook_url, data=data, files=files)
    if response.status_code != 204 and response.status_code != 200:
        print(f"Discord send failed: {response.status_code} - {response.text}")
    else:
        print("Analysis and chart sent to Discord successfully!")


if __name__ == "__main__":
    print("="*70)
    print("🤖 BTC TRADING BOT - PAPER TRADING MODE")
    print("="*70)

    # Load current position state
    positions_data = load_positions()
    print(f"\n📊 Current Status: {positions_data['current_position']['status'].upper()}")
    if positions_data['current_position']['status'] != 'none':
        print(f"   Entry: ${positions_data['current_position']['entry_price']:,.2f}")

    # Show stats if there are any trades
    if positions_data.get('total_trades', 0) > 0:
        balance = positions_data.get("paper_trading_balance", 10000)
        total = positions_data.get("total_trades", 0)
        wins = positions_data.get("winning_trades", 0)
        losses = positions_data.get("losing_trades", 0)
        win_rate = (wins / total * 100) if total > 0 else 0

        # Calculate average win/loss from trade history
        trade_history = positions_data.get("trade_history", [])
        total_profit = sum(t["profit_loss"] for t in trade_history if t["profit_loss"] > 0)
        total_loss = abs(sum(t["profit_loss"] for t in trade_history if t["profit_loss"] < 0))
        avg_win = (total_profit / wins) if wins > 0 else 0
        avg_loss = (total_loss / losses) if losses > 0 else 0
        avg_ratio = (avg_win / avg_loss) if avg_loss > 0 else avg_win

        print(f"\n📈 Paper Trading Stats:")
        print(f"   💰 Balance: ${balance:,.2f}")
        print(f"   📊 Trades: {total} ({wins}W / {losses}L)")
        if losses > 0:
            print(f"   📊 Avg W:L: {avg_ratio:.2f}:1 (avg win: ${avg_win:.2f}, avg loss: ${avg_loss:.2f})")
        else:
            print(f"   📊 Avg W:L: Perfect! (${avg_win:.2f} avg win, no losses)")
        print(f"   🎯 Win Rate: {win_rate:.1f}%")

    # Fetch the data
    print("\n📥 Fetching BTC data from Coinbase...")
    data = fetch_btc_data()
    print("✅ Data fetched successfully\n")

    # Get current price
    lines = data.strip().split('\n')
    latest_candle = lines[-1].split(',')
    current_price = float(latest_candle[4])
    print(f"💵 Current BTC Price: ${current_price:,.2f}\n")

    # Analyze with LLM (now returns analysis + trade data)
    print("🧠 Analyzing with ChatGPT...")
    analysis, trade_data = analyze_with_llm(data)
    print("✅ Analysis complete\n")

    # Print trade data for debugging
    if trade_data:
        print(f"📊 Signal: {trade_data.get('action', 'unknown').upper()}")
        print(f"   Confidence: {trade_data.get('confidence', 0)}%\n")

    # Manage positions (execute trades, check stops, etc.)
    print("💼 Managing positions...")
    trade_results = manage_positions(positions_data, trade_data, current_price, data)

    # Print trade results
    if trade_results:
        for result in trade_results:
            print(f"   {result['message']}")
    print()

    # Save updated position state
    save_positions(positions_data)
    print("💾 Position state saved\n")

    # Check if trade was rejected by validation
    trade_invalid = False
    if trade_results:
        for result in trade_results:
            if not result.get('success', True) and "Invalid trade levels" in result.get('message', ''):
                trade_invalid = True
                break

    # Generate chart with trade levels (and invalid flag if rejected)
    chart_image = generate_chart(data, trade_data, trade_invalid)

    # Send to Discord
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if webhook_url:
        print("📤 Sending to Discord...")
        send_to_discord(analysis, webhook_url, chart_image, trade_data, trade_results, positions_data)
    else:
        print("⚠️  No Discord webhook configured")
        print(f"\nLLM Analysis:\n{analysis}")
        if trade_data:
            print(f"\nTrade Data: {json.dumps(trade_data, indent=2)}")

    print("\n" + "="*70)
    print("✅ BOT RUN COMPLETE")
    print("="*70)
