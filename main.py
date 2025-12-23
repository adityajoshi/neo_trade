import os
import logging
import getpass
from typing import Optional, Dict, Any

from neo_api_client import NeoAPI
from neo_api_client.exceptions import ApiException

# Optional dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


_LOGGER = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


class SessionManager:
    def __init__(self):
        self._client: Optional[NeoAPI] = None

    # ----------------------------
    # Internal helpers
    # ----------------------------
    def _require_env_vars(self, names):
        missing = [n for n in names if not os.getenv(n)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

    def _invalidate(self):
        _LOGGER.warning("Invalidating Neo API session")
        self._client = None

    def _authenticate(self) -> NeoAPI:
        """Create + fully authenticate a new NeoAPI client."""
        self._require_env_vars(
            ["NEO_FIN_KEY", "CONSUMER_KEY", "MOBILE_NO", "UCC", "MPIN"]
        )

        neo = NeoAPI(
            environment=os.getenv("ENV", "prod"),
            access_token=None,
            neo_fin_key=os.getenv("NEO_FIN_KEY"),
            consumer_key=os.getenv("CONSUMER_KEY"),
        )

        totp = os.getenv("TOTP") or getpass.getpass("Enter TOTP: ")

        _LOGGER.info("Performing Neo API login")
        neo.totp_login(
            mobile_number=os.getenv("MOBILE_NO"),
            ucc=os.getenv("UCC"),
            totp=totp,
        )

        neo.totp_validate(mpin=os.getenv("MPIN"))

        _LOGGER.info("Neo API session fully authenticated")
        return neo

    def get_client(self) -> NeoAPI:
        """Public gatekeeper. Always returns a fully authenticated client."""
        if self._client:
            return self._client

        self._client = self._authenticate()
        return self._client

    # ----------------------------
    # Public API wrappers
    # ----------------------------
    def search_stock(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not symbol or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")

        for attempt in range(2):
            try:
                client = self.get_client()
                data = client.search_scrip(
                    exchange_segment="nse_cm",
                    symbol=symbol.upper(),
                    expiry="",
                    option_type="",
                    strike_price="",
                )

                if not data or not data.get("data"):
                    _LOGGER.info("No search results for %s", symbol)
                    return None

                return data["data"][0]

            except ApiException as e:
                _LOGGER.warning("Search failed (attempt %d): %s", attempt + 1, e)
                if attempt == 0 and self._is_auth_error(e):
                    self._invalidate()
                    continue
                return None

    def buy_stock(
        self,
        symbol: str,
        qty: int,
        price: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if qty <= 0:
            raise ValueError("qty must be positive")

        result = self.search_stock(symbol)
        if not result:
            return None

        order_type = "MKT" if price is None else "L"

        for attempt in range(2):
            try:
                client = self.get_client()
                return client.place_order(
                    exchange_segment="nse_cm",
                    transaction_type="B",
                    product="CNC",
                    instrument_token=str(result["instrument_token"]),
                    price=price or 0,
                    quantity=qty,
                    order_type=order_type,
                    validity="DAY",
                )

            except ApiException as e:
                _LOGGER.warning("Buy failed (attempt %d): %s", attempt + 1, e)
                if attempt == 0 and self._is_auth_error(e):
                    self._invalidate()
                    continue
                return None

    def sell_stock(
        self,
        symbol: str,
        qty: int,
        price: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if qty <= 0:
            raise ValueError("qty must be positive")

        result = self.search_stock(symbol)
        if not result:
            return None

        order_type = "MKT" if price is None else "L"

        for attempt in range(2):
            try:
                client = self.get_client()
                return client.place_order(
                    exchange_segment="nse_cm",
                    transaction_type="S",
                    product="CNC",
                    instrument_token=str(result["instrument_token"]),
                    price=price or 0,
                    quantity=qty,
                    order_type=order_type,
                    validity="DAY",
                )

            except ApiException as e:
                _LOGGER.warning("Sell failed (attempt %d): %s", attempt + 1, e)
                if attempt == 0 and self._is_auth_error(e):
                    self._invalidate()
                    continue
                return None

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc)
        return "401" in msg or "Unauthorized" in msg or "2fa" in msg.lower()
