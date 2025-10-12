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
import uuid  # For generating unique order IDs

# Load environment variables from .env file
load_dotenv()


# ============================================================================
# CONFIGURATION - Futures Trading Settings
# ============================================================================
FUTURES_PRODUCT_ID = "ET-31OCT25-CDE"  # ETH Futures (Oct 31, 2025)
CRYPTO_SYMBOL = "ETH"  # For display purposes
TIMEFRAME_MINUTES = 120  # How many minutes of data to fetch
CONTRACTS_PER_TRADE = 1  # Number of contracts to trade (0.1 ETH each)
CONTRACT_MULTIPLIER = 0.1  # 0.1 ETH per contract for nano ETH futures

# Order execution settings
ORDER_TYPE = "limit"  # "market" or "limit" - market is faster, limit avoids spread

# Stop/Target distance constraints (as percentage from entry)
MIN_DISTANCE_PERCENT = 0.40  # Minimum 0.10% distance (prevents overly tight stops)
MAX_DISTANCE_PERCENT = 2.90  # Maximum 0.50% distance (keeps stops reasonable)

# Derived values
CRYPTO_LOWER = CRYPTO_SYMBOL.lower()


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
                "action": None,
                "entry_order_id": None,  # ADDED: Track entry order ID for limit orders
                "stop_loss_order_id": None,
                "take_profit_order_id": None,
                "unrealized_pnl": None,
            },
            "last_signal": "hold",
            "trade_history": [],
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
        }
        with open(positions_file, "w") as f:
            json.dump(default_state, f, indent=2)
        return default_state

    with open(positions_file, "r") as f:
        return json.load(f)


def save_positions(positions_data):
    """Save position state to positions.json"""
    with open("positions.json", "w") as f:
        json.dump(positions_data, f, indent=2)


def check_stop_target(positions_data, csv_data):
    """Check if stop-loss or take-profit has been hit by analyzing candle highs/lows

    Returns:
        tuple: (should_close, reason, exit_price, orders_to_cancel)
    """
    pos = positions_data["current_position"]

    if pos["status"] == "none":
        return False, None, None, []

    # Parse CSV data to get candles
    lines = csv_data.strip().split("\n")[1:]  # Skip header
    candles = []
    for line in lines:
        parts = line.split(",")
        candles.append(
            {
                "timestamp": int(parts[0]),
                "high": float(parts[2]),
                "low": float(parts[3]),
            }
        )

    # Filter candles after entry_time
    from dateutil import parser

    entry_timestamp = int(parser.parse(pos["entry_time"]).timestamp())
    relevant_candles = [c for c in candles if c["timestamp"] >= entry_timestamp]

    # Prepare order IDs to cancel
    stop_order_id = pos.get("stop_loss_order_id")
    tp_order_id = pos.get("take_profit_order_id")

    # For LONG positions: check each candle chronologically
    if pos["status"] == "long":
        for candle in relevant_candles:
            # If target hit in this candle, return it and cancel stop order
            if pos["take_profit"] and candle["high"] >= pos["take_profit"]:
                orders_to_cancel = [stop_order_id] if stop_order_id else []
                return True, "target_hit", pos["take_profit"], orders_to_cancel

            # If stop hit in this candle, return it and cancel target order
            if pos["stop_loss"] and candle["low"] <= pos["stop_loss"]:
                orders_to_cancel = [tp_order_id] if tp_order_id else []
                return True, "stop_hit", pos["stop_loss"], orders_to_cancel

    # For SHORT positions: check each candle chronologically
    elif pos["status"] == "short":
        for candle in relevant_candles:
            # If target hit in this candle, return it and cancel stop order
            if pos["take_profit"] and candle["low"] <= pos["take_profit"]:
                orders_to_cancel = [stop_order_id] if stop_order_id else []
                return True, "target_hit", pos["take_profit"], orders_to_cancel

            # If stop hit in this candle, return it and cancel target order
            if pos["stop_loss"] and candle["high"] >= pos["stop_loss"]:
                orders_to_cancel = [tp_order_id] if tp_order_id else []
                return True, "stop_hit", pos["stop_loss"], orders_to_cancel

    return False, None, None, []


def execute_real_futures_trade(action, contracts, client, limit_price=None):
    """Execute a real futures trade on Coinbase

    Args:
        action: "open_long", "open_short", "close_long", "close_short"
        contracts: Number of contracts to trade
        client: Coinbase RESTClient instance
        limit_price: Optional limit price (for limit orders)

    Returns:
        dict: Trade result with details
    """
    result = {"success": False, "message": "", "profit_loss": 0}

    try:
        if action in ["open_long", "close_short"]:
            # BUY order (open long or close short)
            order_side = "BUY"
        elif action in ["open_short", "close_long"]:
            # SELL order (open short or close long)
            order_side = "SELL"
        else:
            result["message"] = f"❌ Unknown action: {action}"
            return result

        # Generate unique order ID
        client_order_id = str(uuid.uuid4())

        # Execute order based on ORDER_TYPE setting
        if ORDER_TYPE == "limit" and limit_price is not None:
            # LIMIT ORDER - avoids spread but may not fill immediately
            limit_price_rounded = int(round(limit_price))
            if order_side == "BUY":
                order = client.limit_order_gtc_buy(
                    client_order_id=client_order_id,
                    product_id=FUTURES_PRODUCT_ID,
                    base_size=str(contracts),
                    limit_price=str(limit_price_rounded),
                )
            else:  # SELL
                order = client.limit_order_gtc_sell(
                    client_order_id=client_order_id,
                    product_id=FUTURES_PRODUCT_ID,
                    base_size=str(contracts),
                    limit_price=str(limit_price_rounded),
                )
        else:
            # MARKET ORDER (default) - executes immediately but may have slippage
            if order_side == "BUY":
                order = client.market_order_buy(
                    client_order_id=client_order_id,
                    product_id=FUTURES_PRODUCT_ID,
                    base_size=str(contracts),
                )
            else:  # SELL
                order = client.market_order_sell(
                    client_order_id=client_order_id,
                    product_id=FUTURES_PRODUCT_ID,
                    base_size=str(contracts),
                )

        # Convert response object to dict
        order_dict = order.to_dict() if hasattr(order, "to_dict") else {}

        if order_dict.get("success", False):
            order_id = order_dict.get("success_response", {}).get("order_id", "unknown")

            # Fetch status separately
            try:
                status_resp = client.get_order(order_id=order_id)
                # Convert status response to dict
                status_resp_dict = (
                    status_resp.to_dict() if hasattr(status_resp, "to_dict") else {}
                )
                status_dict = (
                    status_resp_dict.get("order", {})
                    if status_resp_dict.get("success", False)
                    else {}
                )
                status = status_dict.get(
                    "status", "FILLED"
                )  # Market IOC usually FILLED
            except Exception as status_err:
                print(f"Warning: Could not fetch order status: {str(status_err)}")
                status = "FILLED"  # Assume for market orders

            result["success"] = True
            result["order_id"] = order_id
            result["message"] = (
                f"{'🟢' if order_side == 'BUY' else '🔴'} {action.replace('_', ' ').upper()} - {contracts} contract(s) | Order ID: {order_id[:8]}... | Status: {status}"
            )
        else:
            error_response = order_dict.get("error_response", {})
            error_msg = error_response.get(
                "message", error_response.get("error_details", "Unknown error")
            )
            print(f"Trade failed with error: {error_msg}")
            result["message"] = f"❌ Trade execution failed: {error_msg}"
            result["order_id"] = "failed"
            result["status"] = "failed"

    except Exception as e:
        error_str = str(e)
        print(f"Error details: {error_str}")
        result["message"] = f"❌ Trade execution failed: {error_str}"

    return result


