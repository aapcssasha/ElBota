# ETH Futures Trading Bot - Project Documentation

**Repository:** https://github.com/aapcssasha/ElBota (Public)
**Status:** 💰 **LIVE TRADING** - Real money on Coinbase Futures
**Last Updated:** 2025-10-12

---

## 🎯 What This Bot Does

Automated ETH futures trading bot that:
1. Fetches ETH futures 1-minute candles from Coinbase Advanced API (last 120 minutes)
2. Syncs local state with actual Coinbase position (detects desyncs when stops/targets hit externally)
3. Sends data to ChatGPT (gpt-5 or gpt-5-mini, time-based) for technical analysis
4. Gets trading recommendation (BUY/SELL/HOLD) with entry, stop-loss, and take-profit levels
5. **Validates volume conditions** before opening trades (filters low-volume periods)
6. Executes **REAL futures trades** on Coinbase (with real money!)
7. Places stop-loss and take-profit orders automatically
8. Manages positions (tracks opens/closes, monitors P/L, cancels stale orders)
9. Generates candlestick charts with trading levels
10. Sends analysis + chart to Discord webhook
11. Runs automatically via GitHub Actions every 15 minutes

---

## 🏗️ How It Works

```
┌─────────────────────────────────────────────────────────┐
│          FUTURES TRADING BOT FLOW (Every 15 min)        │
└─────────────────────────────────────────────────────────┘

1. LOAD STATE
   └─> positions.json (current position, trade history, stats)

2. SYNC WITH COINBASE
   └─> Get actual position from Coinbase API
   └─> Detect desyncs (position closed externally via stop/target)
   └─> Calculate realized P/L if desync detected
   └─> Update local state to match reality

3. FETCH DATA
   └─> Coinbase Advanced API: Last 120 x 1-min ETH futures candles (OHLCV)

4. CHECK STOP/TARGET
   └─> Analyze candle highs/lows since entry time
   └─> If hit: close position, cancel pending orders, record P/L

5. GET SIGNAL
   └─> ChatGPT analyzes data
   └─> Returns: action (buy/sell/hold), entry, stop, target, confidence
   └─> Defensive parsing handles unexpected response formats

6. VALIDATE & MANAGE POSITION
   └─> Validate trade levels (stop distance, R:R ratio, direction)
   └─> Check volume conditions (filters low-volume periods)
   └─> None + BUY (valid) → Open Long + place stop/TP orders
   └─> None + SELL (valid) → Open Short + place stop/TP orders
   └─> Long + BUY → Hold (update stop/TP if missing)
   └─> Long + SELL → Close Long, Open Short (if valid)
   └─> Long + HOLD → Close Long
   └─> Short logic (reversed)

7. GENERATE CHART
   └─> Candlestick + volume
   └─> Shows entry/stop/target lines
   └─> Times in Eastern Time (ET)
   └─> "INVALID TRADE" overlay if validation failed

8. SEND TO DISCORD
   └─> Analysis text (with defensive type checking)
   └─> Chart image
   └─> Position updates
   └─> Real account balance
   └─> Trading stats (W/L, Avg W:L, Win Rate)

9. SAVE STATE
   └─> positions.json updated
   └─> Auto-committed to GitHub
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `CoinbaseMain.py` | **Main bot script** - Live futures trading logic |
| `main.py` | Old paper trading script (archived, not used) |
| `coinbase_futures_setup.py` | Helper to test API credentials and find futures products |
| `positions.json` | State persistence (current position, history, stats) |
| `.env` | API keys (NEVER commit!) |
| `requirements.txt` | Python dependencies |
| `.github/workflows/trading-bot.yml` | GitHub Actions automation |
| `CLAUDE.md` | This file - project reference |

---

## 💾 positions.json Structure

```json
{
  "current_position": {
    "status": "long|short|none",
    "entry_price": 3840.00,
    "entry_time": "2025-10-11T08:23:10.406861",
    "stop_loss": 3830.00,
    "take_profit": 3850.00,
    "trade_id": null,
    "action": "buy|sell|null",
    "entry_order_id": "xyz789...",
    "stop_loss_order_id": "abc123...",
    "take_profit_order_id": "def456...",
    "unrealized_pnl": 5.50
  },
  "last_signal": "buy|sell|hold",
  "trade_history": [
    {
      "type": "long|short",
      "entry_price": 3808.0,
      "exit_price": 3788.5,
      "profit_loss": 19.5,
      "entry_time": "2025-10-11T06:48:22.404713",
      "exit_time": "2025-10-11T07:21:22.833937",
      "note": "Closed externally (desync detected)"
    }
  ],
  "paper_trading_balance": 2000.0,  // Legacy field, ignored in live mode
  "total_trades": 16,
  "winning_trades": 8,
  "losing_trades": 8
}
```

**Important:**
- GitHub Actions auto-commits this file every 15 minutes to persist state between runs
- `entry_order_id` tracks the entry order ID (for limit orders that may not fill immediately)
- `stop_loss_order_id` and `take_profit_order_id` track pending orders on Coinbase
- Many trades have `"note": "Closed externally (desync detected)"` - this means stop/target hit between bot runs
- `paper_trading_balance` is a legacy field from old paper trading days (now ignored)

---

## 🤖 GitHub Actions Automation

**Runs:** Every 15 minutes (`cron: '*/15 * * * *'`)
**Platform:** ubuntu-latest with Python 3.13
**Script:** `CoinbaseMain.py` (live futures trading)

### Workflow Steps:
1. Checkout repo
2. Install dependencies (`requirements.txt`)
3. Run `CoinbaseMain.py` with secrets
4. Auto-commit `positions.json` with updated state
5. Push to GitHub (with retry logic and conflict resolution)

### Required Secrets:
- `OPENAI_API_KEY` - ChatGPT API
- `DISCORD_WEBHOOK_URL` - Discord notifications
- `COINBASE_API_KEY` - Coinbase API key (from CDP portal)
- `COINBASE_API_SECRET` - Coinbase API secret (private key)

### Permissions:
- **"Read and write permissions"** enabled (Settings → Actions → Workflow permissions)
- Allows bot to commit positions.json

### Monitoring:
- **Workflow runs:** https://github.com/aapcssasha/ElBota/actions
- **Discord channel:** Gets notification every 15 minutes (shows which model was used)
- **positions.json:** Check GitHub for latest state

---

## 🔨 Development Workflow

**⚠️ CRITICAL: ALWAYS FOLLOW THIS WORKFLOW**

```bash
# 1. PULL FIRST (positions.json is updated by GitHub Actions!)
git pull

