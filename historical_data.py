#!/usr/bin/env python3
"""
Kotak Neo Historical Data API Integration.

Provides functionality to:
1. Resolve symbols/scrips (e.g. 'BEL', 'NIFTY') to neosymbol (<segment>|<token>) via local scrip master cache.
2. Validate date range and interval against predefined rate-limiting rules before firing requests.
3. Slice date range into valid non-overlapping chunks per interval limits.
4. Concurrently fetch candle data across all chunks under a single 2FA authentication session.
5. Deduplicate, sort chronologically, and save results to CSV in a dedicated output directory.
"""

import os
import sys
import csv
import time
import logging
import argparse
import getpass
import concurrent.futures
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional, Union, Any

import requests

try:
    from neo_api_client import NeoAPI
    from neo_api_client.exceptions import ApiException
except ImportError:
    NeoAPI = None  # type: ignore

    class ApiException(Exception):  # type: ignore
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_LOGGER = logging.getLogger("historical_data")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

# Interval maximum days per single request as documented in historical_data.md
INTERVAL_MAX_DAYS: Dict[str, int] = {
    "1min": 30,
    "3min": 30,
    "5min": 30,
    "10min": 60,
    "15min": 60,
    "30min": 90,
    "60min": 90,
    "D": 180,
    "W": 180,
}

# Predefined rate-limit safety rules
MAX_ALLOWED_CHUNKS = 15

MAX_TOTAL_SPAN_DAYS: Dict[str, int] = {
    "1min": 180,    # Max 6 months (6 chunks of 30d)
    "3min": 180,    # Max 6 months (6 chunks of 30d)
    "5min": 180,    # Max 6 months (6 chunks of 30d)
    "10min": 365,   # Max 1 year (~6 chunks of 60d)
    "15min": 365,   # Max 1 year (~6 chunks of 60d)
    "30min": 730,   # Max 2 years (~8 chunks of 90d)
    "60min": 730,   # Max 2 years (~8 chunks of 90d)
    "D": 1825,      # Max 5 years (~10 chunks of 180d, Kotak retention limit)
    "W": 1825,      # Max 5 years (~10 chunks of 180d, Kotak retention limit)
}

RETENTION_INCEPTION_DATE = date(2021, 1, 1)
SUPPORTED_SEGMENTS = ["nse_cm", "nse_fo", "bse_cm", "bse_fo"]
DEFAULT_OUTPUT_DIR = "historical_data_output"
DEFAULT_SCRIP_DIR = "scrip_master_data"
DEFAULT_BASE_URL = "https://napi.kotaksecurities.com"


def require_env_vars(names: List[str]) -> None:
    """
    Validates that the specified environment variables are set.
    """
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


def login_client(totp: str, cred_details: Dict[str, Any]) -> Optional[Any]:
    """
    Authenticates with Kotak Neo using NeoAPI via TOTP and MPIN validation.
    """
    if NeoAPI is None:
        raise RuntimeError("neo_api_client module is not installed.")

    client = NeoAPI(
        consumer_key=cred_details["consumer_key"],
        environment="prod",
        access_token=None,
        neo_fin_key=cred_details.get("neo_fin_key") or None,
    )
    if client:
        try:
            client.totp_login(
                mobile_number=cred_details["mobno"], ucc=cred_details["ucc"], totp=totp
            )
            client.totp_validate(mpin=cred_details["mpin"])
        except ApiException as e:
            _LOGGER.error("Network/API error during login: %s", e)
            return None
    return client


def parse_date(date_str: str) -> date:
    """
    Parses a YYYY-MM-DD date string.
    """
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format '{date_str}'. Expected 'YYYY-MM-DD'.")