def place_stop_loss_order(client, position_type, contracts, stop_price):
    """Place a stop-loss order on Coinbase

    Args:
        client: Coinbase RESTClient
        position_type: "long" or "short"
        contracts: Number of contracts
        stop_price: Stop-loss trigger price

    Returns:
        dict: Order result with order_id
    """
    try:
        client_order_id = str(uuid.uuid4())
        stop_price_rounded = int(round(stop_price))
        if position_type == "long":
            limit_price_rounded = (
                stop_price_rounded - 2
            )  # $2 buffer for better fill rate
        else:
            limit_price_rounded = (
                stop_price_rounded + 2
            )  # $2 buffer for better fill rate

        # For LONG: sell to close when price drops (stop below entry)
        # For SHORT: buy to close when price rises (stop above entry)

        if position_type == "long":
            # Stop-loss sells when price goes DOWN
            order = client.stop_limit_order_gtc_sell(
                client_order_id=client_order_id,
                product_id=FUTURES_PRODUCT_ID,
                base_size=str(contracts),
                limit_price=str(limit_price_rounded),  # Limit slightly below stop
                stop_price=str(stop_price_rounded),
                stop_direction="STOP_DIRECTION_STOP_DOWN",
            )
        else:  # short
            # Stop-loss buys when price goes UP
            order = client.stop_limit_order_gtc_buy(
                client_order_id=client_order_id,
                product_id=FUTURES_PRODUCT_ID,
                base_size=str(contracts),
                limit_price=str(limit_price_rounded),  # Limit slightly above stop
                stop_price=str(stop_price_rounded),
                stop_direction="STOP_DIRECTION_STOP_UP",
            )

        order_dict = order.to_dict() if hasattr(order, "to_dict") else {}

        # Extract order_id from nested success_response (same as market orders)
        if order_dict.get("success", False):
            order_id = order_dict.get("success_response", {}).get("order_id", None)
            if order_id:
                return {
                    "success": True,
                    "order_id": order_id,
                    "message": f"✅ Stop-loss order placed at ${stop_price_rounded}",
                }
            else:
                # Order API returned success but no order_id
                error_msg = order_dict.get("success_response", {}).get(
                    "error", "No order_id returned"
                )
                print(f"Stop-loss order issue: {error_msg}")
                return {
                    "success": False,
                    "order_id": None,
                    "message": f"❌ Stop-loss order failed: {error_msg}",
                }
        else:
            # Order failed
            error_response = order_dict.get("error_response", {})
            error_msg = error_response.get(
                "message", error_response.get("error_details", "Unknown error")
            )
            print(f"Stop-loss order failed: {error_msg}")
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ Stop-loss order failed: {error_msg}",
            }

    except Exception as e:
        print(f"Stop-loss exception: {e}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "order_id": None,
            "message": f"❌ Stop-loss order failed: {e}",
        }


def place_take_profit_order(client, position_type, contracts, target_price):
    """Place a take-profit order on Coinbase

    Args:
        client: Coinbase RESTClient
        position_type: "long" or "short"
        contracts: Number of contracts
        target_price: Take-profit limit price

    Returns:
        dict: Order result with order_id
    """
    try:
        client_order_id = str(uuid.uuid4())
        target_price_rounded = int(round(target_price))

        # For LONG: sell to close at limit price
        # For SHORT: buy to close at limit price

        if position_type == "long":
            # Take-profit sells at limit price
            order = client.limit_order_gtc_sell(
                client_order_id=client_order_id,
                product_id=FUTURES_PRODUCT_ID,
                base_size=str(contracts),
                limit_price=str(target_price_rounded),
            )
        else:  # short
            # Take-profit buys at limit price
            order = client.limit_order_gtc_buy(
                client_order_id=client_order_id,
                product_id=FUTURES_PRODUCT_ID,
                base_size=str(contracts),
                limit_price=str(target_price_rounded),
            )

        order_dict = order.to_dict() if hasattr(order, "to_dict") else {}

        # Extract order_id from nested success_response (same as market orders)
        if order_dict.get("success", False):
            order_id = order_dict.get("success_response", {}).get("order_id", None)
            if order_id:
                return {
                    "success": True,
                    "order_id": order_id,
                    "message": f"✅ Take-profit order placed at ${target_price_rounded}",
                }
            else:
                # Order API returned success but no order_id
                error_msg = order_dict.get("success_response", {}).get(
                    "error", "No order_id returned"
                )
                print(f"Take-profit order issue: {error_msg}")
                return {
                    "success": False,
                    "order_id": None,
                    "message": f"❌ Take-profit order failed: {error_msg}",
                }
        else:
            # Order failed
            error_response = order_dict.get("error_response", {})
            error_msg = error_response.get(
                "message", error_response.get("error_details", "Unknown error")
            )
            print(f"Take-profit order failed: {error_msg}")
            return {
                "success": False,
                "order_id": None,
                "message": f"❌ Take-profit order failed: {error_msg}",
            }

    except Exception as e:
        print(f"Take-profit exception: {e}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "order_id": None,
            "message": f"❌ Take-profit order failed: {e}",
        }


def cancel_pending_orders(client, order_ids):
    """Cancel specific pending orders

    Args:
        client: Coinbase RESTClient
        order_ids: List of order IDs to cancel
    """
    import time

    if not order_ids:
        return

    try:
        client.cancel_orders(order_ids=order_ids)
        print(f"   ✅ Cancelled {len([o for o in order_ids if o])} pending orders")
        # Small delay to ensure orders are fully cancelled before placing new ones
        time.sleep(0.5)  # 500ms delay
    except Exception as e:
        print(f"   ⚠️ Error cancelling orders: {e}")


def get_open_order_ids(client):
    """Get list of open order IDs for the futures product"""
    try:
        open_orders_resp = client.list_orders(
            product_id=FUTURES_PRODUCT_ID, order_status=["OPEN"]
        )
        # Extract orders list
        orders = (
            getattr(open_orders_resp, "orders", [])
            if hasattr(open_orders_resp, "orders")
            else open_orders_resp.get("orders", [])
            if isinstance(open_orders_resp, dict)
            else []
        )
        # Handle both dict and object types
        order_ids = []
        for order in orders:
            if isinstance(order, dict):
                order_id = order.get("order_id")
            else:
                order_id = getattr(order, "order_id", None)
            if order_id:
                order_ids.append(order_id)
        return order_ids
    except Exception as e:
        print(f"   ⚠️ Error listing open orders: {e}")
        return []


def cancel_all_open_orders(client):
    """Cancel all open orders for the futures product"""
    import time

    order_ids = get_open_order_ids(client)
    if order_ids:
        try:
            client.cancel_orders(order_ids=order_ids)
            print(f"   ✅ Cancelled {len(order_ids)} open orders")
            # Small delay to ensure orders are fully cancelled before placing new ones
            time.sleep(0.5)  # 500ms delay
        except Exception as e:
            print(f"   ⚠️ Error cancelling orders: {e}")


def get_current_futures_position(client):
    """Get current futures position from Coinbase

    Returns:
        dict: Position info (size, side, unrealized_pnl, etc.) or {"exists": None, "error": str} on failure
    """
    try:
        # Get futures positions
        positions = client.list_futures_positions()

        # Look for position in our futures product
        pos_list = (
            getattr(positions, "positions", [])
            if hasattr(positions, "positions")
            else positions.get("positions", [])
            if isinstance(positions, dict)
            else []
        )

        for position in pos_list:
            product_id = getattr(position, "product_id", "")
            if product_id == FUTURES_PRODUCT_ID:
                size = float(getattr(position, "number_of_contracts", 0))
                side = getattr(position, "side", "UNKNOWN")
                entry_price = float(getattr(position, "entry_vwap", 0))

                # FIXED: Safely handle unrealized_pnl as dict or fallback
                pnl_obj = getattr(position, "unrealized_pnl", {})
                if isinstance(pnl_obj, dict):
                    unrealized_pnl = float(pnl_obj.get("value", 0))
                else:
                    unrealized_pnl = 0.0

                return {
                    "exists": True,
                    "size": abs(size),
                    "side": side,  # "LONG" or "SHORT"
                    "entry_price": entry_price,
                    "unrealized_pnl": unrealized_pnl,
                }

        # No position found
        return {"exists": False, "size": 0, "side": None}

    except Exception as e:
        print(f"API error details: {e}")  # For debugging
        return {
            "exists": None,
            "error": str(e),
        }  # FIXED: Flag error instead of fake "no position"