# 2. Make changes to code
# Edit CoinbaseMain.py, etc.

# 3. Test locally (optional - BE CAREFUL, this executes real trades!)
source venv/bin/activate
python3 CoinbaseMain.py

# 4. Commit and push
git add <files>
git commit -m "Description"
git push
```

**Why pull first?**
- GitHub Actions commits positions.json every 15 minutes
- If you don't pull, you'll have merge conflicts
- Always sync before making changes

**Testing Locally:**
- Running `CoinbaseMain.py` locally will execute REAL trades with REAL money
- Make sure you understand what changes you're testing
- Consider testing with a separate test bot or paper trading mode first

---

## 📊 Performance Metrics

### Current Stats (as of 2025-10-12)
- **Total Trades:** 24 (12W / 12L)
- **Win Rate:** 50.0%
- **Avg W:L Ratio:** 8.06:1 (avg win: $19.76, avg loss: $2.45)
- **Many trades closed externally** - Stops/targets hit between bot runs (this is good!)

### Average Win/Loss Ratio (Avg W:L)

**Formula:** (Average Win Amount) / (Average Loss Amount)

**Example:**
- 4 trades: Win $100, Win $80, Lose $30, Lose $20
- Avg Win = ($100 + $80) / 2 = $90
- Avg Loss = ($30 + $20) / 2 = $25
- **Avg W:L = 3.6:1** (making $3.60 for every $1 lost)

**Why it matters:** Shows actual profitability, not just win frequency. A 3:1 ratio means you can have 25% win rate and still make money.

### Win Rate

**Formula:** (Winning Trades / Total Trades) × 100

**Note:** Win rate alone is misleading. You can have 80% win rate but lose money if your few losses are huge.

---

## 🔧 Important Implementation Details

### Futures Trading Configuration

**Location:** Top of `CoinbaseMain.py`

```python
FUTURES_PRODUCT_ID = "ET-31OCT25-CDE"  # ETH Futures (Oct 31, 2025)
CRYPTO_SYMBOL = "ETH"                   # For display purposes
TIMEFRAME_MINUTES = 120                 # How many minutes of data to fetch
CONTRACTS_PER_TRADE = 1                 # Number of contracts to trade (0.1 ETH each)
CONTRACT_MULTIPLIER = 0.1               # 0.1 ETH per contract for nano ETH futures

