#!/usr/bin/env python3
"""
Manual LLM Testing Script
--------------------------
This script prepares the trading prompt for manual testing across different LLMs
(ChatGPT, Claude, Grok, Gemini, etc.) without using APIs.

Usage:
    python3 test_llm_manual.py

Output:
    1. Formatted prompt saved to 'prompt_for_llms.txt'
    2. Chart image saved to 'chart_for_llms.png'
    3. Prompt printed to console for easy copying
"""

import os
import json
import requests
from datetime import datetime
import pytz
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf

# ============================================================================
# CONFIGURATION - Change these to switch crypto/timeframe
# ============================================================================
CRYPTO_SYMBOL = "ETH"  # Options: BTC, ETH, SOL, etc.
TIMEFRAME_MINUTES = 120  # How many minutes of data to fetch
OUTPUT_PROMPT_FILE = "prompt_for_llms.txt"
OUTPUT_CHART_FILE = "chart_for_llms.png"

# Derived values (don't change)
COINBASE_API_URL = f"https://api.exchange.coinbase.com/products/{CRYPTO_SYMBOL}-USD/candles"
CRYPTO_LOWER = CRYPTO_SYMBOL.lower()


def fetch_crypto_data():
    """Fetch last N minutes of crypto/USD 1-minute candles from Coinbase"""
    print(f"📊 Fetching {CRYPTO_SYMBOL} data from Coinbase...")

    params = {
        "granularity": 60  # 1-minute candles
    }

    response = requests.get(COINBASE_API_URL, params=params)
    response.raise_for_status()

    data = response.json()

    # Coinbase returns: [timestamp, low, high, open, close, volume]
    df = pd.DataFrame(
        data, columns=["timestamp", "low", "high", "open", "close", "volume"]
    )

    # Convert timestamp to datetime (ET timezone for display)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York")

    # Sort by time (oldest first) and limit to last N candles
    df = df.sort_values("timestamp").tail(TIMEFRAME_MINUTES).reset_index(drop=True)

    print(f"✅ Fetched {len(df)} candles")
    print(
        f"📅 Time range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]} (ET)"
    )
    print(f"💰 Current {CRYPTO_SYMBOL} price: ${df['close'].iloc[-1]:,.2f}")

    return df


def format_data_for_prompt(df):
    """Format the crypto data as it would be sent to the LLM"""
    data_str = "Timestamp (ET), Open, High, Low, Close, Volume\n"

    for _, row in df.iterrows():
        time_str = row["timestamp"].strftime("%Y-%m-%d %H:%M")
        data_str += f"{time_str}, {row['open']:.2f}, {row['high']:.2f}, {row['low']:.2f}, {row['close']:.2f}, {row['volume']:.6f}\n"

    return data_str