def execute_trade(
    action, price, positions_data, stop_loss=None, take_profit=None, client=None
):
    """Execute trade - real trading only

    Args:
        action: Trade action (open_long, close_long, etc.)
        price: Execution price (approximate for P/L calc)
        positions_data: Position state data
        stop_loss: Stop loss level
        take_profit: Take profit level
        client: Coinbase client (required)

    Returns:
        dict: Trade result
    """
    # Real trading - execute order (market or limit based on ORDER_TYPE setting)
    result = execute_real_futures_trade(
        action, CONTRACTS_PER_TRADE, client, limit_price=price
    )

    # ✅ NEW: Place stop-loss and take-profit orders after opening position
    if result.get("success") and action in ["open_long", "open_short"]:
        position_type = "long" if action == "open_long" else "short"

        # FIXED: Store entry order ID for limit orders (so we can cancel it later if needed)
        positions_data["current_position"]["entry_order_id"] = result.get("order_id")

        # Place stop-loss order
        if stop_loss:
            print(f"   📍 Placing stop-loss order at ${stop_loss:,.2f}...")
            stop_result = place_stop_loss_order(
                client, position_type, CONTRACTS_PER_TRADE, stop_loss
            )
            result["message"] += f"\n   {stop_result['message']}"

            # Store stop-loss order ID in positions data
            if stop_result.get("success"):
                positions_data["current_position"]["stop_loss"] = stop_loss
                positions_data["current_position"]["stop_loss_order_id"] = (
                    stop_result.get("order_id")
                )
            else:
                print(
                    f"   ⚠️ WARNING: Stop-loss order failed to place - position has NO STOP PROTECTION!"
                )

        # Place take-profit order
        if take_profit:
            print(f"   🎯 Placing take-profit order at ${take_profit:,.2f}...")
            tp_result = place_take_profit_order(
                client, position_type, CONTRACTS_PER_TRADE, take_profit
            )
            result["message"] += f"\n   {tp_result['message']}"

            # Store take-profit order ID in positions data
            if tp_result.get("success"):
                positions_data["current_position"]["take_profit"] = take_profit
                positions_data["current_position"]["take_profit_order_id"] = (
                    tp_result.get("order_id")
                )
            else:
                print(
                    f"   ⚠️ WARNING: Take-profit order failed to place - position has NO TARGET!"
                )

        # Update positions data with entry info
        positions_data["current_position"]["status"] = position_type
        positions_data["current_position"]["entry_price"] = price
        positions_data["current_position"]["entry_time"] = datetime.now().isoformat()
        positions_data["current_position"]["unrealized_pnl"] = (
            0.0  # Initial for new position
        )

    # ✅ NEW: Cancel pending orders when closing position
    elif result.get("success") and action in ["close_long", "close_short"]:
        # Get order IDs from positions data
        entry_order_id = positions_data["current_position"].get("entry_order_id")
        stop_order_id = positions_data["current_position"].get("stop_loss_order_id")
        tp_order_id = positions_data["current_position"].get("take_profit_order_id")

        # Cancel any pending orders (including entry if limit order never filled)
        order_ids = [oid for oid in [entry_order_id, stop_order_id, tp_order_id] if oid]
        if order_ids:
            print(f"   🚫 Cancelling {len(order_ids)} pending orders...")
            cancel_pending_orders(client, order_ids)

        # Calculate P/L for real trading (in USD)
        entry_price = positions_data["current_position"].get("entry_price")
        if entry_price:
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            if action == "close_long":
                profit_loss = (price - entry_price) * multiplier
            else:  # close_short
                profit_loss = (entry_price - price) * multiplier

            # Update trade statistics
            positions_data["total_trades"] += 1
            if profit_loss > 0:
                positions_data["winning_trades"] += 1
                emoji = "✅"
            else:
                positions_data["losing_trades"] += 1
                emoji = "❌"

            # Add to trade history
            positions_data["trade_history"].append(
                {
                    "type": "long" if action == "close_long" else "short",
                    "entry_price": entry_price,
                    "exit_price": price,
                    "profit_loss": profit_loss,
                    "entry_time": positions_data["current_position"]["entry_time"],
                    "exit_time": datetime.now().isoformat(),
                }
            )

            # Update message with P/L
            result["message"] += f" | P/L: ${profit_loss:+,.2f}"
            result["message"] = result["message"].replace("CLOSED", f"{emoji} CLOSED")

        # In execute_trade function, after closing position, ensure order IDs are cleared:
        # (This part should already be in your code, but make sure it's like this)

        # Clear positions data (when closing)
        positions_data["current_position"] = {
            "status": "none",
            "entry_price": None,
            "entry_time": None,
            "stop_loss": None,
            "take_profit": None,
            "trade_id": None,
            "action": None,
            "entry_order_id": None,  # Clear entry order ID
            "stop_loss_order_id": None,  # Make sure these are cleared
            "take_profit_order_id": None,  # Make sure these are cleared
            "unrealized_pnl": None,
        }

        result["profit_loss"] = profit_loss if "profit_loss" in locals() else 0

    return result