# Order execution settings
ORDER_TYPE = "limit"  # "market" or "limit" - market is faster, limit avoids spread

# Stop/Target distance constraints (as percentage from entry)
MIN_DISTANCE_PERCENT = 0.30  # Minimum 0.30% distance (prevents overly tight stops)
MAX_DISTANCE_PERCENT = 1.90  # Maximum 1.90% distance (keeps stops reasonable)
```

**Product:** `ET-31OCT25-CDE` (ETH Futures, expires Oct 31, 2025)
**Contract Size:** 0.1 ETH per contract
**Contracts Per Trade:** 1 (configurable)
**Leverage:** Depends on Coinbase account settings (typically 5-10x)
**Data Timeframe:** 120 minutes of 1-minute candles

**Position Size Example:**
- 1 contract = 0.1 ETH
- ETH at $4,000 = $400 notional value per contract
- With 10x leverage, requires ~$40 margin

### Order Type Configuration

**ORDER_TYPE = "limit"** (Current setting)
- **Limit Orders:** Placed at current market price
- Avoids spread/slippage
- May not fill immediately if market moves away
- Better for execution quality

**ORDER_TYPE = "market"** (Alternative)
- Executes immediately at best available price
- Guaranteed fill (for liquid markets)
- May have slippage on large orders

### Real Trading Integration

**API:** Coinbase Advanced Trade API via `coinbase-advanced-py` SDK

**Order Types:**
- **Limit/Market orders** for entry (configurable via ORDER_TYPE)
- **Stop-limit orders** for stop-loss (trigger + limit with $2 buffer)
- **Limit orders** for take-profit

**Order Management:**
- Bot places stop-loss and take-profit orders immediately after opening position
- **Entry, stop-loss, and take-profit order IDs** stored in positions.json
- Orders automatically cancelled when position closes
- Stale orders cancelled before new trades (including unfilled entry limit orders)
- Missing orders are re-placed if detected during "hold" signal

**Position Desync Detection:**
- Bot checks actual Coinbase position every run
- If local state says "long" but API says "none", position closed externally
- Bot checks if entry order was actually filled before recording P/L
- **If entry limit order never filled:** Cancels all orders without recording fake P/L
- Bot calculates realized P/L from filled order prices
- Records trade with note "Closed externally (desync detected)"
- This catches stops/targets hit between 15-minute runs
- Preserves local entry price if API returns 0 (common API issue)

### Volume Filtering (Added 2025-10-12)

**Purpose:** Prevents trading during low-volume periods (low liquidity, wide spreads)

**Function:** `check_volume_conditions(csv_data)`

**Conditions (BOTH must pass):**
1. **Average volume** of last 10 candles > 100
2. **At least 7 out of 10 candles** must have volume > 20

**Behavior:**
- Checked BEFORE opening any new position
- If conditions fail, trade is rejected with message:
  - `"⚠️ Volume too low to open LONG: avg volume 18.9 ≤ 100 AND only 3/10 candles > 20 volume (need 7+)"`
- Does NOT affect existing positions (only new entries)
- Applies to both LONG and SHORT signals

**Why it matters:**
- Prevents slippage during thin markets
- Improves fill quality
- Reduces risk of getting trapped in illiquid conditions

### Stop-Loss and Take-Profit Detection

**Method:** Checks candle highs/lows chronologically (not just current price)

- **For LONG:** Check each candle's **high** for take-profit, then **low** for stop-loss
- **For SHORT:** Check each candle's **low** for take-profit, then **high** for stop-loss
- **Timeframe:** Only checks candles after entry_time
- **Order matters:** Checks target first, then stop, in chronological order by candle
- **Why:** Catches targets/stops hit between 15-minute runs and respects price action order

**Example:** Entered long at $4,000 with target $4,020. If any candle between entry and now had high ≥ $4,020, target is hit (even if current price is $4,010).

**Integration with Real Orders:**
- Candle-based detection is a backup check
- Real stop/TP orders execute immediately on Coinbase when triggered
- Desync detection catches these fills and syncs local state

### Chart Timezone

- **Data source:** Coinbase returns UTC timestamps
- **Display:** Converted to Eastern Time (America/New_York)
- **Why:** User is in ET, chart should match local time

### ChatGPT Prompt Strategy

- **Model:** Time-based switching between gpt-5 and gpt-5-mini
  - **6am-2pm Miami time:** gpt-5 (better reasoning, ~2.6 min response time)
  - **2pm-6am Miami time:** gpt-5-mini (faster, cheaper)
  - **Reason:** OpenAI Tier 1-2 limits gpt-5 to 250K tokens/day (free with data sharing)
  - **Token usage:** 6am-2pm = 32 runs × 7K tokens = 224K ✓ | 2pm-6am = 64 runs × 7K = 448K (gpt-5-mini has 2.5M limit) ✓
  - **Discord:** Model name always shown below "Position Updates" section
- **Context:** 120 minutes of 1-min candles (OHLCV data)
- **Focus:** SHORT-TERM SCALPING with strong technical levels
- **Output:** Dual format
  1. Human-readable analysis (for Discord)
  2. Structured JSON (action, entry, stop, target, confidence)

**Trading Framework:**

**⚠️ TREND FOLLOWING ONLY - NO COUNTER-TREND TRADES**

1. **Step 1: Identify Trend** (MANDATORY)
   - **UPTREND:** Higher highs AND higher lows
   - **DOWNTREND:** Lower highs AND lower lows
   - **NO TREND:** Ranging/choppy → USE HOLD
   - If no clear trend → DO NOT TRADE

2. **Step 2: Wait for Pullback Entry** (20-80% Retracement)
   - **UPTREND:** Enter on pullback (20-80% of last swing)
   - **DOWNTREND:** Enter on bounce (20-80% of last swing)
   - Example: $4000 → $4100 → pullback to $4050 → $4150 → pullback to $4100 = PERFECT ENTRY
   - Outside 20-80% range → USE HOLD

3. **Step 3: Stop-Loss at Last Swing Point** (CRITICAL)
   - **UPTREND:** Stop at last swing LOW (5-20 dollars below)
   - **DOWNTREND:** Stop at last swing HIGH (5-20 dollars above)
   - Example: Uptrend with last low at $4050 → Stop at $4045
   - **Stop Distance Constraints:**
     - Minimum: 0.40% from entry
     - Maximum: 2.90% from entry
   - Outside range → USE HOLD

4. **Step 4: Target at Next Structure Level**
   - **UPTREND:** Target slightly above last swing HIGH
   - **DOWNTREND:** Target slightly below last swing LOW
   - Example: Last high $4150 → Target $4160
   - **Risk-Reward Ratio:**
     - Minimum: 0.5:1 (risk $400 to make $200)
     - Maximum: 3:1 (risk $200 to make $600)
   - Outside range → USE HOLD

**CRITICAL RULES:**
- ✅ ONLY trade WITH the trend
- ❌ NEVER trade counter-trend
- ❌ NEVER trade without clear trend
- ❌ NEVER trade outside 20-80% pullback zone
- If ANY doubt → USE HOLD

### Response Parsing & Error Handling

**Defensive Parsing (Added 2025-10-12):**
- `parse_llm_response()` validates that `analysis` is always a string
- If ChatGPT returns unexpected format (e.g., dict instead of string), auto-converts
- `send_to_discord()` has additional type checking as fallback
- Logs warnings when unexpected formats detected
- Prevents `TypeError: unsupported operand type(s) for +=: 'dict' and 'str'`
- If parsing completely fails, defaults to HOLD signal with 0% confidence

**Why it matters:**
- ChatGPT occasionally returns malformed responses
- Bot continues running instead of crashing
- GitHub Actions workflow remains stable

### Trade Level Validation

Before executing any trade, the bot validates ALL of these criteria:

1. **Direction Check:**
   - For LONG trades: stop_loss < entry_price < take_profit
   - For SHORT trades: take_profit < entry_price < stop_loss

2. **Stop Distance Constraints:**
   - Minimum: 0.30% from entry
   - Maximum: 1.90% from entry
   - Example rejection: Stop 0.05% away → "Stop too tight: 0.05% (minimum 0.30%)"

3. **Target Distance Constraints:**
   - Minimum: 0.30% from entry
   - Maximum: 1.90% from entry

4. **Risk-Reward Ratio:**
   - Minimum: 0.5:1 (risk $400 to make $200) - aka 1:2 ratio
   - Maximum: 3:1 (risk $200 to make $600)
   - Any ratio in range is valid: 0.65:1, 1.2:1, 2.5:1, etc.
   - Example rejection: 0.3:1 ratio → "Risk-reward too low: 0.30:1 (minimum 0.5:1)"

5. **Volume Conditions:**
   - Average volume of last 10 candles > 100
   - At least 7 out of 10 candles with volume > 20
   - Example rejection: `"Volume too low to open LONG: avg volume 18.9 ≤ 100 AND only 3/10 candles > 20 volume (need 7+)"`

If ANY validation fails:
- Trade is rejected and not executed
- Error message appears in Discord
- Discord shows "⚠️ Trade Rejected" warning
- **Chart displays "INVALID TRADE" text** (red box overlay)
- Bot prevents bad trades even if ChatGPT generates them
- **If in opposite position:** Closes existing position but doesn't open new invalid trade

### Position Management Logic

State machine prevents duplicates and handles direction changes:

| Current Status | New Signal | Validation | Volume Check | Action |
|----------------|------------|------------|--------------|--------|
| None | BUY | Valid | Pass | Open Long + place stop/TP orders |
| None | BUY | Valid | Fail | Do nothing (show volume error) |
| None | BUY | Invalid | N/A | Do nothing (show validation error) |
| None | SELL | Valid | Pass | Open Short + place stop/TP orders |
| None | SELL | Valid | Fail | Do nothing (show volume error) |
| None | SELL | Invalid | N/A | Do nothing (show validation error) |
| None | HOLD | N/A | N/A | Do nothing |
| Long | BUY | N/A | N/A | Hold (place missing stop/TP if needed) |
| Long | SELL | Valid | Pass | Close Long → Cancel orders → Open Short |
| Long | SELL | Valid | Fail | Close Long → No position |
| Long | SELL | Invalid | N/A | Close Long → No position |
| Long | HOLD | N/A | N/A | Close Long → Cancel orders |
| Short | SELL | N/A | N/A | Hold (place missing stop/TP if needed) |
| Short | BUY | Valid | Pass | Close Short → Cancel orders → Open Long |
| Short | BUY | Valid | Fail | Close Short → No position |
| Short | BUY | Invalid | N/A | Close Short → No position |
| Short | HOLD | N/A | N/A | Close Short → Cancel orders |

**Key behavior:**
- Bot automatically places stop-loss and take-profit orders after opening position
- If holding and orders are missing (desync), bot re-places them
- When closing position, bot cancels all pending orders
- All stale orders cancelled before opening new position
- Volume check only applies to NEW positions (not closing existing ones)

---

## 🚨 Current Status

### ✅ Live Trading
- **Status:** Bot is actively trading with real money on Coinbase
- **Product:** ET-31OCT25-CDE (ETH Futures)
- **Automation:** GitHub Actions runs every 15 minutes
- **Model:** Time-based switching (gpt-5 6am-2pm, gpt-5-mini 2pm-6am Miami time)
- **Trading Stats:** 18 trades (10W/8L, 55.6% win rate)
- **Account Balance:** ~$192 (as of last check)

### 🎯 What's Working
- [x] Real Coinbase API integration
- [x] Limit/Market order execution (configurable)
- [x] Stop-loss and take-profit order placement
- [x] Position desync detection & auto-recovery
- [x] Order cancellation management
- [x] Real-time balance tracking
- [x] ChatGPT analysis integration with error handling
- [x] Discord notifications with charts (always shows which model was used)
- [x] GitHub Actions automation (15-min intervals)
- [x] Trade level validation (stop distance, R:R, direction)
- [x] Volume filtering (prevents low-volume trades)
- [x] Performance metrics tracking (Avg W:L, Win Rate)
- [x] Defensive response parsing (handles malformed ChatGPT responses)

### 🔧 Recent Improvements (2025-10-14)
- **NEW: Time-Based Model Switching:**
  - Dynamically switches between gpt-5 (6am-2pm Miami) and gpt-5-mini (2pm-6am)
  - Stays under OpenAI Tier 1-2 token limits (250K/day for gpt-5, 2.5M/day for gpt-5-mini)
  - Uses gpt-5 during peak trading hours for better reasoning
  - Model name always shown in Discord below "Position Updates" section
  - Bot runs every 15 minutes (96 runs/day)
  - Token calculation: gpt-5 = 32 runs × 7K = 224K ✓, gpt-5-mini = 64 runs × 7K = 448K ✓
- **MAJOR: Prompt Rewrite - Trend Following Only (2025-10-12):**
  - Removed false breakout and support/resistance strategies (causing confusion)
  - ChatGPT now ONLY trades trend following with pullbacks
  - Must identify clear trend first (higher highs/lows OR lower highs/lows)
  - Only enters on 20-80% pullbacks/bounces
  - NEVER trades counter-trend or in ranging markets
  - Stop MUST be at last swing point in trend direction
  - Target MUST be at next swing point (slightly beyond)
  - Uses HOLD if ANY doubt about trend
- **Volume Filtering:** Added `check_volume_conditions()` to filter low-volume periods
- **Error Handling:** Fixed TypeError when ChatGPT returns dict instead of string
- **Defensive Parsing:** Added type validation in `parse_llm_response()` and `send_to_discord()`
- **Configuration:** Adjusted MIN_DISTANCE_PERCENT to 0.40% and MAX_DISTANCE_PERCENT to 2.90%
- **CRITICAL FIX - Limit Order Management:**
  - Added `entry_order_id` tracking in positions.json
  - Fixed bug where unfilled entry limit orders were left active on exchange
  - Desync detection now cancels all orders (entry + stop + TP)
  - Bot checks if entry was actually filled before recording P/L
  - Prevents fake trade history from orders that never executed

### 🐛 Known Issues
- `positions.json` still has `paper_trading_balance` field (legacy, ignored - not worth removing)
- `main.py` is outdated (old paper trading version, not used - kept for reference)
- Futures contract expires Oct 31, 2025 - will need to update product ID before expiration

---

## 📌 Important Notes

### Live Trading - Real Money

**Current:** 100% live trading with real money on Coinbase Futures

**How it works:**
- Executes real limit/market orders via Coinbase Advanced API
- Places real stop-loss and take-profit orders
- Tracks actual positions on Coinbase
- Calculates profit/loss from actual fills
- Real money at risk

**Risk Management:**
- Start with small position sizes (1 contract = 0.1 ETH)
- Bot validates all trades before execution
- Volume filtering prevents illiquid trades
- Stop-loss orders always placed immediately
- Position size configurable in `CoinbaseMain.py`
- Distance constraints prevent extreme stops/targets

### Data Source

- **Exchange:** Coinbase Advanced Trade API
- **Product:** ET-31OCT25-CDE (ETH Futures)
- **Timeframe:** 1-minute candles
- **Amount:** Last 120 candles (2 hours of data)
- **Delay:** ~5-10 seconds (near real-time)

### Cost Breakdown

- **Data:** $0 (Coinbase Advanced API is free for market data)
- **Charts:** $0 (local generation with matplotlib)
- **ChatGPT:** $0 with OpenAI data sharing (Tier 1-2: 250K free gpt-5 tokens/day, 2.5M free gpt-5-mini tokens/day)
  - Time-based switching keeps usage under limits
  - 6am-2pm: gpt-5 (32 runs × 7K = 224K tokens)
  - 2pm-6am: gpt-5-mini (64 runs × 7K = 448K tokens)
- **Discord:** $0 (webhooks are free)
- **GitHub Actions:** $0 (public repo = unlimited minutes)
- **Trading Fees:** Coinbase futures trading fees (varies by volume tier)

**Total operational cost:** $0 per day (all free with data sharing program)

### Dependencies

```
requests==2.32.3
openai==1.58.1
python-dotenv==1.1.1
pandas==2.3.3
matplotlib==3.10.6
mplfinance==0.12.10b0
python-dateutil==2.9.0
pytz==2024.1
coinbase-advanced-py>=1.2.0
```

---

## 🔐 Security

### .env File (NEVER commit!)

```bash
OPENAI_API_KEY="sk-..."
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
COINBASE_API_KEY="organizations/..."
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
```

**API Key Setup:**
1. Create API keys at: https://portal.cdp.coinbase.com/access/api
2. Enable "Trade" and "View" permissions
3. Copy the FULL private key (including BEGIN/END lines)
4. Store in `.env` file

### .gitignore

Excludes: `.env`, `venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`

### GitHub Secrets

All API keys stored as GitHub Secrets (not visible in repo or logs).

---

## ⚠️ Trading Disclaimer

**This software involves real financial risk.**

- Cryptocurrency futures trading carries significant risk of loss
- You can lose more than your initial investment (leverage amplifies losses)
- Past performance does not guarantee future results
- Only trade with money you can afford to lose completely
- Currently trading live with real money on Coinbase
- Not financial advice - use at your own risk
- The bot executes trades automatically without human intervention
- Stop-loss orders may not prevent all losses (slippage, gap moves, etc.)
- Volume filtering reduces but doesn't eliminate execution risk

**By running this bot, you acknowledge:**
- You understand the risks of automated futures trading
- You are responsible for all trading decisions and outcomes
- The developers are not liable for any losses
- You have tested and understand how the bot works

---

**Maintained By:** Alejandro + Claude Code
**Version:** 4.5 (Time-Based Model Switching + 15-min Intervals + Token Optimization)
