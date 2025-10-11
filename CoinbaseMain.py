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
                # Cancel ALL open orders before new trade
                print("   🚫 Cancelling all open orders before new trade...")
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
                # Cancel ALL open orders before new trade
                print("   🚫 Cancelling all open orders before new trade...")
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
            results.append(
                {"success": True, "message": "⚪ No position | Signal: HOLD"}
            )

    elif current_status == "long":
        if new_signal == "buy":
            # Keep existing BUY signal logic...
            # (keep your existing code for holding long)
            pass  # Your existing code here

        elif new_signal == "sell":
            # Close long and CANCEL its orders, then open short
            result1 = execute_trade(
                "close_long", current_price, positions_data, client=client
            )
            results.append(result1)

            # Cancel ALL open orders after closing
            print("   🚫 Cancelling all open orders before new trade...")
            cancel_all_open_orders(client)

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
            # IMPORTANT: Cancel ALL orders before closing on HOLD signal
            print("   🚫 Cancelling all open orders (signal: HOLD)...")
            cancel_all_open_orders(client)

            result = execute_trade(
                "close_long", current_price, positions_data, client=client
            )
            results.append(result)

    elif current_status == "short":
        if new_signal == "sell":
            # Keep existing SELL signal logic...
            # (keep your existing code for holding short)
            pass  # Your existing code here

        elif new_signal == "buy":
            # Close short and CANCEL its orders, then open long
            result1 = execute_trade(
                "close_short", current_price, positions_data, client=client
            )
            results.append(result1)

            # Cancel ALL open orders after closing
            print("   🚫 Cancelling all open orders before new trade...")
            cancel_all_open_orders(client)

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
            # IMPORTANT: Cancel ALL orders before closing on HOLD signal
            print("   🚫 Cancelling all open orders (signal: HOLD)...")
            cancel_all_open_orders(client)

            result = execute_trade(
                "close_short", current_price, positions_data, client=client
            )
            results.append(result)

    # Update last signal
    positions_data["last_signal"] = new_signal

    return results


