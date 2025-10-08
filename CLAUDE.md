# BTC Automated Trading Bot - Project Documentation

## 📋 Project Overview

**Goal:** Automated cryptocurrency trading system that analyzes BTC price data, gets AI-powered trade recommendations, executes trades via exchange API, and sends notifications to Discord.

**Current Status:** ✅ Phase 1 Complete
- [x] Fetch BTC OHLCV data from Kraken public API
- [x] Send data to ChatGPT API for technical analysis
- [x] Generate professional candlestick charts with matplotlib
- [x] Send analysis + chart to Discord webhook
- [ ] Exchange API integration for automated trading
- [ ] Trade state management system
- [ ] GitHub Actions automation

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTOMATED TRADING FLOW                    │
└─────────────────────────────────────────────────────────────┘

1. FETCH DATA (Kraken API)
   └─> Last 30 x 1-minute BTC/USD candles (OHLCV)

2. GENERATE CHART (matplotlib/mplfinance)
   └─> Professional candlestick chart with volume

3. ANALYZE (ChatGPT API)
   ├─> Input: CSV price data
   ├─> Output 1: Human-readable analysis (Discord)
   └─> Output 2: Structured trade data (JSON for exchange API)

4. EXECUTE TRADES (Exchange API - NOT YET IMPLEMENTED)
   ├─> Place market/limit orders
   ├─> Set stop-loss orders
   └─> Set take-profit orders

5. MANAGE POSITIONS (positions.json)
   ├─> Track open trades
   ├─> Monitor for stop/TP hits
   └─> Calculate profit/loss

6. NOTIFY (Discord Webhook)
   ├─> Send analysis text
   ├─> Embed candlestick chart
   └─> Report trade execution results

7. AUTOMATE (GitHub Actions - NOT YET IMPLEMENTED)
   └─> Run every 30 minutes automatically
```

---

## 📁 Current File Structure

```
trading/
├── main.py                 # Main trading bot script
├── .env                    # API keys (NEVER commit to Git!)
├── venv/                   # Python virtual environment
├── positions.json          # Trade state storage (TO BE CREATED)
├── CLAUDE.md              # This file - project documentation
└── .github/
    └── workflows/
        └── trading-bot.yml # GitHub Actions config (TO BE CREATED)
