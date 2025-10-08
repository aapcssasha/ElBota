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


def generate_chart(data, trade_data=None):
    """Generate candlestick chart from OHLCV data and return as bytes

    Args:
        data: CSV string with OHLCV data
        trade_data: Dict with entry_price, stop_loss, take_profit (optional)
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
        'savefig': dict(fname=buf, dpi=150, bbox_inches='tight')
    }

    # Only add hlines if we have trade data
    if hlines_dict:
        plot_kwargs['hlines'] = hlines_dict

    mpf.plot(df, **plot_kwargs)
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

🎯 ANALYSIS FRAMEWORK - Look for these patterns:

1. **SIGNIFICANT SUPPORT/RESISTANCE ZONES**: Identify the STRONGEST, most noticeable price levels where:
   - Price bounced multiple times (tested 2+ times)
   - Price consolidated/ranged for several candles
   - High volume occurred at that level
   - These are your stop-loss and take-profit zones!

2. **FALSE BREAKOUTS** (High priority signal):
   - Did price recently break above a strong resistance or below a strong support?
   - Did it then QUICKLY reverse back (within 3-5 candles)?
   - If YES: This is a FALSE BREAKOUT → Trade the REVERSAL direction
   - Example: Price breaks above $122,500 resistance, then drops back below → SELL signal

3. **WAVE TRADING / TREND FOLLOWING** (Preferred for trending markets):
   - Is the market moving in clear waves (higher highs + higher lows = uptrend, or lower lows + lower highs = downtrend)?
   - In an UPTREND: Wait for pullbacks to ~50% of the previous swing up, then BUY
   - In a DOWNTREND: Wait for bounces to ~50% of the previous swing down, then SELL
   - Example: Price goes from $122,000 → $122,400 (+$400), pulls back to $122,200 (50% retrace) → BUY signal

4. **RISK-REWARD RATIO** (CRITICAL - Must follow):
   - Minimum 2:1 reward-to-risk ratio (risk $100 to make $200+)
   - Prefer 3:1 or 4:1 when strong zones exist
   - NEVER trade if ratio is poor (like risking $400 to make $100) → use "hold" instead
   - It's OK to risk $100 with tight stop if target is $300-400 at a strong zone

---

Provide TWO outputs:

1. ANALYSIS (for traders):
Identify strongest support/resistance zones, check for false breakouts, analyze trend/wave structure. Give clear BUY/SELL/HOLD recommendation with reasoning. Mention which pattern you're seeing (false breakout, wave trading, range, etc.).

2. TRADE_DATA (for execution):
{{
  "action": "buy" or "sell" or "hold",
  "entry_price": {current_price},
  "stop_loss": <number>,
  "take_profit": <number>,
  "confidence": 0-100
}}

⚠️ CRITICAL: Output PURE JSON ONLY. NO COMMENTS. Do NOT add // text after values.

RULES for stop_loss and take_profit:
- MUST use STRONG support/resistance zones from the data (tested multiple times or high consolidation)
- Stop-loss = just beyond the nearest strong zone (tight but safe)
- Take-profit = next major support/resistance zone (with good risk-reward ratio)

For BUY (LONG):
  * stop_loss = below nearest STRONG support zone - MUST BE BELOW ENTRY
  * take_profit = at/near next STRONG resistance zone - MUST BE ABOVE ENTRY
  * Rule: stop_loss < entry_price < take_profit
  * Example: Entry $122,000, Strong support at $121,950, Strong resistance at $122,400
    → stop_loss: $121,930, take_profit: $122,400 (Risk $70, Gain $400 = 5.7:1 ratio ✓)

For SELL (SHORT):
  * stop_loss = above nearest STRONG resistance zone - MUST BE ABOVE ENTRY
  * take_profit = at/near next STRONG support zone - MUST BE BELOW ENTRY
  * Rule: take_profit < entry_price < stop_loss
  * Example: Entry $122,000, Strong resistance at $122,050, Strong support at $121,600
    → stop_loss: $122,070, take_profit: $121,600 (Risk $70, Gain $400 = 5.7:1 ratio ✓)

RISK-REWARD CHECK (Do this calculation!):
- Calculate: (take_profit - entry_price) / (entry_price - stop_loss) for LONG
- Calculate: (entry_price - take_profit) / (stop_loss - entry_price) for SHORT
- If ratio < 2.0 → Reconsider trade or use "hold"
- If no clear strong zones or bad ratio → use "hold"

For "hold": set stop_loss and take_profit to null

Confidence levels:
- >70: Strong pattern (false breakout, clear wave entry, strong zones)
- 50-70: Moderate setup
- <50: Weak/unclear → probably use "hold"

DOUBLE-CHECK before responding:
- BUY: Is stop < entry < target? ✓
- SELL: Is target < entry < stop? ✓
- Is risk-reward ratio ≥ 2:1? ✓
- Are stop/target at STRONG tested levels (not arbitrary)? ✓"""

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

    # Add trade levels if there's a signal
    if trade_data and trade_data.get('action') != 'hold':
        full_description += f"\n\n**📊 Trade Levels:**"
        full_description += f"\n🔵 Entry: ${trade_data.get('entry_price', 0):,.2f}"
        full_description += f"\n🔴 Stop Loss: ${trade_data.get('stop_loss', 0):,.2f}"
        full_description += f"\n🟢 Take Profit: ${trade_data.get('take_profit', 0):,.2f}"
        if 'confidence' in trade_data:
            full_description += f"\n📈 Confidence: {trade_data['confidence']}%"

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

    # Generate chart with trade levels
    chart_image = generate_chart(data, trade_data)

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