def execute_real_futures_trade(action, contracts, client):
    """Execute a real futures trade on Coinbase

    Args:
        action: "open_long", "open_short", "close_long", "close_short"
        contracts: Number of contracts to trade
        client: Coinbase RESTClient instance

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

        # Create market order for futures (generate unique order ID)
        client_order_id = str(uuid.uuid4())

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
            limit_price_rounded = stop_price_rounded - 1
        else:
            limit_price_rounded = stop_price_rounded + 1

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
        order_id = order_dict.get("order_id", None)

        return {
            "success": True,
            "order_id": order_id,
            "message": f"✅ Stop-loss order placed at ${stop_price_rounded}",
        }

    except Exception as e:
        print(f"Error details: {e}")  # FIXED: Add logging for debugging
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
        order_id = order_dict.get("order_id", None)

        return {
            "success": True,
            "order_id": order_id,
            "message": f"✅ Take-profit order placed at ${target_price_rounded}",
        }

    except Exception as e:
        print(f"Error details: {e}")  # FIXED: Add logging for debugging
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
    if not order_ids:
        return

    try:
        client.cancel_orders(order_ids=order_ids)
        print(f"   ✅ Cancelled {len([o for o in order_ids if o])} pending orders")
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
        order_ids = [order.get("order_id") for order in orders if order.get("order_id")]
        return order_ids
    except Exception as e:
        print(f"   ⚠️ Error listing open orders: {e}")
        return []


def cancel_all_open_orders(client):
    """Cancel all open orders for the futures product"""
    order_ids = get_open_order_ids(client)
    if order_ids:
        try:
            client.cancel_orders(order_ids=order_ids)
            print(f"   ✅ Cancelled {len(order_ids)} open orders")
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
    # Real trading - execute market order first
    result = execute_real_futures_trade(action, CONTRACTS_PER_TRADE, client)

    # ✅ NEW: Place stop-loss and take-profit orders after opening position
    if result.get("success") and action in ["open_long", "open_short"]:
        position_type = "long" if action == "open_long" else "short"

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
        stop_order_id = positions_data["current_position"].get("stop_loss_order_id")
        tp_order_id = positions_data["current_position"].get("take_profit_order_id")

        # Cancel any pending orders
        order_ids = [oid for oid in [stop_order_id, tp_order_id] if oid]
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
            "stop_loss_order_id": None,  # Make sure these are cleared
            "take_profit_order_id": None,  # Make sure these are cleared
            "unrealized_pnl": None,
        }

        result["profit_loss"] = profit_loss if "profit_loss" in locals() else 0

    return result


def manage_positions(positions_data, trade_data, current_price, csv_data, client=None):
    """Manage positions based on current state and new signal

    Args:
        positions_data: Position state data
        trade_data: Signal from LLM (buy/sell/hold)
        current_price: Current market price
        csv_data: Historical candle data
        client: Coinbase RESTClient (required for real trading)

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
            results.append(
                {"success": True, "message": "⚪ No position | Signal: HOLD"}
            )

    elif current_status == "long":
        if new_signal == "buy":
            # Fetch latest pnl
            real_position = get_current_futures_position(client)
            entry = positions_data["current_position"]["entry_price"]
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            fallback_pl = (current_price - entry) * multiplier if entry else 0
            pl = real_position.get("unrealized_pnl", fallback_pl)
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
            # Fetch latest pnl
            real_position = get_current_futures_position(client)
            entry = positions_data["current_position"]["entry_price"]
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            fallback_pl = (entry - current_price) * multiplier if entry else 0
            pl = real_position.get("unrealized_pnl", fallback_pl)
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

    prompt = f"""You are a crypto TA expert specializing in SHORT-TERM scalping with STRONG technical levels. Analyze this {CRYPTO_SYMBOL}/USD 1m OHLCV data from the last {TIMEFRAME_MINUTES} minutes:
{csv_data}

Current {CRYPTO_SYMBOL} price: ${current_price:,.2f}

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
   - After determining direction (BUY/SELL), find the STRONGEST pivot point from the FULL {TIMEFRAME_MINUTES}-minute data
   - Look through ALL {TIMEFRAME_MINUTES} candles, not just the last 5-10 candles
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
  * Look through ALL {TIMEFRAME_MINUTES} minutes of data for the strongest swing LOW or support pivot
  * This could be: a level tested 2+ times, a sharp bounce point, consolidation zone
  * DO NOT just use the low of the last few candles - find SIGNIFICANT pivots
  * Place stop 5-20 dollars BELOW this pivot
  * stop_loss MUST BE BELOW entry_price
  * CHECK: Is |entry - stop| / entry between 0.10% and 0.50%? If not, find different pivot

For SELL (SHORT):
  * Look through ALL {TIMEFRAME_MINUTES} minutes of data for the strongest swing HIGH or resistance pivot
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
  * Looking at {TIMEFRAME_MINUTES}min data, find strong pivot low at $4,288 (tested 3 times)
  * Stop: $4,285 (below pivot)
  * Risk: $4,300 - $4,285 = $15 → 0.35% ✓ (between 0.10%-0.50%)
  * Looking for resistance: Strong resistance at $4,315 (consolidation zone)
  * Target: $4,315 (distance: $15 → 0.35%, ratio: 1:1 ✓) - Within 0.5:1 to 3:1 range

Example for SHORT (acceptable ratio):
  * Entry: $4,300
  * Looking at {TIMEFRAME_MINUTES}min data, find strong pivot high at $4,312 (tested 3 times)
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
- Stop is at a SIGNIFICANT pivot from the full {TIMEFRAME_MINUTES}min data (not a random recent candle) ✓
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
- Is stop placed at a SIGNIFICANT pivot from the FULL {TIMEFRAME_MINUTES}min data (not just last few candles)? ✓
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

    # Try to find JSON in the response
    json_match = re.search(r'\{[^}]*"action"[^}]*\}', response_text, re.DOTALL)

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


def send_to_discord(
    analysis,
    webhook_url,
    chart_image,
    trade_data=None,
    trade_results=None,
    positions_data=None,
    futures_balance=None,
):
    """Send analysis and chart to Discord with position management info"""

    # Start with analysis
    full_description = analysis

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

    # FIXED: Add real account balance if available
    if futures_balance:
        full_description += f"\n\n**💰 Account Balance:** ${futures_balance:,.2f}"

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

    # FIXED: Fetch real futures balance if in LIVE mode
    futures_balance = None
    try:
        balance_summary = client.get_futures_balance_summary()
        balance_summary_dict = (
            balance_summary.to_dict() if hasattr(balance_summary, "to_dict") else {}
        )
        futures_balance = float(
            balance_summary_dict.get("balance_summary", {})
            .get("total_usd_balance", {})
            .get("value", 0)
        )
        print(f"💰 Real Futures Balance: ${futures_balance:,.2f}")
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

    # If real trading, get actual position from Coinbase and sync state
    print("📊 Checking actual futures position on Coinbase...")
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
        positions_data["current_position"]["entry_price"] = real_position["entry_price"]
        positions_data["current_position"]["entry_time"] = datetime.now().isoformat()
        positions_data["current_position"]["unrealized_pnl"] = real_position[
            "unrealized_pnl"
        ]  # FIXED: Store for accurate P/L display

        # FIXED: If entry_vwap == 0, back-calculate entry from unrealized_pnl
        if positions_data["current_position"]["entry_price"] == 0:
            pnl = real_position["unrealized_pnl"]
            size = real_position["size"] * CONTRACT_MULTIPLIER
            if size > 0 and pnl is not None:
                if real_position["side"] == "LONG":
                    entry = current_price - (pnl / size)
                else:  # SHORT
                    entry = current_price + (pnl / size)
                positions_data["current_position"]["entry_price"] = entry
                print(f"   🔄 Back-calculated entry price: ${entry:,.2f} (from P/L)")

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

            # Cancel any lingering orders
            order_ids = [oid for oid in [stop_order_id, tp_order_id] if oid]
            if order_ids:
                print(f"   🚫 Cancelling {len(order_ids)} lingering orders...")
                cancel_pending_orders(client, order_ids)

            # Calculate P/L
            entry = positions_data["current_position"]["entry_price"]
            multiplier = CONTRACTS_PER_TRADE * CONTRACT_MULTIPLIER
            if entry is not None:
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
        else:
            print("   ✅ No open position on Coinbase")
        # FIXED: Always clear local to match API (but only if no error)
        positions_data["current_position"]["status"] = "none"
        positions_data["current_position"]["entry_price"] = None
        positions_data["current_position"]["entry_time"] = None
        positions_data["current_position"]["stop_loss"] = None
        positions_data["current_position"]["take_profit"] = None
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
        )
    else:
        print("⚠️  No Discord webhook configured")
        print(f"\nLLM Analysis:\n{analysis}")
        if trade_data:
            print(f"\nTrade Data: {json.dumps(trade_data, indent=2)}")

    print("\n" + "=" * 70)
    print("✅ BOT RUN COMPLETE")
    print("=" * 70)