```

---

## 🔧 Components Breakdown

### `main.py` - Current Implementation

#### 1. `fetch_btc_data()` ✅
- Fetches last 30 x 1-minute candles from Kraken public API
- Returns CSV format: Timestamp, Open, High, Low, Close, Volume
- **API:** `https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1`

#### 2. `generate_chart(data)` ✅
- Converts CSV data to pandas DataFrame
- Generates professional candlestick chart with volume bars
- Custom dark theme (TradingView-style)
- Returns BytesIO image object for Discord upload
- **Cost:** $0 (local generation)

#### 3. `analyze_with_llm(csv_data)` ✅
- Sends OHLCV data to ChatGPT API (gpt-4o-mini)
- Prompt asks for: patterns, support/resistance, buy/hold/sell recommendation
- Returns human-readable analysis text
- **Cost:** ~$0.00015 per request

#### 4. `send_to_discord(analysis, webhook_url, chart_image)` ✅
- Creates Discord embed with color-coded recommendation
- Attaches candlestick chart as image
- Timestamp and run ID tracking
- **Cost:** $0 (Discord webhooks are free)

#### 5. `main` execution ✅
- Orchestrates all functions
- Loads environment variables from `.env`
- Prints debug output to console

---

## 💾 Trade State Management Strategy

### Why NOT a Database?
- **Overkill:** Small amount of data (1-10 active positions max)
- **Simplicity:** JSON file is human-readable and easy to debug
- **Git tracking:** Commit history = trade audit log
- **Zero dependencies:** No database setup or hosting costs

### `positions.json` Structure

```json
{
  "active_trades": [
    {
      "trade_id": "ORDER123456",
      "timestamp": "2025-10-07T14:30:00Z",
      "pair": "BTC/USD",
      "action": "buy",
      "entry_price": 121500.0,
      "amount": 0.01,
      "stop_loss": 120000.0,
      "take_profit": 123000.0,
      "status": "open"
    }
  ],
  "trade_history": [
    {
      "trade_id": "ORDER123455",
      "timestamp": "2025-10-07T13:00:00Z",
      "pair": "BTC/USD",
      "action": "buy",
      "entry_price": 120000.0,
      "exit_price": 121000.0,
      "amount": 0.01,
      "profit_loss": 10.0,
      "status": "closed",
      "close_reason": "take_profit"
    }
  ],
  "last_updated": "2025-10-07T14:30:00Z"
}
```

### Trade Management Flow

**Each Script Run:**
1. Load `positions.json`
2. Check active trades via exchange API:
   - Has stop-loss been hit? → Close trade, calculate P/L, move to history
   - Has take-profit been hit? → Close trade, calculate P/L, move to history
   - Still open? → Keep monitoring
3. Get new ChatGPT recommendation
4. If recommendation = BUY/SELL and no conflicting position:
   - Place order via exchange API
   - Add to active_trades array
5. Save updated `positions.json`
6. Send Discord notification with current status

---

## 🏦 Exchange API Integration (TO BE IMPLEMENTED)

### Option 1: Coinbase Advanced Trade API ⭐ RECOMMENDED

**Pros:**
- Official Python SDK (`coinbase-advanced-py`)
- Clean, modern API
- Good for US users
- Well-documented

**Cons:**
- Higher fees than Kraken
- Fewer advanced order types

**Installation:**
```bash
pip install coinbase-advanced-py
```

**Example Code:**
```python
from coinbase.rest import RESTClient

client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)

# Place market buy order
order = client.market_order_buy(
    client_order_id="unique-id-123",
    product_id="BTC-USD",
    quote_size="50.00"  # $50 worth of BTC
)

# Place limit order with stop-loss
limit_order = client.limit_order_gtc_buy(
    client_order_id="unique-id-124",
    product_id="BTC-USD",
    base_size="0.01",  # 0.01 BTC
    limit_price="121500.00"
)

# Place stop-loss order
stop_loss = client.stop_limit_order_gtc_sell(
    client_order_id="unique-id-125",
    product_id="BTC-USD",
    base_size="0.01",
    limit_price="119900.00",
    stop_price="120000.00"  # Triggers at this price
)
```

**Required API Keys:**
- Create at: https://www.coinbase.com/settings/api
- Permissions needed: `trade`, `view`
- Store in `.env`: `COINBASE_API_KEY` and `COINBASE_API_SECRET`

### Option 2: Kraken API

**Pros:**
- Already using Kraken for price data
- Lower fees
- More order types (OCO, trailing stops)

**Cons:**
- API slightly more complex
- Unofficial Python libraries

**Installation:**
```bash
pip install python-kraken-sdk
```

**Example Code:**
```python
from kraken.spot import Trade, User

trade = Trade(key=API_KEY, secret=API_SECRET)

# Place market buy order
order = trade.create_order(
    ordertype="market",
    side="buy",
    pair="XBTUSD",
    volume="0.01"
)

# Place limit order with stop-loss (OCO)
order = trade.create_order(
    ordertype="limit",
    side="buy",
    pair="XBTUSD",
    volume="0.01",
    price="121500",
    close={
        "ordertype": "stop-loss-limit",
        "price": "119900",
        "price2": "120000"
    }
)
```

**Required API Keys:**
- Create at: https://www.kraken.com/u/security/api
- Permissions needed: `Query Funds`, `Create & Modify Orders`, `Query Open/Closed Orders`
- Store in `.env`: `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`

---

## 🤖 ChatGPT Prompt Updates (TO BE IMPLEMENTED)

### Current Prompt (Human-Readable Only)
```
You are a crypto TA expert. Analyze this BTC/USD 1m OHLCV data from the last 30 minutes:
{csv_data}
Identify key patterns (e.g., candlestick formations, support/resistance, momentum indicators like RSI/MACD).
Give a neutral recommendation: buy/hold/sell with risk level (low/medium/high) and stop-loss target. Be concise.
```

### Updated Prompt (Dual Output)
```
You are a crypto TA expert. Analyze this BTC/USD 1m OHLCV data from the last 30 minutes:
{csv_data}

