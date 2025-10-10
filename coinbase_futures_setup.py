"""
Coinbase Futures Setup Helper (Updated for Cloud API)
This script helps you:
1. Test API credentials
2. Find available ETH futures products
3. Check account balance
"""

from coinbase.rest import RESTClient
from dotenv import load_dotenv
import os
import json

load_dotenv()

# Get credentials from .env
API_KEY = os.getenv("COINBASE_API_KEY", "")
API_SECRET = os.getenv("COINBASE_API_SECRET", "")


def test_credentials():
    """Test if API credentials are valid"""
    print("🔐 Testing API credentials...")

    if not API_KEY or not API_SECRET:
        print("❌ Missing API credentials in .env file!")
        print("\nPlease add to your .env file:")
        print("COINBASE_API_KEY=your_api_key_here")
        print("COINBASE_API_SECRET=your_api_secret_here")
        return None

    try:
        # Initialize Coinbase client
        client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)

        # Try to get accounts (simple auth test)
        accounts = client.get_accounts()

        print("✅ API credentials are valid!")
        return client
    except Exception as e:
        print(f"❌ API credentials failed: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure you created API keys at: https://portal.cdp.coinbase.com/access/api")
        print("2. Verify the API key has 'Trade' and 'View' permissions")
        print("3. Check that you copied the FULL private key (including BEGIN/END lines)")
        return None


def get_account_balance(client):
    """Get account balance"""
    print("\n💰 Fetching account balance...")

    try:
        accounts = client.get_accounts()

        print("\n📊 Account Balances:")
        # Handle accounts list
        accounts_list = accounts.accounts if hasattr(accounts, 'accounts') else []

        for account in accounts_list:
            currency = getattr(account, 'currency', '???')

            # Get available balance
            available_bal = getattr(account, 'available_balance', None)
            if available_bal:
                available = float(getattr(available_bal, 'value', 0))
            else:
                available = 0

            # Get hold balance
            hold_bal = getattr(account, 'hold', None)
            if hold_bal:
                hold = float(getattr(hold_bal, 'value', 0))
            else:
                hold = 0

            if available > 0 or hold > 0:
                print(f"   {currency}: {available:.8f} available, {hold:.8f} on hold")
    except Exception as e:
        print(f"❌ Error getting balance: {e}")
        import traceback
        traceback.print_exc()


def list_futures_products(client):
    """List all available futures products"""
    print("\n📋 Fetching available futures products...")

    try:
        # Get all products
        products = client.get_products()

        # Get products list
        products_list = getattr(products, 'products', [])

        # Filter for ETH futures/perpetuals
        eth_futures = []
        all_futures = []

        for product in products_list:
            product_id = getattr(product, 'product_id', '')
            product_type = getattr(product, 'product_type', 'UNKNOWN')
            status = getattr(product, 'status', 'Unknown')

            # Check if it's a futures or perpetual product
            is_futures = (
                'FUTURE' in product_type.upper() or
                'PERP' in product_type.upper() or
                '-PERP' in product_id.upper() or
                'FUT' in product_id.upper()
            )

            if is_futures:
                all_futures.append((product_id, product_type, status))

                if 'ETH' in product_id.upper():
                    eth_futures.append((product_id, product_type, status))

        if eth_futures:
            print("\n🔮 ETH Futures Products:")
            for product_id, product_type, status in eth_futures:
                print(f"   • {product_id} ({product_type}) - Status: {status}")
        else:
            print("\n⚠️  No ETH futures products found")
            print("   Showing all available crypto products instead...\n")

        # If no futures found, show regular ETH products
        if not eth_futures:
            print("📊 ETH Spot Products:")
            count = 0
            for product in products_list:
                product_id = getattr(product, 'product_id', '')
                product_type = getattr(product, 'product_type', 'Unknown')

                if 'ETH' in product_id.upper() and 'USD' in product_id.upper():
                    print(f"   • {product_id} ({product_type})")
                    count += 1
                    if count >= 10:
                        break

        # Show all futures if any exist
        if all_futures:
            print(f"\n🌍 All Futures/Perpetual Products ({len(all_futures)} found):")
            for product_id, product_type, status in all_futures[:10]:
                print(f"   • {product_id} ({product_type}) - Status: {status}")

            if len(all_futures) > 10:
                print(f"   ... and {len(all_futures) - 10} more")

    except Exception as e:
        print(f"❌ Error getting products: {e}")
        import traceback
        traceback.print_exc()


def check_trading_permissions(client):
    """Check what trading permissions the API key has"""
    print("\n🔍 Checking API key permissions...")

    try:
        # Try to get current orders (requires trade permission)
        orders = client.list_orders()
        print("✅ API key has trading permissions!")

    except Exception as e:
        if "permission" in str(e).lower() or "unauthorized" in str(e).lower():
            print("⚠️  API key might not have trading permissions")
            print(f"   Error: {e}")
        else:
            print(f"ℹ️  Permission check: {e}")


def get_eth_price(client):
    """Get current ETH price for reference"""
    print("\n💵 Fetching current ETH price...")

    try:
        # Try ETH-USD spot first
        product = client.get_product("ETH-USD")
        print(f"   ETH-USD Spot: ${product.price}")

    except Exception as e:
        print(f"ℹ️  Could not fetch ETH price: {e}")


if __name__ == "__main__":
    print("=" * 70)
    print("🔧 COINBASE FUTURES SETUP HELPER")
    print("=" * 70)

    # Test credentials first
    client = test_credentials()

    if client:
        # Get balance
        get_account_balance(client)

        # Check permissions
        check_trading_permissions(client)

        # Get ETH price
        get_eth_price(client)

        # List products
        list_futures_products(client)

    print("\n" + "=" * 70)
    print("📝 NEXT STEPS:")
    print("=" * 70)
    print()
    print("1. If API test failed:")
    print("   → Create API keys at: https://portal.cdp.coinbase.com/access/api")
    print("   → Make sure to enable 'Trade' and 'View' permissions")
    print("   → Copy the FULL private key (including BEGIN/END lines)")
    print()
    print("2. If no futures products found:")
    print("   → Coinbase Advanced Trade might not show futures in product list")
    print("   → You may need to access Coinbase Derivatives separately")
    print("   → Check your account has futures enabled at: https://www.coinbase.com/derivatives")
    print()
    print("3. If you see ETH-PERP or other ETH futures:")
    print("   → Note the exact product_id")
    print("   → We'll use it in CoinbaseMain.py for real trading")
    print()
    print("4. Account balance shown:")
    print(f"   → You mentioned having ~$199 available")
    print("   → With 10x leverage, you can control ~$1,990 position size")
    print("   → We'll configure proper position sizing in the trading bot")
    print()