def manage_positions(positions_data, trade_data, current_price, csv_data, client=None):
    """Manage positions based on current state and new signal"""
    results = []
    current_status = positions_data["current_position"]["status"]
    new_signal = trade_data.get("action", "hold") if trade_data else "hold"

    # Check if stop-loss or take-profit hit first (checks candle highs/lows)
    should_close, reason, exit_price, orders_to_cancel = check_stop_target(
        positions_data, csv_data
    )
    if should_close:
        # Cancel the other pending order
        if orders_to_cancel:
            print(
                f"   🚫 Cancelling {len(orders_to_cancel)} pending order(s) after {reason}..."
            )
            cancel_pending_orders(client, orders_to_cancel)

        if current_status == "long":
            result = execute_trade(
                "close_long", exit_price, positions_data, client=client
            )
            result["message"] += f" ({reason.replace('_', ' ').title()})"
            results.append(result)
            current_status = "none"  # Update for next logic
        elif current_status == "short":
            result = execute_trade(
                "close_short", exit_price, positions_data, client=client
            )
            result["message"] += f" ({reason.replace('_', ' ').title()})"
            results.append(result)
            current_status = "none"

    # Position management logic
    if current_status == "none":
        if new_signal == "buy":
            # Validate trade levels before executing
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append(
                    {
                        "success": False,
                        "message": f"⚠️ Invalid trade levels: {error_msg}",
                    }
                )
            else:
                # NEW: Check volume conditions before opening trade
                volume_ok, volume_msg = check_volume_conditions(csv_data)
                if not volume_ok:
                    results.append(
                        {
                            "success": False,
                            "message": f"⚠️ Volume too low to open LONG: {volume_msg}",
                        }
                    )
                else:
                    # Cancel any previous limit orders before new trade
                    cancel_all_open_orders(client)
                    result = execute_trade(
                        "open_long",
                        current_price,
                        positions_data,
                        trade_data.get("stop_loss"),
                        trade_data.get("take_profit"),
                        client=client,
                    )
                    results.append(result)
        elif new_signal == "sell":
            # Validate trade levels before executing
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append(
                    {
                        "success": False,
                        "message": f"⚠️ Invalid trade levels: {error_msg}",
                    }
                )
            else:
                # NEW: Check volume conditions before opening trade
                volume_ok, volume_msg = check_volume_conditions(csv_data)
                if not volume_ok:
                    results.append(
                        {
                            "success": False,
                            "message": f"⚠️ Volume too low to open SHORT: {volume_msg}",
                        }
                    )
                else:
                    # Cancel any previous limit orders before new trade
                    cancel_all_open_orders(client)
                    result = execute_trade(
                        "open_short",
                        current_price,
                        positions_data,
                        trade_data.get("stop_loss"),
                        trade_data.get("take_profit"),
                        client=client,
                    )
                    results.append(result)
        elif new_signal == "hold":
            # Cancel any lingering limit orders (e.g., unfilled entry orders from previous runs)
            cancel_all_open_orders(client)
            results.append(
                {"success": True, "message": "⚪ No position | Signal: HOLD"}
            )

    elif current_status == "long":
        if new_signal == "buy":
            # Calculate P/L from entry price and current price
            entry = positions_data["current_position"]["entry_price"]
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            pl = (current_price - entry) * multiplier if entry else 0
            positions_data["current_position"]["unrealized_pnl"] = pl
            results.append(
                {
                    "success": True,
                    "message": f"✅ Holding LONG (Entry: ${entry:,.2f}, Current P/L: ${pl:+,.2f})",
                }
            )
            # FIXED: Place missing stop/TP if None
            if positions_data["current_position"][
                "stop_loss_order_id"
            ] is None and trade_data.get("stop_loss"):
                print(
                    f"   📍 Placing missing stop-loss at ${trade_data['stop_loss']:.2f}..."
                )
                stop_result = place_stop_loss_order(
                    client, "long", CONTRACTS_PER_TRADE, trade_data["stop_loss"]
                )
                if stop_result.get("success"):
                    positions_data["current_position"]["stop_loss"] = trade_data[
                        "stop_loss"
                    ]
                    positions_data["current_position"]["stop_loss_order_id"] = (
                        stop_result.get("order_id")
                    )
                results[0]["message"] += f"\n   {stop_result['message']}"
            if positions_data["current_position"][
                "take_profit_order_id"
            ] is None and trade_data.get("take_profit"):
                print(
                    f"   🎯 Placing missing take-profit at ${trade_data['take_profit']:.2f}..."
                )
                tp_result = place_take_profit_order(
                    client, "long", CONTRACTS_PER_TRADE, trade_data["take_profit"]
                )
                if tp_result.get("success"):
                    positions_data["current_position"]["take_profit"] = trade_data[
                        "take_profit"
                    ]
                    positions_data["current_position"]["take_profit_order_id"] = (
                        tp_result.get("order_id")
                    )
                results[0]["message"] += f"\n   {tp_result['message']}"
        elif new_signal == "sell":
            # Close long, open short
            result1 = execute_trade(
                "close_long", current_price, positions_data, client=client
            )
            results.append(result1)

            # Validate before opening short
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append(
                    {
                        "success": False,
                        "message": f"⚠️ Invalid trade levels: {error_msg}",
                    }
                )
            else:
                # NEW: Check volume conditions before opening opposite position
                volume_ok, volume_msg = check_volume_conditions(csv_data)
                if not volume_ok:
                    results.append(
                        {
                            "success": False,
                            "message": f"⚠️ Volume too low to open SHORT: {volume_msg}",
                        }
                    )
                else:
                    # Cancel any previous limit orders before new trade (though just closed)
                    cancel_all_open_orders(client)
                    result2 = execute_trade(
                        "open_short",
                        current_price,
                        positions_data,
                        trade_data.get("stop_loss"),
                        trade_data.get("take_profit"),
                        client=client,
                    )
                    results.append(result2)
        elif new_signal == "hold":
            result = execute_trade(
                "close_long", current_price, positions_data, client=client
            )
            results.append(result)

    elif current_status == "short":
        if new_signal == "sell":
            # Calculate P/L from entry price and current price
            entry = positions_data["current_position"]["entry_price"]
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            pl = (entry - current_price) * multiplier if entry else 0
            positions_data["current_position"]["unrealized_pnl"] = pl
            results.append(
                {
                    "success": True,
                    "message": f"✅ Holding SHORT (Entry: ${entry:,.2f}, Current P/L: ${pl:+,.2f})",
                }
            )
            # FIXED: Place missing stop/TP if None
            if positions_data["current_position"][
                "stop_loss_order_id"
            ] is None and trade_data.get("stop_loss"):
                print(
                    f"   📍 Placing missing stop-loss at ${trade_data['stop_loss']:.2f}..."
                )
                stop_result = place_stop_loss_order(
                    client, "short", CONTRACTS_PER_TRADE, trade_data["stop_loss"]
                )
                if stop_result.get("success"):
                    positions_data["current_position"]["stop_loss"] = trade_data[
                        "stop_loss"
                    ]
                    positions_data["current_position"]["stop_loss_order_id"] = (
                        stop_result.get("order_id")
                    )
                results[0]["message"] += f"\n   {stop_result['message']}"
            if positions_data["current_position"][
                "take_profit_order_id"
            ] is None and trade_data.get("take_profit"):
                print(
                    f"   🎯 Placing missing take-profit at ${trade_data['take_profit']:.2f}..."
                )
                tp_result = place_take_profit_order(
                    client, "short", CONTRACTS_PER_TRADE, trade_data["take_profit"]
                )
                if tp_result.get("success"):
                    positions_data["current_position"]["take_profit"] = trade_data[
                        "take_profit"
                    ]
                    positions_data["current_position"]["take_profit_order_id"] = (
                        tp_result.get("order_id")
                    )
                results[0]["message"] += f"\n   {tp_result['message']}"
        elif new_signal == "buy":
            # Close short, open long
            result1 = execute_trade(
                "close_short", current_price, positions_data, client=client
            )
            results.append(result1)

            # Validate before opening long
            is_valid, error_msg = validate_trade_levels(trade_data, current_price)
            if not is_valid:
                results.append(
                    {
                        "success": False,
                        "message": f"⚠️ Invalid trade levels: {error_msg}",
                    }
                )
            else:
                # NEW: Check volume conditions before opening opposite position
                volume_ok, volume_msg = check_volume_conditions(csv_data)
                if not volume_ok:
                    results.append(
                        {
                            "success": False,
                            "message": f"⚠️ Volume too low to open LONG: {volume_msg}",
                        }
                    )
                else:
                    # Cancel any previous limit orders before new trade (though just closed)
                    cancel_all_open_orders(client)
                    result2 = execute_trade(
                        "open_long",
                        current_price,
                        positions_data,
                        trade_data.get("stop_loss"),
                        trade_data.get("take_profit"),
                        client=client,
                    )
                    results.append(result2)
        elif new_signal == "hold":
            result = execute_trade(
                "close_short", current_price, positions_data, client=client
            )
            results.append(result)

    # Update last signal
    positions_data["last_signal"] = new_signal

    return results