Provide TWO outputs:

1. ANALYSIS (for Discord notification):
Identify key patterns, support/resistance, momentum indicators. Give a recommendation (buy/hold/sell)
with reasoning. Be concise and actionable.

2. TRADE_DATA (for automated execution):
Provide a JSON object with this EXACT structure:
{
  "action": "buy|sell|hold",
  "confidence": 0-100,
  "entry_price": <number>,
  "stop_loss": <number>,
  "take_profit": <number>,
  "position_size": 0.001-0.01,
  "reasoning": "<brief explanation>"
}

Rules:
- If action is "hold", set all prices to null
- Stop-loss should be 1-2% below entry for buys, above for sells
- Take-profit should be 2-4% above entry for buys, below for sells
- Position size based on confidence (higher = larger position)
- Use current market price from latest candle as reference
```

### Parsing ChatGPT Response
```python
import json
import re

def parse_llm_response(response_text):
    """Extract both human analysis and structured trade data"""

    # Split response into sections
    parts = response_text.split("TRADE_DATA")
    analysis = parts[0].replace("ANALYSIS", "").strip()

    # Extract JSON from trade data section
    json_match = re.search(r'\{[^}]+\}', parts[1], re.DOTALL)
    if json_match:
        trade_data = json.loads(json_match.group(0))
        return analysis, trade_data
    else:
        return analysis, None
```

---

## 🚀 GitHub Actions Automation (TO BE IMPLEMENTED)

### `.github/workflows/trading-bot.yml`

```yaml
name: BTC Trading Bot

on:
  schedule:
    # Run every 30 minutes
    - cron: '*/30 * * * *'
  workflow_dispatch:  # Allow manual trigger

jobs:
  trade:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.13'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt

    - name: Run trading bot
      env:
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        COINBASE_API_KEY: ${{ secrets.COINBASE_API_KEY }}
        COINBASE_API_SECRET: ${{ secrets.COINBASE_API_SECRET }}
      run: |
        python main.py

    - name: Commit updated positions
      run: |
        git config --global user.name 'Trading Bot'
        git config --global user.email 'bot@example.com'
        git add positions.json
        git diff --quiet && git diff --staged --quiet || git commit -m "Update positions $(date)"
        git push
```

### Setting Up GitHub Secrets

1. Go to repository **Settings** → **Secrets and variables** → **Actions**
2. Add secrets:
   - `OPENAI_API_KEY`
   - `DISCORD_WEBHOOK_URL`
   - `COINBASE_API_KEY` (or `KRAKEN_API_KEY`)
   - `COINBASE_API_SECRET` (or `KRAKEN_API_SECRET`)

### `requirements.txt` (TO BE CREATED)

```
requests==2.32.3
openai==1.58.1
python-dotenv==1.1.1
pandas==2.3.3
matplotlib==3.10.6
mplfinance==0.12.10b0
coinbase-advanced-py==1.4.1  # or python-kraken-sdk
```

---

## 📊 Risk Management & Safety

### 🛡️ Position Sizing Strategy

**Conservative Approach (RECOMMENDED):**
- **Max position size:** 1% of account balance per trade
- **Max concurrent positions:** 2-3
- **Daily loss limit:** 2% of account balance
- **Example:** $1000 account → max $10 per trade, stop trading after $20 daily loss

**Implementation:**
```python
def calculate_position_size(account_balance, confidence, max_risk_pct=0.01):
    """
    Calculate position size based on account balance and confidence

    Args:
        account_balance: Total USD in account
        confidence: 0-100 from ChatGPT
        max_risk_pct: Max % of account to risk (default 1%)

    Returns:
        BTC amount to trade
    """
    risk_amount = account_balance * max_risk_pct

    # Scale by confidence (50% confidence = 50% of max position)
    adjusted_risk = risk_amount * (confidence / 100)

    # Convert to BTC amount
    current_btc_price = get_current_price()
    btc_amount = adjusted_risk / current_btc_price

    return round(btc_amount, 8)  # BTC has 8 decimal places
