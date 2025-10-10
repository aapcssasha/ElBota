"""
Test script to verify ET-31OCT25-CDE futures product access
"""

from coinbase.rest import RESTClient
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# The futures product you're trading
FUTURES_PRODUCT_ID = "ET-31OCT25-CDE"

print("=" * 70)
print("🔍 TESTING ETH FUTURES PRODUCT ACCESS")
print("=" * 70)

try:
    client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)

    # Test 1: Get specific product info
    print(f"\n1️⃣ Fetching product info for {FUTURES_PRODUCT_ID}...")
    try:
        product = client.get_product(FUTURES_PRODUCT_ID)
        print(f"✅ Product found!")
        print(f"   Product ID: {getattr(product, 'product_id', 'N/A')}")
        print(f"   Product Type: {getattr(product, 'product_type', 'N/A')}")
        print(f"   Status: {getattr(product, 'status', 'N/A')}")
        print(f"   Base Currency: {getattr(product, 'base_currency_id', 'N/A')}")
        print(f"   Quote Currency: {getattr(product, 'quote_currency_id', 'N/A')}")

        # Try to get price
        price = getattr(product, 'price', None)
        if price:
            print(f"   Current Price: ${price}")
    except Exception as e:
        print(f"❌ Could not fetch product: {e}")

    # Test 2: Get candles (price history)
    print(f"\n2️⃣ Fetching recent candles for {FUTURES_PRODUCT_ID}...")
    try:
        import time
        end_time = int(time.time())
        start_time = end_time - (60 * 60)  # Last 60 minutes

        candles = client.get_candles(
            product_id=FUTURES_PRODUCT_ID,
            start=str(start_time),
            end=str(end_time),
            granularity="ONE_MINUTE"
        )

        candles_list = getattr(candles, 'candles', [])
        if candles_list and len(candles_list) > 0:
            print(f"✅ Got {len(candles_list)} candles")

            # Show most recent candle
            latest = candles_list[0]
            print(f"   Latest candle:")
            print(f"     Open: ${getattr(latest, 'open', 'N/A')}")
            print(f"     High: ${getattr(latest, 'high', 'N/A')}")
            print(f"     Low: ${getattr(latest, 'low', 'N/A')}")
            print(f"     Close: ${getattr(latest, 'close', 'N/A')}")
            print(f"     Volume: {getattr(latest, 'volume', 'N/A')}")
        else:
            print("⚠️ No candles returned")
    except Exception as e:
        print(f"❌ Could not fetch candles: {e}")
        import traceback
        traceback.print_exc()

    # Test 3: Get your account balances
    print(f"\n3️⃣ Checking account balances...")
    try:
        accounts = client.get_accounts()
        accounts_list = getattr(accounts, 'accounts', [])

        print("   Balances with funds:")
        total_usd = 0
        for account in accounts_list:
            currency = getattr(account, 'currency', '???')
            available_bal = getattr(account, 'available_balance', None)

            if available_bal:
                available = float(getattr(available_bal, 'value', 0))
                if available > 0:
                    print(f"     {currency}: {available:.8f} available")

                    # Rough USD conversion (assume stablecoins = $1)
                    if currency in ['USD', 'USDC', 'USDT']:
                        total_usd += available

        print(f"\n   💰 Total USD-equivalent: ~${total_usd:.2f}")
        print(f"   💪 With 10x leverage: ~${total_usd * 10:.2f} buying power")
    except Exception as e:
        print(f"❌ Could not fetch balances: {e}")

    # Test 4: Get futures positions (if any exist)
    print(f"\n4️⃣ Checking for existing futures positions...")
    try:
        # Try to get futures positions
        # This endpoint might not exist or might be different
        positions = client.get_futures_balance_summary()
        print(f"   Futures balance summary: {positions}")
    except Exception as e:
        print(f"ℹ️  Could not fetch futures positions: {e}")
        print(f"   (This is OK - might just mean no positions or different API call needed)")

    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"\nProduct ID to use: {FUTURES_PRODUCT_ID}")
    print(f"Contract Size: 0.1 ETH (Nano Ether)")
    print(f"Expiration: October 31, 2025")
    print(f"\nNext step: Update CoinbaseMain.py to trade this futures contract")

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
