# BTC Trading Bot - Project Documentation

**Repository:** https://github.com/aapcssasha/ElBota (Public)
**Status:** 🧪 **PAPER TRADING ONLY** - Not live on Coinbase, testing with fake money
**Last Updated:** 2025-10-08

---

## 🎯 What This Bot Does

Automated BTC trading bot that:
1. Fetches BTC/USD 1-minute candles from Coinbase Exchange API (last 60 minutes)
2. Sends data to ChatGPT (gpt-4o-mini) for technical analysis
3. Gets trading recommendation (BUY/SELL/HOLD) with entry, stop-loss, and take-profit levels
4. Executes **paper trades** (simulated, no real money)
5. Manages positions (tracks opens/closes, checks if stop/target hit)
6. Generates candlestick charts with trading levels
7. Sends analysis + chart to Discord webhook
8. Runs automatically via GitHub Actions every 15 minutes

---

## 🏗️ How It Works

```
┌─────────────────────────────────────────────────────────┐
│              TRADING BOT FLOW (Every 15 min)            │
└─────────────────────────────────────────────────────────┘

1. LOAD STATE
   └─> positions.json (current position, trade history, balance)

2. FETCH DATA
   └─> Coinbase API: Last 60 x 1-min BTC/USD candles (OHLCV)

3. CHECK STOP/TARGET
   └─> Analyze candle highs/lows since entry time
   └─> If hit: close position, record P/L, update state

4. GET SIGNAL
   └─> ChatGPT analyzes data
   └─> Returns: action (buy/sell/hold), entry, stop, target, confidence

5. MANAGE POSITION
   └─> None + BUY → Open Long
   └─> None + SELL → Open Short
   └─> Long + BUY → Hold (already in)
   └─> Long + SELL → Close Long, Open Short
   └─> Long + HOLD → Close Long
   └─> Short logic (reversed)

6. GENERATE CHART
   └─> Candlestick + volume
   └─> Shows entry/stop/target lines
   └─> Times in Eastern Time (ET)

7. SEND TO DISCORD
   └─> Analysis text
   └─> Chart image
   └─> Position updates
   └─> Paper trading stats

8. SAVE STATE
   └─> positions.json updated
   └─> Auto-committed to GitHub
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `main.py` | Main bot script (all logic) |
| `positions.json` | State persistence (current position, history, balance) |
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
    "entry_price": 122000.00,
    "entry_time": "2025-10-08T01:30:40.144966",
    "stop_loss": 121500.00,
    "take_profit": 122500.00,
    "trade_id": "paper_1759887040",
    "action": "buy|sell"
  },
  "last_signal": "buy|sell|hold",
  "trade_history": [
    {
      "type": "long|short",
      "entry_price": 121500.00,
      "exit_price": 122000.00,
      "profit_loss": 500.00,
      "entry_time": "2025-10-08T00:00:00",
      "exit_time": "2025-10-08T01:00:00"
    }
  ],
  "paper_trading_balance": 10500.00,
  "total_trades": 10,
  "winning_trades": 6,
  "losing_trades": 4
}
```

**Important:** GitHub Actions auto-commits this file every 15 minutes to persist state between runs.

---

## 🤖 GitHub Actions Automation

**Runs:** Every 15 minutes (`cron: '*/15 * * * *'`)
**Platform:** ubuntu-latest with Python 3.13

### Workflow Steps:
1. Checkout repo
2. Install dependencies (`requirements.txt`)
3. Run `main.py` with secrets
4. Auto-commit `positions.json` with updated state
5. Push to GitHub

### Required Secrets:
- `OPENAI_API_KEY` - ChatGPT API
- `DISCORD_WEBHOOK_URL` - Discord notifications

### Permissions:
- **"Read and write permissions"** enabled (Settings → Actions → Workflow permissions)
- Allows bot to commit positions.json

### Monitoring:
- **Workflow runs:** https://github.com/aapcssasha/ElBota/actions
- **Discord channel:** Gets notification every 15 minutes
- **positions.json:** Check GitHub for latest state

---

## 🔨 Development Workflow

**⚠️ CRITICAL: ALWAYS FOLLOW THIS WORKFLOW**