def validate_and_generate_chunks(
    from_date: Union[date, str],
    to_date: Union[date, str],
    interval: str,
    max_allowed_chunks: int = MAX_ALLOWED_CHUNKS,
) -> List[Tuple[str, str]]:
    """
    Validates the date range against predefined rate-limit safety rules and generates
    contiguous non-overlapping chunks.
    """
    if isinstance(from_date, str):
        from_date = parse_date(from_date)
    if isinstance(to_date, str):
        to_date = parse_date(to_date)

    if interval not in INTERVAL_MAX_DAYS:
        valid_intervals = ", ".join(INTERVAL_MAX_DAYS.keys())
        raise ValueError(f"Invalid interval '{interval}'. Supported intervals: {valid_intervals}")

    if from_date > to_date:
        raise ValueError(f"from_date ({from_date}) cannot be later than to_date ({to_date}).")

    today = datetime.now().date()
    if to_date > today:
        raise ValueError(f"to_date ({to_date}) cannot be in the future (today is {today}).")

    if from_date < RETENTION_INCEPTION_DATE:
        raise ValueError(
            f"from_date ({from_date}) is earlier than Kotak Neo's data retention limit ({RETENTION_INCEPTION_DATE})."
        )

    total_span_days = (to_date - from_date).days + 1
    max_span = MAX_TOTAL_SPAN_DAYS[interval]
    if total_span_days > max_span:
        raise ValueError(
            f"Requested span of {total_span_days} days exceeds the maximum allowed span of {max_span} days for interval '{interval}'."
        )

    chunk_max_days = INTERVAL_MAX_DAYS[interval]
    chunks: List[Tuple[str, str]] = []
    curr_start = from_date
    while curr_start <= to_date:
        curr_end = min(curr_start + timedelta(days=chunk_max_days - 1), to_date)
        chunks.append((curr_start.strftime("%Y-%m-%d"), curr_end.strftime("%Y-%m-%d")))
        curr_start = curr_end + timedelta(days=1)

    if len(chunks) > max_allowed_chunks:
        raise ValueError(
            f"Requested date range requires {len(chunks)} chunks for interval '{interval}', "
            f"which exceeds the maximum allowed safety threshold of {max_allowed_chunks} chunks to prevent rate-limiting (HTTP 429)."
        )

    return chunks