def generate_prompt(data_str, current_price):
    """Generate the exact prompt that goes to ChatGPT API"""

    prompt = f"""You are a professional {CRYPTO_SYMBOL} short-term scalping trading analyst. Analyze the following {TIMEFRAME_MINUTES} minutes of {CRYPTO_SYMBOL}/USD 1-minute candle data and provide a trading recommendation.

**CURRENT {CRYPTO_SYMBOL} PRICE: ${current_price:,.2f}**

**DATA (Last {TIMEFRAME_MINUTES} candles):**
{data_str}

---

## TRADING FRAMEWORK (STRICT REQUIREMENTS)

### 1. STRATEGY PRIORITY (Choose ONE that fits current market):

**A) Trend Following with Pullback Entries** (PRIMARY STRATEGY)
- Identify clear trend: higher highs/lows (uptrend) OR lower highs/lows (downtrend)
- Enter on pullbacks/bounces: 20-80% retracement of previous swing (flexible range)
- **IDEAL SETUP (highest confidence):**
  - **For UPTREND (BUY):** Price makes higher high → pulls back to/near previous high
    - Example: $50 → drops to $25 → rallies to new high $75 → pulls back to ~$50 (near previous high)
    - This combines: trend following + ~50% pullback + previous structure support
  - **For DOWNTREND (SELL):** Price makes lower low → bounces to/near previous low
    - Example: $50 → rallies to $75 → drops to new low $25 → bounces to ~$50 (near previous low)
    - This combines: trend following + ~50% bounce + previous structure resistance
- **ACCEPTABLE SETUPS (medium confidence):**
  - Any 20-80% retracement in a clear trend, even if not at previous structure
  - Closer to 40-60% range = higher confidence
  - Landing at previous high/low = bonus confidence boost

**B) False Breakout Reversal** (SECONDARY - use if detected)
- Price breaks strong support/resistance → quickly reverses within 3-5 candles
- Trade the reversal direction
- Example: Break above resistance → drops back → SELL signal
- Example: Break below support → bounces back → BUY signal

**C) Strong Support/Resistance Zones** (FALLBACK)
- Levels tested 2+ times with price consolidation
- High volume zones
- Clear pivot points
- Use when no clear trend or pullback setup exists

### 2. STOP-LOSS PLACEMENT (PRIMARY STEP - DO THIS FIRST)

**CRITICAL:** Stop-loss determines if trade is valid!

**Process:**
1. Analyze FULL {TIMEFRAME_MINUTES}-minute data for strongest pivot points
2. Look for most significant swing high/low (tested 2+ times, clear structure)
3. For LONG: Find most significant swing LOW or support zone
4. FOR SHORT: Find most significant swing HIGH or resistance zone
5. Place stop 5-20 dollars beyond this pivot

**Stop Distance Constraints:**
- Minimum distance: 0.10% from entry (prevents overly tight stops)
- Maximum distance: 0.50% from entry (keeps stops reasonable)
- Calculate: (|entry - stop| / entry) × 100 = percentage
- If nearest pivot is <0.10% away → find next major pivot
- If all pivots are >0.50% away → use "hold" action

**Example (LONG):**
- Current: $4,300
- Found strong support at $4,280 (tested 3x in last hour)
- Stop placement: $4,275 (below support, $25 away = 0.58% from entry)
- Wait, 0.58% > 0.50% max → Try next pivot at $4,290
- New stop: $4,285 ($15 away = 0.35%) ✅ Valid (0.10%-0.50% range)

### 3. TARGET CALCULATION (MARKET STRUCTURE FIRST)

**Process:**
1. Find next significant support/resistance level based on market structure
2. Use actual market level as target (don't force ratios)
3. THEN verify ratio falls within acceptable boundaries

**Risk-Reward Ratio Boundaries:**
- Minimum: 0.5:1 (risk $400 to make $200 = acceptable)
- Maximum: 3:1 (risk $200 to make $600)
- Any ratio between 0.5:1 and 3:1 is valid
- Examples of acceptable ratios: 0.65:1, 1.2:1, 1.8:1, 2.5:1, 2.9:1

**Important:** These are just boundaries to prevent extreme trades, NOT targets to aim for. Let market structure determine the target, then verify it's within range.

**Example Targets (all valid):**
- Risk $300 / Reward $200 = 0.67:1 ratio ✅
- Risk $250 / Reward $300 = 1.2:1 ratio ✅
- Risk $200 / Reward $500 = 2.5:1 ratio ✅

If no significant level exists within ratio range → use "hold"

### 4. VALIDATION CHECKS (Must pass ALL):

- Direction: LONG (stop < entry < target) or SHORT (target < entry < stop)
- Stop Distance: Between 0.10% and 0.50% from entry
- Target Distance: Between 0.10% and 0.50% from entry
- Risk-Reward: Between 0.5:1 and 3:1
- If ANY check fails → use "hold" action

---

## OUTPUT FORMAT

Provide TWO sections:

**SECTION 1: Human Analysis (for Discord)**
Write 3-5 sentences explaining:
- Current market structure (trend, key levels, pattern)
- Why you chose this action (strategy used)
- Key support/resistance levels identified
- Risk factors or confidence notes

**SECTION 2: Structured JSON (for bot parsing)**
```json
{{
  "action": "buy|sell|hold",
  "entry_price": 122000.00,
  "stop_loss": 121500.00,
  "take_profit": 122500.00,
  "confidence": "high|medium|low",
  "strategy_used": "trend_pullback|false_breakout|support_resistance|hold"
}}
```

**Rules:**
- action: "buy" (open long), "sell" (open short), "hold" (no trade)
- All prices must be realistic based on current price
- confidence: "high" (clear setup), "medium" (decent setup), "low" (weak setup)
- If recommending "hold", still provide analysis but JSON can have null prices

**IMPORTANT:** Only recommend BUY/SELL if you have HIGH confidence and ALL validation checks pass. When in doubt, use HOLD.

---

Now analyze the data and provide your recommendation."""

    return prompt