```bash
# 1. PULL FIRST (positions.json is updated by GitHub Actions!)
git pull

# 2. Make changes to code
# Edit main.py, etc.

# 3. Test locally (optional)
source venv/bin/activate
python3 main.py

# 4. Commit and push
git add <files>
git commit -m "Description"
git push
```

**Why pull first?**
- GitHub Actions commits positions.json every 15 minutes
- If you don't pull, you'll have merge conflicts
- Always sync before making changes

---

## 📊 Performance Metrics

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

### Paper Trading Balance

- **Starting:** $10,000 (fake money)
- **Current:** Updated after every trade
- **Purpose:** Test strategy before risking real money

**Success Criteria (before going live):**
- Avg W:L > 2:1
- Win Rate > 40%
- 30+ trades completed
- 30+ days of consistent performance
- Positive balance growth

---

## 🔧 Important Implementation Details

### Stop-Loss and Take-Profit Detection

**Method:** Checks candle highs/lows chronologically (not just current price)

- **For LONG:** Check each candle's **high** for take-profit, then **low** for stop-loss
- **For SHORT:** Check each candle's **low** for take-profit, then **high** for stop-loss
- **Timeframe:** Only checks candles after entry_time
- **Order matters:** Checks target first, then stop, in chronological order by candle
- **Why:** Catches targets/stops hit between 15-minute runs and respects price action order

**Example:** Entered long at $122,000 with target $122,200. If any candle between entry and now had high ≥ $122,200, target is hit (even if current price is $122,100).

**Recent fix:** Updated to check chronologically (candle by candle) rather than checking all highs then all lows. This ensures if both target and stop are hit in the same candle, the one that would have been hit first based on price movement is recorded.

### Chart Timezone

- **Data source:** Coinbase returns UTC timestamps
- **Display:** Converted to Eastern Time (America/New_York)
- **Why:** User is in ET, chart should match local time

### ChatGPT Prompt Strategy

- **Model:** gpt-4o-mini (cheap, fast)
- **Context:** 60 minutes of 1-min candles (OHLCV data)
- **Focus:** SHORT-TERM SCALPING with strong technical levels
- **Output:** Dual format
  1. Human-readable analysis (for Discord)
  2. Structured JSON (action, entry, stop, target, confidence)

**Trading Framework:**

1. **Strong Support/Resistance Zones**
   - Levels tested 2+ times
   - Price consolidation areas
   - High volume zones
   - These become stop-loss and take-profit targets

2. **False Breakout Detection** (High priority)
   - Price breaks strong level then quickly reverses (3-5 candles)
   - Trade the reversal direction
   - Example: Break above resistance → drops back → SELL signal

3. **Wave Trading / Trend Following** (Preferred for trends)
   - Identify market waves (higher highs/lows or lower highs/lows)
   - Enter on 50% retracements of previous swing
   - Uptrend: Buy on pullbacks
   - Downtrend: Sell on bounces

4. **Stop-Loss Placement** (Primary step)
   - After determining direction, find the STRONGEST pivot from FULL 60-minute data
   - Look through ALL 60 candles, not just last 5-10 candles
   - For LONG: Most significant swing low or support (tested 2+ times, clear structure)
   - For SHORT: Most significant swing high or resistance (tested 2+ times, clear structure)
   - Place stop 5-20 dollars beyond this pivot
   - **Stop Distance Constraints:**
     - Minimum: $80 (prevents overly tight stops)
     - Maximum: $500 (keeps stops reasonable)
     - If nearest pivot is <$80 away, find next major pivot
     - If all pivots >$500 away, use "hold"

5. **Target Calculation** (Based on stop distance)
   - Calculate risk distance: |entry - stop|
   - Target = 2x to 3x the risk distance
   - Ratio range: 2:1 to 3:1 reward-to-risk
   - Choose multiplier based on next significant level
   - If no good target exists → use "hold"

### Trade Level Validation

Before executing any trade, the bot validates ALL of these criteria:

1. **Direction Check:**
   - For LONG trades: stop_loss < entry_price < take_profit
   - For SHORT trades: take_profit < entry_price < stop_loss