```

### ⚠️ Safety Checks (MUST IMPLEMENT)

```python
def safety_checks(trade_data, account_balance):
    """Validate trade before execution"""

    # 1. Check daily loss limit
    if get_daily_loss() > account_balance * 0.02:
        return False, "Daily loss limit exceeded (2%)"

    # 2. Check position size
    if trade_data['position_size'] > account_balance * 0.01:
        return False, "Position size too large (>1% of account)"

    # 3. Check maximum open positions
    active_count = len(load_positions()['active_trades'])
    if active_count >= 3:
        return False, "Too many open positions (max 3)"

    # 4. Check stop-loss is set
    if trade_data['stop_loss'] is None:
        return False, "No stop-loss specified"

    # 5. Check risk/reward ratio
    entry = trade_data['entry_price']
    stop = trade_data['stop_loss']
    tp = trade_data['take_profit']

    risk = abs(entry - stop)
    reward = abs(tp - entry)

    if reward / risk < 1.5:  # Minimum 1.5:1 ratio
        return False, f"Risk/reward too low ({reward/risk:.2f}:1, need >1.5:1)"

    return True, "All checks passed"
```

### 🚨 Kill Switch

**Manual Override File:** `STOP_TRADING.txt`

```python
def should_trade():
    """Check if trading is allowed"""
    if os.path.exists('STOP_TRADING.txt'):
        print("❌ TRADING DISABLED - Remove STOP_TRADING.txt to resume")
        return False
    return True