def generate_chart(df):
    """Generate candlestick chart similar to main bot"""
    print("\n📈 Generating chart...")

    # Prepare data for mplfinance
    chart_df = df.set_index("timestamp")
    chart_df = chart_df[["open", "high", "low", "close", "volume"]]
    chart_df.columns = ["Open", "High", "Low", "Close", "Volume"]

    # Create custom style
    mc = mpf.make_marketcolors(
        up="#26a69a",
        down="#ef5350",
        edge="inherit",
        wick="inherit",
        volume="in",
        alpha=0.9,
    )

    s = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle="-",
        gridcolor="#e0e0e0",
        facecolor="white",
        figcolor="white",
        gridaxis="both",
    )

    # Plot
    fig, axes = mpf.plot(
        chart_df,
        type="candle",
        style=s,
        volume=True,
        title=f"{CRYPTO_SYMBOL}/USD - Last {TIMEFRAME_MINUTES} Minutes (1-min candles)",
        ylabel="Price (USD)",
        ylabel_lower="Volume",
        figsize=(14, 8),
        returnfig=True,
        datetime_format="%H:%M",
        xrotation=45,
    )

    # Save
    plt.savefig(OUTPUT_CHART_FILE, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"✅ Chart saved to: {OUTPUT_CHART_FILE}")


def main():
    print("\n" + "=" * 60)
    print(f"🧪 MANUAL LLM TESTING - {CRYPTO_SYMBOL} PROMPT GENERATOR")
    print("=" * 60 + "\n")

    # Fetch data
    df = fetch_crypto_data()
    current_price = df["close"].iloc[-1]

    # Format data
    data_str = format_data_for_prompt(df)

    # Generate prompt
    prompt = generate_prompt(data_str, current_price)

    # Save prompt to file
    with open(OUTPUT_PROMPT_FILE, "w") as f:
        f.write(prompt)

    print(f"\n✅ Prompt saved to: {OUTPUT_PROMPT_FILE}")

    # Generate chart
    generate_chart(df)

    # Print instructions
    print("\n" + "=" * 60)
    print("📋 HOW TO TEST DIFFERENT LLMs")
    print("=" * 60)
    print(f"""
1. Open the prompt file: {OUTPUT_PROMPT_FILE}
2. Copy the entire prompt
3. Test on each LLM:

   🤖 ChatGPT: https://chat.openai.com
   🧠 Claude: https://claude.ai
   🚀 Grok: https://x.com/i/grok
   💎 Gemini: https://gemini.google.com

4. Paste the prompt into each chat
5. Optionally upload the chart: {OUTPUT_CHART_FILE}
6. Compare outputs!

📊 WHAT TO COMPARE:
- Trade direction (BUY/SELL/HOLD)
- Entry, stop, take-profit levels
- Quality of analysis
- Confidence and reasoning
- Risk-reward ratios
- Which model understands the framework best

💡 TIP: Open all LLM chats in different tabs, paste the same prompt,
        and compare side-by-side!
""")

    # Print prompt preview
    print("\n" + "=" * 60)
    print("📄 PROMPT PREVIEW (first 500 chars)")
    print("=" * 60)
    print(prompt[:500] + "...")
    print("\n[Full prompt saved to file]")

    print("\n✅ Done! Ready for manual testing.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
