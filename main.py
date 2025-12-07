import os
import time
import logging
from typing import Optional, Dict, Any
import getpass

from neo_api_client import NeoAPI
from neo_api_client.exceptions import ApiException

# Optional: load `.env` if python-dotenv is installed
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # dotenv is optional — environment variables may come from the environment
    pass

# ----------------------------
#  GLOBAL SESSION (re-used)
# ----------------------------
_neo = None
_LOGGER = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    # Basic configuration if the app hasn't configured logging yet
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# ----------------------------------------------------
# 1. SESSION INITIALIZATION (called automatically)
# ----------------------------------------------------
def _require_env_vars(names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def _get_client():
    """Create the Kotak Neo API client only once.

    This function validates environment variables, creates the client,
    and performs login + 2FA. It also implements simple retries with
    exponential backoff for transient failures.
    """
    global _neo
    if _neo:
        return _neo

    # Validate critical environment variables early
    _require_env_vars(["NEO_FIN_KEY", "CONSUMER_KEY", "MOBILE_NO", "UCC"])

    neo_fin_Key = os.getenv("NEO_FIN_KEY")
    consumer_key = os.getenv("CONSUMER_KEY")
    environment = os.getenv("ENV", "prod")
    mobile_no = os.getenv("MOBILE_NO")
    ucc = os.getenv("UCC")
    # Prefer environment variable, otherwise request TOTP interactively
    totp = os.getenv("TOTP")
    if not totp:
        try:
            totp = getpass.getpass("Enter TOTP (input hidden): ").strip()
            if totp == "":
                totp = None
        except Exception:
            totp = None

    mpin = os.getenv("MPIN")

    # Create client
    _neo = NeoAPI(environment=environment, access_token=None, neo_fin_key=neo_fin_Key, consumer_key=consumer_key)

    # Try login + 2FA with a small retry/backoff loop
    max_attempts = 1
    backoff = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            if _neo:
                _LOGGER.info("Logging in to Neo API (attempt %d)", attempt)
                _neo.totp_login(mobile_number=mobile_no, ucc=ucc, totp=totp)

                _LOGGER.info("Kotak Neo API session established.")
                _neo.totp_validate(mpin=mpin)
                _LOGGER.info("Kotak Neo API session validated.")
                return _neo

        except ApiException as e:
            msg = str(e)
            _LOGGER.warning("Login attempt %d failed: %s", attempt, msg)
            # If auth-related, invalidate client and re-raise after final attempt
            if attempt == max_attempts:
                _LOGGER.exception("Login failed after %d attempts", attempt)
                raise
        except Exception as e:
            _LOGGER.warning("Unexpected error during login attempt %d: %s", attempt, e)
            if attempt == max_attempts:
                _LOGGER.exception("Login failed after %d attempts", attempt)
                raise

        time.sleep(backoff)
        backoff *= 2

    # If we fall through (shouldn't happen), raise a runtime error
    raise RuntimeError("Unable to establish Neo API session")


# ----------------------------------------------------
# 2. SEARCH FUNCTION
# ----------------------------------------------------
def search_stock(symbol: str) -> Optional[Dict[str, Any]]:
    """Search stock in NSE-CM and return the first instrument metadata.

    Returns None when not found or when an API error occurs.
    """
    if not symbol or not symbol.strip():
        raise ValueError("symbol must be a non-empty string")

    client = _get_client()

    # Retry once on auth error after reinitializing the client
    for attempt in range(2):
        try:
            data = client.scrip_search(exchange_segment="nse_cm", symbol=symbol.upper())
            if not data or not data.get("data"):
                _LOGGER.info("No search results for symbol=%s", symbol)
                return None
            return data["data"][0]

        except ApiException as e:
            _LOGGER.warning("Search API error (attempt %d): %s", attempt + 1, e)
            if attempt == 0 and ("401" in str(e) or "Unauthorized" in str(e)):
                # Try to refresh session once
                _LOGGER.info("Auth error during search — refreshing session and retrying")
                _invalidate_session()
                client = _get_client()
                continue
            return None
        except Exception as e:
            _LOGGER.exception("Unexpected error during search: %s", e)
            return None


def _invalidate_session():
    global _neo
    _neo = None


# ----------------------------------------------------
# 3. BUY FUNCTION
# ----------------------------------------------------
# def buy_stock(symbol: str, qty: int, price: Optional[float] = None) -> Optional[Dict[str, Any]]:
#     """Place a Buy order for NSE cash market. If `price` is None a market
#     order will be placed.
#     """
#     if qty <= 0:
#         raise ValueError("qty must be a positive integer")
#     if price is not None and price < 0:
#         raise ValueError("price must be a non-negative number or None")

#     client = _get_client()
#     result = search_stock(symbol)
#     if not result:
#         _LOGGER.info("Stock not found: %s", symbol)
#         return None

#     token = result.get("instrument_token")
#     order_type = "MKT" if price is None else "L"

#     try:
#         order = client.place_order(
#             exchange_segment="nse_cm",
#             transaction_type="B",
#             product="CNC",
#             instrument_token=str(token),
#             price=(price if price is not None else 0),
#             quantity=qty,
#             order_type=order_type,
#             validity="DAY",
#         )
#         _LOGGER.info("Buy order placed: %s", {k: order.get(k) for k in ("order_id", "status") if order})
#         return order

#     except ApiException as e:
#         _LOGGER.warning("Buy order failed: %s", e)
#         # If auth error, try once after refreshing session
#         if "401" in str(e) or "Unauthorized" in str(e):
#             _LOGGER.info("Auth error during buy — refreshing session and retrying once")
#             _invalidate_session()
#             return buy_stock(symbol, qty, price)
#         return None



# # ----------------------------------------------------
# # 4. SELL FUNCTION
# # ----------------------------------------------------
# def sell_stock(symbol: str, qty: int, price: Optional[float] = None) -> Optional[Dict[str, Any]]:
#     """Place a Sell order for NSE cash market. If `price` is None a market
#     order will be placed.
#     """
#     if qty <= 0:
#         raise ValueError("qty must be a positive integer")
#     if price is not None and price < 0:
#         raise ValueError("price must be a non-negative number or None")

#     client = _get_client()
#     result = search_stock(symbol)
#     if not result:
#         _LOGGER.info("Stock not found: %s", symbol)
#         return None

#     token = result.get("instrument_token")
#     order_type = "MKT" if price is None else "L"

#     try:
#         order = client.place_order(
#             exchange_segment="nse_cm",
#             transaction_type="S",
#             product="CNC",
#             instrument_token=str(token),
#             price=(price if price is not None else 0),
#             quantity=qty,
#             order_type=order_type,
#             validity="DAY",
#         )
#         _LOGGER.info("Sell order placed: %s", {k: order.get(k) for k in ("order_id", "status") if order})
#         return order

#     except ApiException as e:
#         _LOGGER.warning("Sell order failed: %s", e)
#         if "401" in str(e) or "Unauthorized" in str(e):
#             _LOGGER.info("Auth error during sell — refreshing session and retrying once")
#             _invalidate_session()
#             return sell_stock(symbol, qty, price)
#         return None
