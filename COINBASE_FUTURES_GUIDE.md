# Coinbase ETH Futures Trading Bot - Quick Start Guide

## ✅ Setup Complete!

Your bot is now configured to trade **ETH Futures (ET-31OCT25-CDE)** on Coinbase.

---

## 📊 Current Configuration

**File:** `CoinbaseMain.py`

```python
FUTURES_PRODUCT_ID = "ET-31OCT25-CDE"  # ETH Futures (Oct 31, 2025)
CONTRACTS_PER_TRADE = 1  # Number of contracts per trade (0.1 ETH each)
TIMEFRAME_MINUTES = 120  # 2 hours of 1-minute candles
PAPER_TRADING = True  # ⚠️ CURRENTLY IN PAPER TRADING MODE
```

**Your Account:**
- 💰 Total Balance: **$200**
- 💪 Buying Power: **$195.70** (with leverage)
- 📦 Contract Size: **0.1 ETH** (~$437 per contract)
- 🎯 Max Contracts: **~4 contracts** (with margin)
- ✅ Recommended: **1-2 contracts** to leave buffer

---

## 🚀 How to Run

### Paper Trading (TEST MODE - Current Setting)
```bash
cd /Users/alejandro/Documents/trading
source venv/bin/activate
python3 CoinbaseMain.py
```

This will:
- ✅ Fetch real ETH futures prices
- ✅ Get ChatGPT analysis
- ✅ Simulate trades (no real money)
- ✅ Send results to Discord
- ✅ Track paper P/L

---

## 💰 Switch to LIVE TRADING

**⚠️ WARNING: This will trade REAL money on Coinbase!**

### Step 1: Open CoinbaseMain.py

```bash
nano CoinbaseMain.py
# or use your favorite editor
```

### Step 2: Change Line 27

Find this line:
```python
PAPER_TRADING = True  # ⚠️ SET TO True FOR TESTING, False FOR REAL TRADING
```

Change to:
```python
PAPER_TRADING = False  # ⚠️ SET TO True FOR TESTING, False FOR REAL TRADING
```

### Step 3: Save and Run

```bash
python3 CoinbaseMain.py
```

You'll see:
```
⚠️  ⚠️  ⚠️  WARNING: LIVE TRADING MODE ENABLED ⚠️  ⚠️  ⚠️
This bot will execute REAL trades with REAL money!
```

---

## 🎛️ Adjusting Position Size

If you want to trade more or fewer contracts, edit line 24:

```python
CONTRACTS_PER_TRADE = 1  # Change this number (1-4 recommended)
```

**Position Sizing Guide:**
- **1 contract** = ~$43.77 margin (conservative, recommended to start)
- **2 contracts** = ~$87.54 margin
- **3 contracts** = ~$131.31 margin
- **4 contracts** = ~$175.08 margin (close to max with $195.70 buying power)

---

## 📈 Monitoring

### Check Your Trades

1. **Discord:** You'll get notifications with:
   - Chart with entry/stop/target levels
   - Trade analysis from ChatGPT
   - Position updates
   - P/L tracking

2. **Coinbase Platform:**
   - Go to: https://www.coinbase.com/advanced-trade/futures/ET-31OCT25-CDE
   - View your open positions
   - Check P/L in real-time

3. **positions.json file:**
   - Stores current position state
   - Trade history
   - Paper trading stats

---

## 🛡️ Safety Features

The bot includes multiple safety checks:

1. **Trade Validation:**
   - ✅ Stop distance: 0.10% - 0.50% from entry
   - ✅ Risk-reward ratio: 0.5:1 to 3:1
   - ✅ Direction check (stop < entry < target for LONG)

2. **Invalid Trade Protection:**
   - ❌ Rejects trades that fail validation
   - ❌ Won't open positions with bad levels
   - ❌ Shows "INVALID TRADE" on chart if rejected