2. **Stop Distance Constraints:**
   - Minimum: $80 (prevents overly tight stops)
   - Maximum: $500 (keeps stops reasonable)
   - Example rejection: Stop $2 away → "Stop too tight: $2.13 (minimum $80)"

3. **Risk-Reward Ratio:**
   - Minimum: 2:1 (risk $100 to make $200+)
   - Maximum: 3:1 (risk $100 to make $300)
   - Example rejection: 28:1 ratio with $2 stop → "Stop too tight"

If ANY validation fails:
- Trade is rejected and not executed
- Error message appears in Discord
- Discord shows "⚠️ Trade Rejected" instead of invalid levels
- Bot prevents bad trades even if ChatGPT generates them

### Position Management Logic

State machine prevents duplicates:

| Current Status | New Signal | Action |
|----------------|------------|--------|
| None | BUY | Open Long |
| None | SELL | Open Short |
| None | HOLD | Do nothing |
| Long | BUY | Hold (already in) |
| Long | SELL | Close Long → Open Short |
| Long | HOLD | Close Long |
| Short | SELL | Hold (already in) |
| Short | BUY | Close Short → Open Long |
| Short | HOLD | Close Short |

---

## 🚨 Current Status & Next Steps

### ✅ Completed
- [x] Data fetching from Coinbase
- [x] ChatGPT integration
- [x] Chart generation with trading levels
- [x] Discord notifications
- [x] Paper trading system
- [x] Position management
- [x] Stop/target detection (candle-based)
- [x] GitHub Actions automation
- [x] Performance metrics tracking
- [x] Trade level validation (prevents inverted stops/targets)

### 🧪 In Progress - Paper Trading Results
**Current Stats (as of 2025-10-08):**
- ✅ **42 trades** completed (exceeds 30+ goal)
- ✅ **59.5% win rate** (25W/17L) - exceeds 40% goal
- ✅ **$10,901.69 balance** (+$901.69 profit, +9.02% gain)
- ⏳ **Avg W:L ratio:** Being calculated from trade history
- ⏳ **Running time:** Need 30+ days of consistent performance

**Status:** Strategy is performing well. Need more time to validate consistency before going live.

### 🚀 Future (After Successful Backtesting)
- [ ] **Go live on Coinbase** - Start with small amounts ($50-100)
- [ ] **Real money trading** - Only if paper trading proves consistently profitable

---

## 📌 Important Notes

### Paper Trading vs Live Trading

**Current:** 100% paper trading (fake money, no real trades on Coinbase)

**How it works:**
- Simulates trades based on ChatGPT signals
- Tracks positions in `positions.json`
- Calculates profit/loss as if trades were real
- No actual API calls to Coinbase trading endpoints
- No real money at risk

**When to go live:**
- After 30+ days of profitable paper trading
- Avg W:L ratio consistently > 2:1
- Win rate > 40%
- Understand all edge cases and risks

### Data Source

- **Exchange:** Coinbase Exchange API (free, public endpoint)
- **Pair:** BTC-USD
- **Timeframe:** 1-minute candles
- **Amount:** Last 60 candles (1 hour of data)
- **Delay:** ~20 seconds (nearly real-time)

### Cost Breakdown

- **Data:** $0 (Coinbase public API is free)
- **Charts:** $0 (local generation with matplotlib)
- **ChatGPT:** ~$0.00015 per run (gpt-4o-mini)
- **Discord:** $0 (webhooks are free)
- **GitHub Actions:** $0 (public repo = unlimited minutes)

**Total cost:** ~$0.01 per day (96 runs × $0.00015)

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
```

---

## 🔐 Security

### .env File (NEVER commit!)

```bash
OPENAI_API_KEY="sk-..."
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

### .gitignore

Excludes: `.env`, `venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`

### GitHub Secrets

All API keys stored as GitHub Secrets (not visible in repo or logs).

---

## ⚠️ Trading Disclaimer

**This software is for educational purposes only.**

- Cryptocurrency trading carries significant risk
- Past performance does not guarantee future results
- Only trade with money you can afford to lose
- Currently in paper trading phase (no real money)
- Not financial advice

---

**Maintained By:** Alejandro + Claude Code
**Version:** 3.0 (Paper Trading + GitHub Actions Deployed)