def resolve_neosymbol(
    symbol: str,
    segment: Optional[str] = "nse_cm",
    scrip_dir: Union[str, Path] = DEFAULT_SCRIP_DIR,
) -> Tuple[str, str]:
    """
    Resolves an instrument symbol to (exchange_segment, instrument_token).
    Supports:
    1. Direct neosymbol format: e.g. "nse_cm|26000"
    2. Symbol names such as 'BEL', 'NIFTY', 'RELIANCE-EQ' resolved from local scrip master CSVs.
    """
    sym_trimmed = symbol.strip()
    if "|" in sym_trimmed:
        parts = sym_trimmed.split("|")
        if len(parts) == 2 and parts[0] in SUPPORTED_SEGMENTS and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
        raise ValueError(f"Invalid neosymbol format '{sym_trimmed}'. Expected '<segment>|<token>'.")

    scrip_path = Path(scrip_dir)
    if not scrip_path.exists():
        raise FileNotFoundError(
            f"Scrip master cache directory '{scrip_path}' does not exist. "
            f"Please download scrip master files first using 'python scrip_master.py --download'."
        )

    query = sym_trimmed.upper()
    target_segment = segment.strip().lower() if segment else "nse_cm"
    if target_segment not in SUPPORTED_SEGMENTS:
        raise ValueError(f"Unsupported segment '{target_segment}'. Supported segments: {', '.join(SUPPORTED_SEGMENTS)}")

    csv_files: List[Path] = []
    seg_file = scrip_path / f"{target_segment}.csv"
    if seg_file.exists():
        csv_files.append(seg_file)
    else:
        csv_files = sorted(list(scrip_path.glob(f"*{target_segment}*.csv")))

    if not csv_files:
        csv_files = sorted(list(scrip_path.glob("*.csv")))

    if not csv_files:
        raise FileNotFoundError(
            f"No scrip master CSV files found in '{scrip_path}'. "
            f"Please download scrip master files first using 'python scrip_master.py --download'."
        )

    exact_symbol_name_match = None
    exact_trd_symbol_match = None
    suffix_match = None
    token_match = None

    for csv_file in csv_files:
        try:
            with open(csv_file, mode="r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    p_symbol = (row.get("pSymbol") or row.get("psymbol") or "").strip()
                    p_trd_symbol = (row.get("pTrdSymbol") or row.get("ptrdsymbol") or "").strip()
                    p_symbol_name = (row.get("pSymbolName") or row.get("psymbolname") or "").strip()
                    p_exch_seg = (row.get("pExchSeg") or row.get("pexchseg") or "").strip().lower()

                    if p_exch_seg not in SUPPORTED_SEGMENTS:
                        continue

                    is_target_segment = (p_exch_seg == target_segment)

                    # 1. Exact match on pSymbolName (e.g. 'BEL')
                    if query == p_symbol_name.upper():
                        if is_target_segment:
                            return p_exch_seg, p_symbol
                        elif not exact_symbol_name_match:
                            exact_symbol_name_match = (p_exch_seg, p_symbol)

                    # 2. Exact match on pTrdSymbol (e.g. 'BEL-EQ' or 'NIFTY')
                    if query == p_trd_symbol.upper():
                        if is_target_segment:
                            return p_exch_seg, p_symbol
                        elif not exact_trd_symbol_match:
                            exact_trd_symbol_match = (p_exch_seg, p_symbol)

                    # 3. Suffix variations (e.g., query 'BEL' matching 'BEL-EQ')
                    if f"{query}-EQ" == p_trd_symbol.upper() or query.replace("-EQ", "") == p_symbol_name.upper():
                        if is_target_segment:
                            suffix_match = (p_exch_seg, p_symbol)
                        elif not suffix_match:
                            suffix_match = (p_exch_seg, p_symbol)

                    # 4. Token match
                    if query == p_symbol.upper():
                        if is_target_segment:
                            token_match = (p_exch_seg, p_symbol)
                        elif not token_match:
                            token_match = (p_exch_seg, p_symbol)
        except Exception as e:
            _LOGGER.warning("Error reading %s: %s", csv_file, e)

    match = exact_symbol_name_match or exact_trd_symbol_match or suffix_match or token_match
    if match:
        return match

    raise ValueError(
        f"Could not resolve instrument token for symbol '{symbol}' in segment '{target_segment}'. "
        f"Please check the symbol or provide direct format '<segment>|<token>'."
    )


class HistoricalDataClient:
    """
    Client for fetching historical candle data concurrently across multiple chunks.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        base_url: Optional[str] = None,
        max_workers: int = 5,
        consumer_key: Optional[str] = None,
    ):
        self.client = client
        raw_base_url = base_url or os.getenv("NEO_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = raw_base_url.rstrip("/")
        self.max_workers = max_workers
        self.consumer_key = consumer_key or os.getenv("CONSUMER_KEY")

    def _get_auth_token(self) -> str:
        """
        Extracts authorization token from NeoAPI client or consumer key.
        """
        token = ""
        if self.client:
            # Check for configuration bearer token
            cfg = getattr(self.client, "configuration", None)
            if cfg and getattr(cfg, "bearer_token", None):
                token = cfg.bearer_token
            elif getattr(self.client, "access_token", None):
                token = self.client.access_token

        return token or self.consumer_key or ""

    def fetch_chunk(
        self,
        neosymbol: str,
        from_date: str,
        to_date: str,
        interval: str,
        max_retries: int = 3,
    ) -> List[List[Any]]:
        """
        Fetches candle data for a single date chunk.
        Handles rate-limiting (HTTP 429) with retries and exponential backoff.
        """
        if self.client and hasattr(self.client, "historical_data"):
            try:
                res = self.client.historical_data(
                    neosymbol=neosymbol,
                    fromdate=from_date,
                    todate=to_date,
                    interval=interval,
                )
                return self._parse_candles(res)
            except Exception as e:
                _LOGGER.debug("SDK historical_data method raised %s, attempting REST call", e)

        endpoint = f"{self.base_url}/market-data/1.0/historical/details"
        params = {
            "neosymbol": neosymbol,
            "fromdate": from_date,
            "todate": to_date,
            "interval": interval,
        }
        headers = {
            "Authorization": self._get_auth_token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for attempt in range(max_retries):
            try:
                response = requests.get(endpoint, params=params, headers=headers, timeout=30)
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 1.5 * (attempt + 1)))
                    _LOGGER.warning(
                        "Rate limited (HTTP 429) for chunk %s to %s. Retrying in %.1fs (attempt %d/%d)...",
                        from_date, to_date, retry_after, attempt + 1, max_retries
                    )
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                res_json = response.json()
                return self._parse_candles(res_json)
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Failed to fetch historical data for chunk {from_date} to {to_date}: {e}") from e
                time.sleep(1.0 * (attempt + 1))

        return []

    def _parse_candles(self, res: Any) -> List[List[Any]]:
        if not isinstance(res, dict):
            return []
        data = res.get("data", {})
        if isinstance(data, dict):
            return data.get("candles", []) or []
        return []

    def fetch_historical_data(
        self,
        neosymbol: str,
        chunks: List[Tuple[str, str]],
        interval: str,
    ) -> List[List[Any]]:
        """
        Concurrently dispatches requests across all chunks, merges, deduplicates,
        and sorts candles in ascending chronological order.
        """
        if not chunks:
            return []

        all_candles: List[List[Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_chunk = {
                executor.submit(self.fetch_chunk, neosymbol, start, end, interval): (start, end)
                for start, end in chunks
            }

            for future in concurrent.futures.as_completed(future_to_chunk):
                start, end = future_to_chunk[future]
                try:
                    candles = future.result()
                    all_candles.extend(candles)
                except Exception as e:
                    _LOGGER.error("Error fetching chunk %s to %s: %s", start, end, e)
                    raise

        # Deduplicate by timestamp (index 0)
        seen_timestamps = set()
        unique_candles = []
        for candle in all_candles:
            if candle and len(candle) >= 5:
                ts = str(candle[0])
                if ts not in seen_timestamps:
                    seen_timestamps.add(ts)
                    unique_candles.append(candle)

        # Sort chronologically by ISO 8601 timestamp string
        unique_candles.sort(key=lambda c: str(c[0]))
        return unique_candles


def save_candles_to_csv(
    candles: List[List[Any]],
    output_path: Union[str, Path],
) -> Path:
    """
    Saves candle rows into CSV file in the standard format.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = ["timestamp", "open", "high", "low", "close", "volume", "oi"]
    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for c in candles:
            writer.writerow(c)

    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kotak Neo Historical Data tool for fetching and chunking OHLCV candles to CSV."
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Stock/Index trading symbol (e.g. 'BEL', 'NIFTY', 'RELIANCE-EQ') or direct neosymbol ('nse_cm|26000')",
    )
    parser.add_argument(
        "--from-date",
        required=True,
        help="Start date in YYYY-MM-DD format (must be on or after 2021-01-01)",
    )
    parser.add_argument(
        "--to-date",
        required=True,
        help="End date in YYYY-MM-DD format (up to today)",
    )
    parser.add_argument(
        "--interval",
        required=True,
        choices=list(INTERVAL_MAX_DAYS.keys()),
        help=f"Candle interval: {', '.join(INTERVAL_MAX_DAYS.keys())}",
    )
    parser.add_argument(
        "--segment",
        default="nse_cm",
        choices=SUPPORTED_SEGMENTS,
        help="Exchange segment (default: nse_cm)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Custom output CSV file path (defaults to historical_data_output/<symbol>_<segment>_<interval>_<from>_<to>.csv)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save CSV output (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--scrip-dir",
        default=DEFAULT_SCRIP_DIR,
        help=f"Directory containing cached scrip master CSV files (default: {DEFAULT_SCRIP_DIR})",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Maximum concurrent workers for simultaneous requests (default: 5)",
    )

    args = parser.parse_args()

    # Step 1: Pre-API validation rules & chunk generation
    try:
        chunks = validate_and_generate_chunks(
            from_date=args.from_date,
            to_date=args.to_date,
            interval=args.interval,
        )
    except ValueError as e:
        print(f"Validation Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Validated date range: {args.from_date} to {args.to_date} for interval '{args.interval}'.")
    print(f"Divided into {len(chunks)} chunk(s) (max {INTERVAL_MAX_DAYS[args.interval]} days per chunk).")

    # Step 2: Resolve neosymbol via local scrip master cache
    try:
        seg, token = resolve_neosymbol(
            symbol=args.symbol,
            segment=args.segment,
            scrip_dir=args.scrip_dir,
        )
        neosymbol = f"{seg}|{token}"
        print(f"Resolved symbol '{args.symbol}' -> neosymbol: {neosymbol}")
    except Exception as e:
        print(f"Symbol Resolution Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Single 2FA Authentication
    try:
        require_env_vars(["CONSUMER_KEY", "MOBILE_NO", "UCC", "MPIN"])
    except RuntimeError as e:
        print(f"Authentication Config Error: {e}", file=sys.stderr)
        sys.exit(1)

    cred_details = {
        "neo_fin_key": os.getenv("NEO_FIN_KEY"),
        "consumer_key": os.getenv("CONSUMER_KEY"),
        "ucc": os.getenv("UCC"),
        "mobno": os.getenv("MOBILE_NO"),
        "mpin": os.getenv("MPIN"),
    }

    totp = getpass.getpass("Enter TOTP: ")
    neo_client = login_client(totp, cred_details)
    if not neo_client:
        print("Failed to authenticate with Kotak Neo. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Step 4: Simultaneous chunk fetching
    client = HistoricalDataClient(
        client=neo_client,
        max_workers=args.max_workers,
        consumer_key=cred_details["consumer_key"],
    )

    print(f"Fetching {len(chunks)} chunk(s) concurrently (max_workers={args.max_workers})...")
    try:
        candles = client.fetch_historical_data(
            neosymbol=neosymbol,
            chunks=chunks,
            interval=args.interval,
        )
    except Exception as e:
        print(f"Error fetching historical data: {e}", file=sys.stderr)
        sys.exit(1)

    if not candles:
        print(f"No candle data returned for '{neosymbol}' in range {args.from_date} to {args.to_date}.")
        sys.exit(0)

    # Step 5: Save to CSV in output directory
    clean_sym = args.symbol.replace("|", "_").replace("/", "_")
    default_filename = f"{clean_sym}_{seg}_{args.interval}_{args.from_date}_{args.to_date}.csv"
    output_path = Path(args.output) if args.output else Path(args.output_dir) / default_filename

    saved_file = save_candles_to_csv(candles, output_path)
    print(f"Successfully saved {len(candles)} candle(s) to '{saved_file}'.")


if __name__ == "__main__":
    main()