3. **Stop-Loss & Take-Profit:**
   - ✅ Automatically checks if hit (analyzes candle highs/lows)
   - ✅ Closes positions when levels are touched
   - ✅ No need to manually monitor

---

## 🔄 Automated Running (Optional)

If you want to run this automatically every 15 minutes like the BTC bot:

1. **Option A: Cron Job (Mac/Linux)**
   ```bash
   # Edit crontab
   crontab -e

   # Add this line (runs every 15 minutes)
   */15 * * * * cd /Users/alejandro/Documents/trading && source venv/bin/activate && python3 CoinbaseMain.py >> bot.log 2>&1
   ```

2. **Option B: Keep GitHub Actions**
   - You'd need to commit CoinbaseMain.py to your repo
   - Update the workflow to run this file
   - (Not recommended initially - test manually first!)

---

## 📝 Testing Checklist Before Going Live

Before switching to `PAPER_TRADING = False`:

- [ ] **Run bot 3-5 times in paper mode** - Make sure it fetches data correctly
- [ ] **Verify Discord messages** - Charts show correctly, analysis makes sense
- [ ] **Check different signals** - BUY, SELL, HOLD all work
- [ ] **Review trade validation** - Invalid trades are rejected properly
- [ ] **Understand risk** - 1 contract = 0.1 ETH = ~$437 notional exposure
- [ ] **Set reasonable stop** - Bot uses 0.10%-0.50% stops (safe for scalping)
- [ ] **Start with 1 contract** - Don't use full buying power initially

---

## ⚠️ Important Notes

1. **Contract Expiration:** ET-31OCT25-CDE expires **October 31, 2025**
   - You have plenty of time
   - No need to roll over for months

2. **Price Differences:**
   - Futures price ≠ Spot price
   - Usually very close (~$4,377 futures vs $4,354 spot)
   - This is normal (called "basis")

3. **Leverage Risk:**
   - You're trading with 10x leverage built-in
   - Small price moves = big P/L swings
   - **Use stop-losses** (bot does this automatically)

4. **Liquidation:**
   - Your account shows "liquidation buffer: 1000%"
   - This means you're very safe from liquidation
   - But still use stops to protect capital

5. **Paper vs Live:**
   - Paper trading tracks simulated P/L in positions.json
   - Live trading executes real orders on Coinbase
   - Both use the SAME signals from ChatGPT

---

## 🆘 Troubleshooting

### "Error fetching data"
- Check internet connection
- Verify API keys are still valid
- Make sure ET-31OCT25-CDE still exists (check Coinbase)

### "Trade execution failed"
- Check your buying power (might be used up)
- Verify you have funds in futures account
- Check if you have open position already

### "Invalid trade levels"
- This is GOOD - bot rejected a bad signal
- ChatGPT's levels didn't meet safety criteria
- Bot will try again next run

### Discord not receiving messages
- Check `DISCORD_WEBHOOK_URL` in .env
- Test webhook manually
- Verify webhook hasn't been deleted

---

## 📞 Quick Commands

```bash
# Run bot once
python3 CoinbaseMain.py

# Check current position
python3 test_futures_product.py

# View paper trading history
cat positions.json

# Check bot logs (if running via cron)
tail -f bot.log
```

---

## 🎯 Success Metrics to Track

Before going fully live, track these over 1-2 weeks:

- **Win Rate:** Aim for > 40%
- **Avg W:L Ratio:** Aim for > 1.5:1
- **Consistency:** Positive days > negative days
- **Max Drawdown:** Stay below 20% of account

Your paper trading already shows:
- ✅ 57.3% win rate
- ✅ 1.51:1 avg W:L ratio
- ✅ $12,294 balance (up from $10,000)

These are GOOD numbers! But remember: futures ≠ spot, so test with futures data first.

---

**Good luck, and trade safely! 🚀**

Remember: Start with paper trading, then 1 contract live, then scale up if profitable.
