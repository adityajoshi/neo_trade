import os
from neo_api_client import NeoAPI
from neo_api_client.exceptions import ApiException

# ----------------------------
#  GLOBAL SESSION (re-used)
# ----------------------------
_neo = None


# ----------------------------------------------------
# 1. SESSION INITIALIZATION (called automatically)
# ----------------------------------------------------
def _get_client():
    """Create the Kotak Neo API client only once."""
    global _neo
    if _neo:
        return _neo

    try:
        _neo = NeoAPI(
            consumer_key=os.getenv("CONSUMER_KEY"),
            consumer_secret=os.getenv("CONSUMER_SECRET"),
            environment=os.getenv("ENV", "prod"),
        )

        # First step login
        _neo.login(
            userid=os.getenv("USER_ID"),
            password=os.getenv("PASSWORD"),
        )

        # TOTP / MPIN only once here
        _neo.session_2fa(
            totp=os.getenv("TOTP"),
        )

        print("✓ Kotak Neo API session established.")
        return _neo

    except Exception as e:
        print("Login/Session error:", e)
        raise


# ----------------------------------------------------
# 2. SEARCH FUNCTION
# ----------------------------------------------------
def search_stock(symbol: str):
    """
    Search stock in NSE-CM and return instrument token + metadata.
    """
    client = _get_client()
    try:
        data = client.scrip_search(
            exchange_segment="nse_cm",
            symbol=symbol.upper()
        )

        if not data or not data.get("data"):
            return None

        return data["data"][0]  # Return first matching result

    except ApiException as e:
        print("Search API error:", e)
        return None


# ----------------------------------------------------
# 3. BUY FUNCTION
# ----------------------------------------------------
def buy_stock(symbol: str, qty: int, price=None):
    """
    Place a Buy order for NSE cash market.
    If price=None → Market order.
    """

    client = _get_client()
    result = search_stock(symbol)
    if not result:
        print(f"Stock not found: {symbol}")
        return None

    token = result["instrument_token"]

    order_type = "MKT" if price is None else "L"

    try:
        order = client.place_order(
            exchange_segment="nse_cm",
            transaction_type="B",
            product="CNC",
            instrument_token=str(token),
            price=price if price else 0,
            quantity=qty,
            order_type=order_type,
            validity="DAY",
        )
        print("Buy order:", order)
        return order

    except ApiException as e:
        print("Buy order failed:", e)
        return None


# ----------------------------------------------------
# 4. SELL FUNCTION
# ----------------------------------------------------
def sell_stock(symbol: str, qty: int, price=None):
    """
    Place a Sell order for NSE cash market.
    If price=None → Market order.
    """

    client = _get_client()
    result = search_stock(symbol)
    if not result:
        print(f"Stock not found: {symbol}")
        return None

    token = result["instrument_token"]
    order_type = "MKT" if price is None else "L"

    try:
        order = client.place_order(
            exchange_segment="nse_cm",
            transaction_type="S",
            product="CNC",
            instrument_token=str(token),
            price=price if price else 0,
            quantity=qty,
            order_type=order_type,
            validity="DAY",
        )
        print("Sell order:", order)
        return order

    except ApiException as e:
        print("Sell order failed:", e)
        return None