```

**To pause trading:** Create file `STOP_TRADING.txt` in repo
**To resume trading:** Delete the file

---

## 📈 Testing Strategy

### Phase 1: Paper Trading (4-8 weeks) ⚠️ CRITICAL

**Never skip this step! Test with fake money first.**

**Setup:**
1. Use Coinbase Advanced Trade sandbox OR
2. Create separate JSON file `paper_positions.json`
3. Track "virtual" trades without real API calls
4. Calculate hypothetical P/L

**Metrics to Track:**
- Win rate (% of profitable trades)
- Average profit per trade
- Average loss per trade
- Maximum drawdown (largest peak-to-trough loss)
- Sharpe ratio (risk-adjusted returns)

**Success Criteria (before going live):**
- [ ] Win rate >50%
- [ ] Average win >1.5x average loss
- [ ] Maximum drawdown <10%
- [ ] 30+ completed trades
- [ ] Consistent performance over 4+ weeks

### Phase 2: Live Trading with Minimum Amounts

**Initial Live Testing:**
- Start with $50-100 account
- Minimum position sizes (0.001 BTC)
- Monitor closely for 2 weeks
- If successful, gradually scale up

### Phase 3: Full Production

**Only after:**
- Paper trading successful
- Small live trades profitable
- All safety systems tested
- Emergency procedures documented

---

## 🗺️ Implementation Roadmap

### ✅ Phase 1: Foundation (COMPLETE)
- [x] BTC data fetching
- [x] ChatGPT integration
- [x] Chart generation
- [x] Discord notifications

### 🔨 Phase 2: Trading Infrastructure (NEXT)

**Priority 1: Trade State Management**
- [ ] Create `positions.json` structure
- [ ] Write `load_positions()` function
- [ ] Write `save_positions()` function
- [ ] Write `update_position_status()` function

**Priority 2: Exchange API Selection**
- [ ] Decide: Coinbase vs Kraken
- [ ] Create exchange account
- [ ] Generate API keys
- [ ] Test API connection (read-only first)

**Priority 3: ChatGPT Prompt Enhancement**
- [ ] Update prompt for dual output (analysis + JSON)
- [ ] Write `parse_llm_response()` function
- [ ] Test prompt with various market conditions

### 🧪 Phase 3: Paper Trading (4-8 weeks)

**Priority 4: Mock Trading System**
- [ ] Create `execute_paper_trade()` function
- [ ] Track paper trades in separate JSON
- [ ] Calculate virtual P/L
- [ ] Generate performance reports

**Priority 5: Safety Systems**
- [ ] Implement position sizing calculator
- [ ] Add all safety checks
- [ ] Create kill switch mechanism
- [ ] Test edge cases (API failures, network issues)

### 🤖 Phase 4: Automation

**Priority 6: GitHub Actions**
- [ ] Create `requirements.txt`
- [ ] Write GitHub Actions workflow
- [ ] Set up secrets
- [ ] Test automated runs

### 🚀 Phase 5: Live Trading (After Extensive Testing)

**Priority 7: Go Live (CAUTIOUSLY)**
- [ ] Start with minimum amounts
- [ ] Monitor every trade manually
- [ ] Gradually increase position sizes
- [ ] Implement performance tracking

---

## 🔐 Security Best Practices

### Environment Variables
```bash
# .env file (NEVER commit to Git!)
OPENAI_API_KEY="sk-..."
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
COINBASE_API_KEY="..."
COINBASE_API_SECRET="..."
```

### .gitignore
```
.env
*.pyc
__pycache__/
venv/
.DS_Store
*.log
```

### API Key Permissions (Minimum Required)
**Coinbase:**
- `view` - Read account balance
- `trade` - Place/cancel orders
- ❌ NOT `transfer` or `withdraw`

**Kraken:**
- `Query Funds`
- `Query Open/Closed Orders`
- `Create & Modify Orders`
- ❌ NOT `Withdraw Funds`

---

## 📞 Support & Resources

### Official Documentation
- **Coinbase Advanced API:** https://docs.cdp.coinbase.com/advanced-trade/docs/welcome
- **Kraken API:** https://docs.kraken.com/
- **OpenAI API:** https://platform.openai.com/docs
- **Discord Webhooks:** https://discord.com/developers/docs/resources/webhook
- **GitHub Actions:** https://docs.github.com/en/actions

### Python Libraries
- **coinbase-advanced-py:** https://github.com/coinbase/coinbase-advanced-py
- **python-kraken-sdk:** https://github.com/btschwertfeger/python-kraken-sdk
- **openai:** https://github.com/openai/openai-python
- **mplfinance:** https://github.com/matplotlib/mplfinance

---

## 🎯 Current Focus

**IMMEDIATE NEXT STEPS:**
1. Choose exchange (Coinbase or Kraken)
2. Set up exchange account + API keys
3. Implement `positions.json` management
4. Update ChatGPT prompt for structured output
5. Build paper trading system

**DO NOT** implement real trading until paper trading proves profitable for 4+ weeks.

---

## 📝 Development Notes

### Known Issues
- First run requires matplotlib font cache build (~30 seconds)
- GitHub Actions has 6-hour max runtime (not an issue for 30min cron jobs)

### Future Enhancements
- Add more technical indicators (RSI, MACD, Bollinger Bands)
- Support multiple timeframes (5m, 15m, 1h)
- Add backtesting framework
- Web dashboard for monitoring
- Support multiple cryptocurrencies (ETH, SOL, etc.)
- Implement trailing stop-loss
- Add email notifications for critical events

---

## 📄 License & Disclaimer

⚠️ **TRADING DISCLAIMER:**

This software is for educational purposes only. Cryptocurrency trading carries significant risk of loss. Past performance does not guarantee future results. Only trade with money you can afford to lose. The authors are not responsible for any financial losses.

**By using this software, you acknowledge:**
- You understand the risks of automated trading
- You will test thoroughly with paper trading first
- You are responsible for all trades executed
- You will implement proper risk management
- You comply with all local regulations

---

## 🤖 GitHub Actions Deployment

### Setup (One-Time)

**Repository:** https://github.com/aapcssasha/ElBota (Public)

**Why Public:**
- Unlimited GitHub Actions minutes (private repos limited to 2,000 min/month)
- Bot runs every 15 minutes = ~2,880 min/month
- positions.json is visible but contains paper trading data only (not sensitive)

### Configuration

**1. Secrets (Required):**
Go to: https://github.com/aapcssasha/ElBota/settings/secrets/actions

Add these secrets:
- `OPENAI_API_KEY` - Your OpenAI API key
- `DISCORD_WEBHOOK_URL` - Your Discord webhook URL

**2. Workflow Permissions (Required):**
Go to: https://github.com/aapcssasha/ElBota/settings/actions

- Select: **"Read and write permissions"**
- This allows the bot to commit positions.json back to the repo

### How It Works

**Workflow File:** `.github/workflows/trading-bot.yml`

**Schedule:** Every 15 minutes (`cron: '*/15 * * * *'`)

**Workflow Steps:**
1. Checkout repository
2. Install Python 3.13
3. Install dependencies from requirements.txt
4. Run main.py with secrets as environment variables
5. Auto-commit positions.json with updated state
6. Push commit back to GitHub

**Result:** 96 commits per day (one every 15 minutes)

### Monitoring

**View Workflow Runs:**
https://github.com/aapcssasha/ElBota/actions

**Check Discord:**
Bot sends notification every 15 minutes with:
- Technical analysis
- Chart with entry/stop/target lines
- Position updates (opened/closed/holding)
- Paper trading statistics

**Check positions.json:**
Latest state visible in GitHub repo (auto-updated by bot)

### Running Locally + GitHub Sync

**Pull latest state before local run:**
```bash
cd /Users/alejandro/Documents/trading
git pull origin main  # Get latest positions.json from GitHub
python main.py        # Run locally
git add positions.json
git commit -m "Manual run"
git push              # GitHub Actions will use this on next run
```

**Note:** Rarely needed - just let GitHub Actions handle everything!

---

## 📊 Performance Metrics Explained

### Average Win/Loss Ratio (Avg W:L)

**What it shows:** Average dollar amount won per winning trade vs average dollar amount lost per losing trade

**Example:**
```
Trades: 4 (2W / 2L)
Win 1: +$84.11
Win 2: +$98.78
Loss 1: -$24.31
Loss 2: -$16.24

Avg Win = ($84.11 + $98.78) / 2 = $91.44
Avg Loss = ($24.31 + $16.24) / 2 = $20.28
Avg W:L = $91.44 / $20.28 = 4.51:1
```

**Interpretation:** For every $1 lost, the bot makes $4.51 on winning trades

**Why it's better than simple W:L count:**
- Shows actual profitability, not just win frequency
- A 3.0:1 ratio means you can have 25% win rate and still be profitable!
- Industry standard metric for trading systems

### Win Rate

**Formula:** (Winning Trades / Total Trades) × 100

**Example:** 50% means half of all trades are winners

**Note:** Win rate alone is misleading - you can have 90% win rate but lose money if your losses are huge!

### Paper Trading Balance

**Starting balance:** $10,000 (fake money)
**Updated:** After every trade based on profit/loss
**Purpose:** Test strategy performance before risking real money

**Next Steps:**
- Run for 30+ days
- If consistently profitable (Avg W:L > 2:1 and positive balance growth)
- Consider going live with small amounts on Coinbase

---

**Last Updated:** 2025-10-08
**Version:** 2.0 (GitHub Actions Deployed + Position Management)
**Maintained By:** Alejandro + Claude Code
**Repository:** https://github.com/aapcssasha/ElBota