def fetch_btc_data():
    """Fetch futures candles from Coinbase Advanced API"""
    from coinbase.rest import RESTClient
    import time

    # Initialize client
    client = RESTClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
    )

    # Request last N+1 minutes of data
    end_time = int(time.time())
    start_time = end_time - ((TIMEFRAME_MINUTES + 1) * 60)

    # Get candles from Coinbase Advanced API
    candles_response = client.get_candles(
        product_id=FUTURES_PRODUCT_ID,
        start=str(start_time),
        end=str(end_time),
        granularity="ONE_MINUTE",
    )

    # Extract candles (API returns newest first)
    candles_list = getattr(candles_response, "candles", [])

    # Reverse to get oldest first
    candles_list.reverse()

    # Take last N candles, convert to CSV
    recent = (
        candles_list[-TIMEFRAME_MINUTES:]
        if len(candles_list) >= TIMEFRAME_MINUTES
        else candles_list
    )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Open", "High", "Low", "Close", "Volume"])

    for candle in recent:
        ts = int(getattr(candle, "start", 0))  # Unix timestamp
        open_price = float(getattr(candle, "open", 0))
        high = float(getattr(candle, "high", 0))
        low = float(getattr(candle, "low", 0))
        close = float(getattr(candle, "close", 0))
        volume = float(getattr(candle, "volume", 0))
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
    lines = data.strip().split("\n")[1:]  # Skip header
    candles = []
    for line in lines:
        parts = line.split(",")
        # Create UTC timestamp, convert to local time
        utc_time = pd.to_datetime(int(parts[0]), unit="s", utc=True)
        local_time = utc_time.tz_convert("America/New_York").tz_localize(
            None
        )  # Convert to ET and remove timezone
        candles.append(
            {
                "timestamp": local_time,
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": float(parts[5]),
            }
        )

    df = pd.DataFrame(candles)
    df.set_index("timestamp", inplace=True)
    df.columns = ["Open", "High", "Low", "Close", "Volume"]

    # Create custom style for professional look
    mc = mpf.make_marketcolors(
        up="#26a69a",
        down="#ef5350",
        edge="inherit",
        wick={"up": "#26a69a", "down": "#ef5350"},
        volume="in",
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle=":",
        y_on_right=False,
        facecolor="#1e1e1e",
        figcolor="#1e1e1e",
        edgecolor="#555555",
        gridcolor="#333333",
        rc={
            "axes.labelcolor": "white",  # X and Y axis labels
            "xtick.color": "white",  # X axis tick labels
            "ytick.color": "white",  # Y axis tick labels
            "axes.titlecolor": "white",  # Chart title
            "text.color": "white",  # All text
        },
    )

    # Add horizontal lines for entry, stop-loss, and take-profit
    hlines_dict = None
    if trade_data and trade_data.get("action") != "hold":
        values = []
        colors = []
        linestyles = []
        linewidths = []

        if trade_data.get("entry_price"):
            values.append(trade_data["entry_price"])
            colors.append("#2196F3")  # Blue for entry
            linestyles.append("--")
            linewidths.append(1.5)

        if trade_data.get("stop_loss"):
            values.append(trade_data["stop_loss"])
            colors.append("#FF5252")  # Red for stop-loss
            linestyles.append("--")
            linewidths.append(1.5)

        if trade_data.get("take_profit"):
            values.append(trade_data["take_profit"])
            colors.append("#4CAF50")  # Green for take-profit
            linestyles.append("--")
            linewidths.append(1.5)

        if values:
            hlines_dict = dict(
                hlines=values,
                colors=colors,
                linestyle=linestyles,
                linewidths=linewidths,
                alpha=0.8,
            )

    # Save to BytesIO instead of file
    buf = BytesIO()
    plot_kwargs = {
        "type": "candle",
        "style": style,
        "volume": True,
        "title": f"{CRYPTO_SYMBOL} FUTURES ({FUTURES_PRODUCT_ID}) - LIVE - Last {TIMEFRAME_MINUTES} min",
        "returnfig": True,  # Return figure object so we can add text
    }

    # Only add hlines if we have trade data
    if hlines_dict:
        plot_kwargs["hlines"] = hlines_dict

    fig, axes = mpf.plot(df, **plot_kwargs)

    # Add "INVALID TRADE" text overlay if trade was rejected
    if trade_invalid and trade_data and trade_data.get("action") != "hold":
        # Add text to the main price chart (axes[0])
        ax = axes[0]
        # Position text at left side, vertically centered (25% from left, 50% from bottom)
        ax.text(
            0.25,
            0.50,
            "INVALID TRADE",
            transform=ax.transAxes,
            fontsize=16,
            fontweight="bold",
            color="#FF5252",  # Red
            bbox=dict(
                boxstyle="round,pad=0.5",
                facecolor="#1e1e1e",
                edgecolor="#FF5252",
                linewidth=2,
            ),
            ha="center",
            va="center",
            zorder=1000,
        )

    # Save figure to buffer
    fig.savefig(buf, dpi=150, bbox_inches="tight")
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
    lines = csv_data.strip().split("\n")
    latest_candle = lines[-1].split(",")
    current_price = float(latest_candle[4])  # Close price

    prompt = f"""You are a crypto TA expert specializing in TREND FOLLOWING ONLY. Your ONLY job is to identify trends and enter on pullbacks. DO NOT take counter-trend trades. DO NOT trade in ranging markets.

Analyze this {CRYPTO_SYMBOL}/USD 1m OHLCV data from the last {TIMEFRAME_MINUTES} minutes:
{csv_data}

Current {CRYPTO_SYMBOL} price: ${current_price:,.2f}

🎯 **CRITICAL RULE: ONLY TRADE TREND FOLLOWING WITH PULLBACKS**

**⚠️ IF NO CLEAR TREND → IMMEDIATELY USE "hold" (DO NOT TRADE)**

---

## STEP 1: IDENTIFY THE TREND (MOST IMPORTANT!)

**UPTREND DEFINITION (for BUY signals):**
- Price makes higher highs AND higher lows
- Each swing high is above the previous swing high
- Each swing low is above the previous swing low
- Example: $4000 → $4100 (swing up), pullback to $4050 (higher low), → $4150 (higher high), pullback to $4100 (higher low)

**DOWNTREND DEFINITION (for SELL signals):**
- Price makes lower highs AND lower lows
- Each swing high is below the previous swing high
- Each swing low is below the previous swing low
- Example: $4000 → $3900 (swing down), bounce to $3950 (lower high), → $3850 (lower low), bounce to $3900 (lower high)

**NO TREND / RANGING:**
- Price moving sideways without clear direction
- No higher highs/lows OR lower highs/lows
- Choppy price action with no structure
- **ACTION: USE "hold" - DO NOT TRADE**

**🚫 NEVER TRADE COUNTER-TREND:**
- If uptrend exists, NEVER take SELL signals
- If downtrend exists, NEVER take BUY signals
- If no trend, NEVER trade at all

---

## STEP 2: CHECK FOR PULLBACK ENTRY (20-80% Retracement)

**For UPTREND (BUY):**
- Wait for price to pull back from the last swing high
- Pullback should be 20-80% of the last upward swing
- Entry anywhere in this range is valid
- Example: Swing from $4100 to $4150 ($50 range) → pullback to $4110-$4140 = valid entry zone

**For DOWNTREND (SELL):**
- Wait for price to bounce from the last swing low
- Bounce should be 20-80% of the last downward swing
- Entry anywhere in this range is valid
- Example: Swing from $4100 to $4050 ($50 range) → bounce to $4060-$4090 = valid entry zone

**Perfect Example from User:**
- Price at $4000 → $4100 (uptrend starting)
- Pullback to $4050 (50% retracement) ✓
- Swing to $4150 (higher high confirmed) ✓
- Pullback to $4100 (current price) ✓
- **ENTRY HERE at $4100** (50% of $4100-$4150 swing)
- Stop: $4050 (last swing low)
- Target: $4160+ (above last high of $4150)
- This is a PERFECT trend-following setup!

**IF NO PULLBACK:**
- Price still making new highs/lows without retracement
- Wait for pullback (use "hold")
- DO NOT chase momentum

---

## STEP 3: STOP-LOSS PLACEMENT (Must be at swing point in trend direction)

**For UPTREND (BUY):**
- Find the last significant swing LOW in the uptrend
- This is where the last pullback ended (the support that held)
- Place stop 5-20 dollars BELOW this swing low
- Example: Last swing low at $4050 → Stop at $4045

**For DOWNTREND (SELL):**
- Find the last significant swing HIGH in the downtrend
- This is where the last bounce ended (the resistance that held)
- Place stop 5-20 dollars ABOVE this swing high
- Example: Last swing high at $3950 → Stop at $3955

**STOP DISTANCE CONSTRAINTS:**
- Minimum stop distance: {MIN_DISTANCE_PERCENT}% from entry
- Maximum stop distance: {MAX_DISTANCE_PERCENT}% from entry
- Calculate: (|entry - stop| / entry) × 100 = percentage
- If stop doesn't meet constraints → use "hold" (trend not clear enough)

---

## STEP 4: TARGET CALCULATION (Next structure level in trend direction)

**For UPTREND (BUY):**
- Find the next resistance level ABOVE entry price
- Look for previous swing highs in the trend
- Target should be slightly above the last swing high (to ensure breakout)
- Example: Last high was $4150 → Target at $4160 (a bit above for confirmation)

**For DOWNTREND (SELL):**
- Find the next support level BELOW entry price
- Look for previous swing lows in the trend
- Target should be slightly below the last swing low (to ensure breakdown)
- Example: Last low was $3850 → Target at $3840 (a bit below for confirmation)

**TARGET CONSTRAINTS:**
- Risk-reward ratio must be between 0.5:1 and 3:1
- Calculate: (|entry - target| / |entry - stop|)
- If ratio outside range → use "hold" (not worth the risk)

---

## DECISION MATRIX

**Use BUY signal ONLY if:**
1. ✓ Clear uptrend identified (higher highs + higher lows)
2. ✓ Currently in 20-80% pullback zone
3. ✓ Stop at last swing low meets distance constraints
4. ✓ Target at next resistance meets R:R ratio
5. ✓ You would NOT take a SELL signal here

**Use SELL signal ONLY if:**
1. ✓ Clear downtrend identified (lower highs + lower lows)
2. ✓ Currently in 20-80% bounce zone
3. ✓ Stop at last swing high meets distance constraints
4. ✓ Target at next support meets R:R ratio
5. ✓ You would NOT take a BUY signal here

**Use HOLD signal if:**
- ❌ No clear trend (ranging/choppy market)
- ❌ Trend exists but no pullback yet
- ❌ Pullback too deep (>80% retracement = trend broken)
- ❌ Pullback too shallow (<20% = momentum still too strong)
- ❌ Stop distance doesn't meet constraints
- ❌ Target R:R ratio outside acceptable range
- ❌ ANY doubt about trend direction

---

## OUTPUT FORMAT

Provide TWO outputs:

1. **ANALYSIS** (for traders):
- State if UPTREND, DOWNTREND, or NO TREND
- If trend: describe the swing structure (where are the highs/lows)
- If pullback: state percentage retracement and entry zone
- If no trend: explain why (ranging, choppy, unclear structure)
- Give clear BUY/SELL/HOLD recommendation
- Mention stop placement: "Stop at $X (last swing low/high from trend)"

2. **TRADE_DATA** (for execution):
{{
  "action": "buy" or "sell" or "hold",
  "entry_price": {current_price},
  "stop_loss": <number>,
  "take_profit": <number>,
  "confidence": 0-100
}}

⚠️ CRITICAL: Output PURE JSON ONLY. NO COMMENTS. Do NOT add // text after values.

---

## CONFIDENCE SCORING

**75-100% (Very High):**
- Perfect trend with clear structure
- Pullback in 40-60% zone (ideal)
- Stop at strong swing point
- Multiple confirmations

**50-75% (High):**
- Clear trend with good structure
- Pullback in 20-80% zone
- Stop at valid swing point
- Target at clear level

**25-50% (Medium):**
- Trend exists but less clear
- Pullback in acceptable zone
- Some structure uncertainty

**0-25% (Low):**
- Weak or unclear trend
- Should probably use "hold"

**IF CONFIDENCE < 50% → USE "hold"**

---

## VALIDATION CHECKLIST (MUST PASS ALL)

For BUY:
- [ ] Stop < Entry < Target (direction check)
- [ ] Stop distance: {MIN_DISTANCE_PERCENT}% to {MAX_DISTANCE_PERCENT}%
- [ ] Target R:R ratio: 0.5:1 to 3:1
- [ ] Stop at last swing LOW in uptrend
- [ ] Target above last swing HIGH
- [ ] Clear uptrend with higher highs + higher lows
- [ ] Currently in 20-80% pullback zone

For SELL:
- [ ] Target < Entry < Stop (direction check)
- [ ] Stop distance: {MIN_DISTANCE_PERCENT}% to {MAX_DISTANCE_PERCENT}%
- [ ] Target R:R ratio: 0.5:1 to 3:1
- [ ] Stop at last swing HIGH in downtrend
- [ ] Target below last swing LOW
- [ ] Clear downtrend with lower highs + lower lows
- [ ] Currently in 20-80% bounce zone

**IF ANY CHECK FAILS → USE "hold"**

For "hold": set stop_loss and take_profit to null"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )

    full_response = response.choices[0].message.content

    # Parse response to extract analysis and trade data
    analysis, trade_data = parse_llm_response(full_response)

    # FIXED: If parsing fails, fallback to hold
    if trade_data is None:
        trade_data = {
            "action": "hold",
            "entry_price": current_price,
            "stop_loss": None,
            "take_profit": None,
            "confidence": 0,
        }
        print("⚠️ LLM response parsing failed - defaulting to HOLD")

    return analysis, trade_data


def parse_llm_response(response_text):
    """Extract human analysis and structured trade data from ChatGPT response"""

    # Try to parse as complete JSON first (new nested format)
    try:
        full_json = json.loads(response_text)
        if isinstance(full_json, dict):
            # Check if it has the nested structure: {"analysis": "...", "trade_data": {...}}
            if "analysis" in full_json and "trade_data" in full_json:
                # Ensure analysis is a string
                analysis_value = full_json["analysis"]
                if not isinstance(analysis_value, str):
                    analysis_value = (
                        json.dumps(analysis_value)
                        if isinstance(analysis_value, dict)
                        else str(analysis_value)
                    )
                    print(
                        "⚠️ Warning: ChatGPT returned analysis as non-string, converted"
                    )
                return analysis_value, full_json["trade_data"]
            # Check if it has "action" at top level (old flat format)
            elif "action" in full_json:
                return "", full_json
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON in the response (old method for backwards compatibility)
    # This regex now allows nested braces
    json_match = re.search(
        r'\{(?:[^{}]|(?:\{[^{}]*\}))*"action"[^}]*\}', response_text, re.DOTALL
    )

    if json_match:
        try:
            trade_data = json.loads(json_match.group(0))
            # Extract analysis (everything before the JSON)
            analysis = response_text[: json_match.start()].strip()
            # Clean up common markers
            analysis = re.sub(
                r"^\*\*?ANALYSIS\*\*?:?\s*", "", analysis, flags=re.IGNORECASE
            )
            analysis = re.sub(
                r"\*\*?TRADE_DATA\*\*?:?\s*.*$",
                "",
                analysis,
                flags=re.DOTALL | re.IGNORECASE,
            )
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
    if not trade_data or trade_data.get("action") == "hold":
        return True, None

    action = trade_data.get("action")
    entry = current_price  # We use current price as entry
    stop = trade_data.get("stop_loss")
    target = trade_data.get("take_profit")

    # Check that levels exist
    if stop is None or target is None:
        return False, "Missing stop_loss or take_profit"

    # Calculate distances and percentages
    stop_distance = abs(entry - stop)
    target_distance = abs(entry - target)
    stop_percentage = (stop_distance / entry) * 100  # Convert to percentage
    target_percentage = (target_distance / entry) * 100

    # Check stop distance constraints (use configured min/max percentages)
    if stop_percentage < MIN_DISTANCE_PERCENT:
        return (
            False,
            f"Stop too tight: {stop_percentage:.2f}% (minimum {MIN_DISTANCE_PERCENT}%)",
        )
    if stop_percentage > MAX_DISTANCE_PERCENT:
        return (
            False,
            f"Stop too wide: {stop_percentage:.2f}% (maximum {MAX_DISTANCE_PERCENT}%)",
        )

    # Check target distance constraints (use configured min/max percentages)
    if target_percentage < MIN_DISTANCE_PERCENT:
        return (
            False,
            f"Target too close: {target_percentage:.2f}% (minimum {MIN_DISTANCE_PERCENT}%)",
        )
    if target_percentage > MAX_DISTANCE_PERCENT:
        return (
            False,
            f"Target too far: {target_percentage:.2f}% (maximum {MAX_DISTANCE_PERCENT}%)",
        )

    # Check risk-reward ratio (0.5:1 to 3:1, meaning 1:2 to 3:1)
    rr_ratio = target_distance / stop_distance if stop_distance > 0 else 0
    if rr_ratio < 0.5:
        return False, f"Risk-reward too low: {rr_ratio:.2f}:1 (minimum 0.5:1, aka 1:2)"
    if rr_ratio > 3.0:
        return False, f"Risk-reward too high: {rr_ratio:.2f}:1 (maximum 3:1)"

    # For BUY (long): stop < entry < target
    if action == "buy":
        if stop >= entry:
            return (
                False,
                f"LONG: stop_loss (${stop:,.2f}) must be BELOW entry (${entry:,.2f})",
            )
        if target <= entry:
            return (
                False,
                f"LONG: take_profit (${target:,.2f}) must be ABOVE entry (${entry:,.2f})",
            )

    # For SELL (short): target < entry < stop
    elif action == "sell":
        if target >= entry:
            return (
                False,
                f"SHORT: take_profit (${target:,.2f}) must be BELOW entry (${entry:,.2f})",
            )
        if stop <= entry:
            return (
                False,
                f"SHORT: stop_loss (${stop:,.2f}) must be ABOVE entry (${entry:,.2f})",
            )

    return True, None


def check_volume_conditions(csv_data):
    """Check if volume conditions are met for opening new trades

    Conditions (both must be satisfied):
    - Average volume of last 10 candles must be > 100
    - At least 7 out of 10 candles must have volume > 20

    Returns:
        tuple: (is_valid, failure_message)
            - is_valid: True if both conditions pass, False otherwise
            - failure_message: None if valid, descriptive string if invalid
    """
    # Parse CSV data to get last 10 candles
    lines = csv_data.strip().split("\n")[1:]  # Skip header

    # Get last 10 candles (or all if less than 10)
    last_10_lines = lines[-10:] if len(lines) >= 10 else lines

    volumes = []
    for line in last_10_lines:
        parts = line.split(",")
        volume = float(parts[5])  # Volume is 6th column (index 5)
        volumes.append(volume)

    # Check condition 1: Average volume > 100
    avg_volume = sum(volumes) / len(volumes) if volumes else 0
    avg_check = avg_volume > 100

    # Check condition 2: At least 7 candles with volume > 20
    high_volume_count = sum(1 for v in volumes if v > 20)
    count_check = high_volume_count >= 7

    # Determine result
    if avg_check and count_check:
        return True, None

    # Build failure message
    failures = []
    if not avg_check:
        failures.append(f"avg volume {avg_volume:.1f} ≤ 100")
    if not count_check:
        failures.append(f"only {high_volume_count}/10 candles > 20 volume (need 7+)")

    failure_msg = " AND ".join(failures)
    return False, failure_msg


def send_to_discord(
    analysis,
    webhook_url,
    chart_image,
    trade_data=None,
    trade_results=None,
    positions_data=None,
    futures_balance=None,
    buying_power=None,
    daily_pnl=None,
):
    """Send analysis and chart to Discord with position management info"""

    # Start with analysis (ensure it's always a string)
    if isinstance(analysis, dict):
        # If analysis is accidentally a dict, convert to JSON string or extract text
        analysis = (
            json.dumps(analysis, indent=2) if analysis else "Analysis parsing error"
        )
        print("⚠️ Warning: analysis was a dict, converted to string")
    full_description = str(analysis)

    # Add trade results (position changes)
    if trade_results:
        full_description += "\n\n**💼 Position Updates:**"
        for result in trade_results:
            full_description += f"\n{result['message']}"

    # FIXED: Show levels from current position if exists, else from trade_data if new/invalid trade
    current_status = (
        positions_data.get("current_position", {}).get("status", "none")
        if positions_data
        else "none"
    )
    if current_status != "none":
        # Show existing position levels (if set)
        entry = positions_data["current_position"].get("entry_price", "N/A")
        stop = positions_data["current_position"].get("stop_loss", "N/A")
        tp = positions_data["current_position"].get("take_profit", "N/A")
        pl = positions_data["current_position"].get("unrealized_pnl", 0)
        full_description += f"\n\n**📊 Current Position Levels:**"
        full_description += (
            f"\n🔵 Entry: ${entry:,.2f}"
            if isinstance(entry, (int, float))
            else f"\n🔵 Entry: {entry}"
        )
        full_description += (
            f"\n🔴 Stop Loss: ${stop:,.2f}"
            if isinstance(stop, (int, float))
            else f"\n🔴 Stop Loss: {stop}"
        )
        full_description += (
            f"\n🟢 Take Profit: ${tp:,.2f}"
            if isinstance(tp, (int, float))
            else f"\n🟢 Take Profit: {tp}"
        )
        full_description += f"\n💰 Current P/L: ${pl:+,.2f}"
        if trade_data and "confidence" in trade_data:
            full_description += f"\n📈 Confidence: {trade_data['confidence']}%"
    elif trade_data and trade_data.get("action") != "hold":
        # Show proposed levels for new trades
        is_invalid = any(
            "Invalid trade levels" in r.get("message", "") for r in trade_results or []
        )
        if is_invalid:
            full_description += f"\n\n**⚠️ Trade Rejected:** Signal was {trade_data.get('action', 'unknown').upper()} but validation failed (check stop distance, risk-reward ratio, or levels)"
        else:
            full_description += f"\n\n**📊 Trade Levels:**"
            full_description += f"\n🔵 Entry: ${trade_data.get('entry_price', 0):,.2f}"
            full_description += (
                f"\n🔴 Stop Loss: ${trade_data.get('stop_loss', 0):,.2f}"
            )
            full_description += (
                f"\n🟢 Take Profit: ${trade_data.get('take_profit', 0):,.2f}"
            )
            if "confidence" in trade_data:
                full_description += f"\n📈 Confidence: {trade_data['confidence']}%"

    # Add real account balance if available
    if futures_balance or buying_power or daily_pnl is not None:
        full_description += f"\n\n**💰 Account:**"
        if futures_balance:
            full_description += f"\n💵 Total Balance: ${futures_balance:,.2f}"
        if buying_power:
            full_description += f"\n📊 Buying Power: ${buying_power:,.2f}"
        if daily_pnl is not None:
            full_description += f"\n📈 Today's P/L: ${daily_pnl:+,.2f}"

    # Add performance stats (live stats without paper balance)
    if positions_data:
        total = positions_data.get("total_trades", 0)
        if total > 0:
            wins = positions_data.get("winning_trades", 0)
            losses = positions_data.get("losing_trades", 0)
            win_rate = (wins / total * 100) if total > 0 else 0

            # Calculate average win/loss from trade history
            trade_history = positions_data.get("trade_history", [])
            total_profit = sum(
                t["profit_loss"] for t in trade_history if t["profit_loss"] > 0
            )
            total_loss = abs(
                sum(t["profit_loss"] for t in trade_history if t["profit_loss"] < 0)
            )
            avg_win = (total_profit / wins) if wins > 0 else 0
            avg_loss = (total_loss / losses) if losses > 0 else 0
            avg_ratio = (avg_win / avg_loss) if avg_loss > 0 else avg_win

            full_description += f"\n\n**📈 Trading Stats:**"
            full_description += f"\n📊 Trades: {total} ({wins}W / {losses}L)"
            if total > 0:
                if losses > 0:
                    full_description += f"\n📊 Avg W:L: {avg_ratio:.2f}:1 (avg win: ${avg_win:.2f}, avg loss: ${avg_loss:.2f})"
                else:
                    full_description += (
                        f"\n📊 Avg W:L: Perfect! (${avg_win:.2f} avg win, no losses)"
                    )
                full_description += f"\n🎯 Win Rate: {win_rate:.1f}%"

    # Determine trading mode for footer
    trading_mode_text = "💰 LIVE TRADING"

    # Format as Discord embed for better readability
    payload = {
        "embeds": [
            {
                "title": f"🪙 {CRYPTO_SYMBOL} Futures Bot ({FUTURES_PRODUCT_ID})",
                "description": full_description,
                "color": 0x00FF00
                if "buy" in analysis.lower()
                else 0xFFA500
                if "hold" in analysis.lower()
                else 0xFF0000,  # Green/Yellow/Red based on rec
                "image": {"url": "attachment://chart.png"},
                "footer": {
                    "text": f"{trading_mode_text} | {CONTRACTS_PER_TRADE} contract(s) | {os.getenv('GITHUB_RUN_ID', 'Local')}"
                },
                "timestamp": datetime.now().isoformat(),
            }
        ]
    }

    # Send with file attachment
    files = {"file": ("chart.png", chart_image, "image/png")}
    data = {"payload_json": json.dumps(payload)}

    response = requests.post(webhook_url, data=data, files=files)
    if response.status_code != 204 and response.status_code != 200:
        print(f"Discord send failed: {response.status_code} - {response.text}")
    else:
        print("Analysis and chart sent to Discord successfully!")


if __name__ == "__main__":
    from coinbase.rest import RESTClient

    trading_mode = "💰 LIVE TRADING"
    print("=" * 70)
    print(f"🤖 {CRYPTO_SYMBOL} FUTURES TRADING BOT - {trading_mode}")
    print(f"📦 Product: {FUTURES_PRODUCT_ID}")
    print(f"📊 Contracts per trade: {CONTRACTS_PER_TRADE}")
    print("=" * 70)

    print("\n⚠️  ⚠️  ⚠️  WARNING: LIVE TRADING MODE ENABLED ⚠️  ⚠️  ⚠️")
    print("This bot will execute REAL trades with REAL money!")
    print("=" * 70)

    # Initialize Coinbase client (needed for both paper and real trading for data)
    client = RESTClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
    )

    # Fetch real futures balance
    futures_balance = None
    buying_power = None
    daily_pnl = None
    try:
        balance_summary = client.get_futures_balance_summary()
        balance_summary_dict = (
            balance_summary.to_dict() if hasattr(balance_summary, "to_dict") else {}
        )
        bal_sum = balance_summary_dict.get("balance_summary", {})

        futures_balance = float(bal_sum.get("total_usd_balance", {}).get("value", 0))
        buying_power = float(bal_sum.get("futures_buying_power", {}).get("value", 0))
        daily_pnl = float(bal_sum.get("daily_realized_pnl", {}).get("value", 0))

        print(f"💰 Total Balance: ${futures_balance:,.2f}")
        print(f"📊 Buying Power: ${buying_power:,.2f}")
        print(f"📈 Today's P/L: ${daily_pnl:+,.2f}")
    except Exception as e:
        print(f"⚠️ Failed to fetch futures balance: {e}")

    # Load current position state
    positions_data = load_positions()
    print(
        f"\n📊 Current Status: {positions_data['current_position']['status'].upper()}"
    )
    if positions_data["current_position"]["status"] != "none":
        print(f"   Entry: ${positions_data['current_position']['entry_price']:,.2f}")

    # Show stats if there are any trades
    total = positions_data.get("total_trades", 0)
    if total > 0:
        wins = positions_data.get("winning_trades", 0)
        losses = positions_data.get("losing_trades", 0)
        win_rate = (wins / total * 100) if total > 0 else 0

        # Calculate average win/loss from trade history
        trade_history = positions_data.get("trade_history", [])
        total_profit = sum(
            t["profit_loss"] for t in trade_history if t["profit_loss"] > 0
        )
        total_loss = abs(
            sum(t["profit_loss"] for t in trade_history if t["profit_loss"] < 0)
        )
        avg_win = (total_profit / wins) if wins > 0 else 0
        avg_loss = (total_loss / losses) if losses > 0 else 0
        avg_ratio = (avg_win / avg_loss) if avg_loss > 0 else avg_win

        print(f"\n📈 Trading Stats:")
        print(f"   📊 Trades: {total} ({wins}W / {losses}L)")
        if losses > 0:
            print(
                f"   📊 Avg W:L: {avg_ratio:.2f}:1 (avg win: ${avg_win:.2f}, avg loss: ${avg_loss:.2f})"
            )
        else:
            print(f"   📊 Avg W:L: Perfect! (${avg_win:.2f} avg win, no losses)")
        print(f"   🎯 Win Rate: {win_rate:.1f}%")

    # Fetch the data
    print(f"\n📥 Fetching {CRYPTO_SYMBOL} futures data from Coinbase...")
    data = fetch_btc_data()
    print("✅ Data fetched successfully\n")

    # Get current price
    lines = data.strip().split("\n")
    latest_candle = lines[-1].split(",")
    current_price = float(latest_candle[4])
    print(f"💵 Current {CRYPTO_SYMBOL} Futures Price: ${current_price:,.2f}\n")

    # Get actual position from Coinbase and sync state
    print("\n📊 Checking actual futures position on Coinbase...")
    real_position = get_current_futures_position(client)

    trade_results = []  # Initialize here to collect desync if any

    if real_position.get("exists") is None:
        error_msg = real_position.get("error", "Unknown API error")
        print(f"   ⚠️ API error (keeping local state): {error_msg}")
    elif real_position["exists"]:
        print(
            f"   ✅ Position found: {real_position['side']} - {real_position['size']} contract(s)"
        )
        print(f"   Entry: ${real_position['entry_price']:,.2f}")
        print(f"   Unrealized P/L: ${real_position['unrealized_pnl']:+,.2f}")

        # Sync positions.json with actual Coinbase position
        positions_data["current_position"]["status"] = real_position["side"].lower()

        # FIXED: Preserve local entry price if API returns 0 (common issue)
        local_entry = positions_data["current_position"].get("entry_price")
        if real_position["entry_price"] == 0 and local_entry:
            # Keep local entry price, don't overwrite with 0
            print(
                f"   🔄 Preserving local entry price: ${local_entry:,.2f} (API returned 0)"
            )
        else:
            # Update with API entry price (only if non-zero or local is None)
            positions_data["current_position"]["entry_price"] = real_position[
                "entry_price"
            ]

        positions_data["current_position"]["unrealized_pnl"] = real_position[
            "unrealized_pnl"
        ]  # Store for accurate P/L display

        print("   🔄 Synced local state with Coinbase position")
    else:  # No error, but no position on API
        local_has_pos = positions_data["current_position"]["status"] != "none"
        if local_has_pos:
            print(
                "   ⚠️ API shows no position, but local has one. Assuming closed externally (e.g., stop hit)."
            )
            # Detect which order was filled for accurate exit price and P/L
            stop_order_id = positions_data["current_position"].get("stop_loss_order_id")
            tp_order_id = positions_data["current_position"].get("take_profit_order_id")

            exit_price = current_price  # Fallback
            reason = "externally"
            filled_price = None

            # Check stop order
            if stop_order_id:
                try:
                    stop_order_resp = client.get_order(stop_order_id)
                    stop_dict = (
                        stop_order_resp.to_dict()
                        if hasattr(stop_order_resp, "to_dict")
                        else {}
                    )
                    order_info = stop_dict.get("order", {})
                    if order_info.get("status") == "FILLED":
                        filled_price = float(
                            order_info.get("average_filled_price", current_price)
                        )
                        exit_price = filled_price
                        reason = "stop_hit"
                except Exception as e:
                    print(f"Warning: Could not fetch stop order status: {e}")

            # Check TP order
            if tp_order_id and filled_price is None:  # If stop not filled
                try:
                    tp_order_resp = client.get_order(tp_order_id)
                    tp_dict = (
                        tp_order_resp.to_dict()
                        if hasattr(tp_order_resp, "to_dict")
                        else {}
                    )
                    order_info = tp_dict.get("order", {})
                    if order_info.get("status") == "FILLED":
                        filled_price = float(
                            order_info.get("average_filled_price", current_price)
                        )
                        exit_price = filled_price
                        reason = "target_hit"
                except Exception as e:
                    print(f"Warning: Could not fetch TP order status: {e}")

            # FIXED: Cancel any lingering orders (including entry order for unfilled limit orders)
            entry_order_id = positions_data["current_position"].get("entry_order_id")
            order_ids = [
                oid for oid in [entry_order_id, stop_order_id, tp_order_id] if oid
            ]
            if order_ids:
                print(
                    f"   🚫 Cancelling {len(order_ids)} lingering orders (including unfilled entry)..."
                )
                cancel_pending_orders(client, order_ids)

            # FIXED: Check if entry order actually filled before recording P/L
            entry_was_filled = True  # Assume filled unless we find unfilled entry order
            if entry_order_id:
                try:
                    entry_order_resp = client.get_order(entry_order_id)
                    entry_dict = (
                        entry_order_resp.to_dict()
                        if hasattr(entry_order_resp, "to_dict")
                        else {}
                    )
                    entry_order_info = entry_dict.get("order", {})
                    entry_status = entry_order_info.get("status", "UNKNOWN")
                    if entry_status in ["OPEN", "PENDING", "QUEUED"]:
                        entry_was_filled = False
                        print(
                            f"   ⚠️ Entry order never filled (status: {entry_status}) - NOT recording P/L"
                        )
                except Exception as e:
                    print(f"Warning: Could not fetch entry order status: {e}")

            # Calculate P/L only if entry was actually filled
            entry = positions_data["current_position"]["entry_price"]
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            if entry is not None and entry_was_filled:
                if positions_data["current_position"]["status"] == "long":
                    profit_loss = (exit_price - entry) * multiplier
                    trade_type = "long"
                    emoji = "✅" if profit_loss > 0 else "❌"
                else:
                    profit_loss = (entry - exit_price) * multiplier
                    trade_type = "short"
                    emoji = "✅" if profit_loss > 0 else "❌"
                positions_data["trade_history"].append(
                    {
                        "type": trade_type,
                        "entry_price": entry,
                        "exit_price": exit_price,
                        "profit_loss": profit_loss,
                        "entry_time": positions_data["current_position"]["entry_time"],
                        "exit_time": datetime.now().isoformat(),
                        "note": f"Closed {reason} (desync detected)",
                    }
                )
                positions_data["total_trades"] += 1
                if profit_loss > 0:
                    positions_data["winning_trades"] += 1
                else:
                    positions_data["losing_trades"] += 1

                # Add to trade_results for Discord
                trade_results.append(
                    {
                        "success": True,
                        "message": f"{emoji} Desync: Position closed {reason} at ${exit_price:,.2f} | P/L: ${profit_loss:+,.2f}",
                    }
                )
            elif entry is not None and not entry_was_filled:
                # Entry order never filled - just report desync without P/L
                trade_results.append(
                    {
                        "success": True,
                        "message": f"⚠️ Desync: Entry limit order never filled - position cancelled (no P/L)",
                    }
                )
        else:
            print("   ✅ No open position on Coinbase")
        # FIXED: Always clear local to match API (but only if no error)
        positions_data["current_position"]["status"] = "none"
        positions_data["current_position"]["entry_price"] = None
        positions_data["current_position"]["entry_time"] = None
        positions_data["current_position"]["stop_loss"] = None
        positions_data["current_position"]["take_profit"] = None
        positions_data["current_position"]["entry_order_id"] = None
        positions_data["current_position"]["stop_loss_order_id"] = None
        positions_data["current_position"]["take_profit_order_id"] = None
        positions_data["current_position"]["unrealized_pnl"] = None
        if local_has_pos:
            print("   🔄 Local state cleared (desync resolved)")
        else:
            print("   🔄 Local state cleared (no position)")

    # FIXED: Always run LLM analysis after position check (moved outside the else block)
    print("\n🧠 Analyzing with ChatGPT...")
    analysis, trade_data = analyze_with_llm(data)
    print("✅ Analysis complete\n")

    # Print trade data for debugging
    if trade_data:
        print(f"📊 Signal: {trade_data.get('action', 'unknown').upper()}")
        print(f"   Confidence: {trade_data.get('confidence', 0)}%\n")

    # Manage positions (execute trades, check stops, etc.)
    print("💼 Managing positions...")
    manage_results = manage_positions(
        positions_data, trade_data, current_price, data, client
    )
    trade_results.extend(manage_results)

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
            if not result.get("success", True) and "Invalid trade levels" in result.get(
                "message", ""
            ):
                trade_invalid = True
                break

    # Generate chart with trade levels (and invalid flag if rejected)
    chart_image = generate_chart(data, trade_data, trade_invalid)

    # Send to Discord
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if webhook_url:
        print("📤 Sending to Discord...")
        send_to_discord(
            analysis,
            webhook_url,
            chart_image,
            trade_data,
            trade_results,
            positions_data,
            futures_balance,
            buying_power,
            daily_pnl,
        )
    else:
        print("⚠️  No Discord webhook configured")
        print(f"\nLLM Analysis:\n{analysis}")
        if trade_data:
            print(f"\nTrade Data: {json.dumps(trade_data, indent=2)}")

    print("\n" + "=" * 70)
    print("✅ BOT RUN COMPLETE")
    print("=" * 70)
