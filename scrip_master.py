#!/usr/bin/env python3
"""
Kotak Neo Scrip Master API Integration.

Provides functionality to:
1. Fetch scrip master file paths from Kotak Neo API (/script-details/1.0/masterscrip/file-paths)
2. Download scrip master CSV files across all or specific exchange segments
3. Parse and search instrument details (pSymbol, pExchSeg, pTrdSymbol, lLotSize, lExpiryDate)
4. Convert expiry dates to human-readable IST datetime
"""

import os
import sys
import csv
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Union, Any

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_LOGGER = logging.getLogger("scrip_master")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
NSE_CDE_EPOCH_OFFSET = 315511200  # Offset documented in Scrip Master API for nse_fo and cde_fo
DEFAULT_BASE_URL = "https://napi.kotaksecurities.com"
DEFAULT_CACHE_DIR = "scrip_master_data"

KNOWN_SEGMENTS = ["nse_cm", "bse_cm", "nse_fo", "bse_fo", "cde_fo", "mcx_fo", "nse_com"]


def parse_expiry_date(epoch_val: Union[int, float, str, None], segment: Optional[str] = None) -> Optional[str]:
    """
    Converts epoch expiry date to IST human-readable string.
    Rules:
    - nse_fo and cde_fo: Add 315511200 to epoch value and convert to IST.
    - mcx_fo and bse_fo: Direct epoch value converted to IST.
    """
    if epoch_val is None or epoch_val == "":
        return None

    try:
        epoch = float(epoch_val)
    except (ValueError, TypeError):
        return None

    if epoch <= 0:
        return None

    seg = segment.lower() if segment else ""
    if seg in ("nse_fo", "cde_fo"):
        epoch += NSE_CDE_EPOCH_OFFSET

    try:
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(IST_TIMEZONE)
        return dt.strftime("%Y-%m-%d %H:%M:%S IST")
    except (OverflowError, OSError, ValueError):
        return None


def extract_segment_from_url(url: str) -> str:
    """
    Extracts the exchange segment identifier from a scrip master download URL.
    E.g.
    'https://.../transformed-v1/nse_cm-v1.csv' -> 'nse_cm'
    'https://.../transformed/cde_fo.csv' -> 'cde_fo'
    """
    filename = url.split("?")[0].rstrip("/").split("/")[-1].lower()
    base_name = filename.replace(".csv", "").replace("-v1", "").replace("_v1", "")

    for seg in KNOWN_SEGMENTS:
        if seg in base_name:
            return seg
    return base_name


class ScripMasterClient:
    """
    Client for Kotak Neo Scrip Master API.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
    ):
        self.api_token = api_token or os.getenv("NEO_API_TOKEN") or os.getenv("NEO_TOKEN")
        raw_base_url = base_url or os.getenv("NEO_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = raw_base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)

    def get_master_file_paths(self) -> Dict[str, Any]:
        """
        Calls GET <Base URL>/script-details/1.0/masterscrip/file-paths.
        Returns the data dictionary containing 'filesPaths' and 'baseFolder'.
        """
        if not self.api_token:
            raise RuntimeError(
                "Missing API token. Provide it via NEO_API_TOKEN env var or --token argument."
            )

        endpoint = f"{self.base_url}/script-details/1.0/masterscrip/file-paths"
        headers = {
            "Authorization": self.api_token,
            "Accept": "application/json",
        }

        _LOGGER.info("Fetching scrip master file paths from %s", endpoint)
        try:
            response = requests.get(endpoint, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise RuntimeError(f"Network error while connecting to Scrip Master API: {e}") from e

        if response.status_code == 401:
            raise RuntimeError("Unauthorized: Invalid or missing API token (HTTP 401)")
        elif response.status_code == 403:
            raise RuntimeError("Forbidden: Not enough privileges (HTTP 403)")
        elif response.status_code == 429:
            raise RuntimeError("Too many requests: API rate limited (HTTP 429)")
        elif response.status_code >= 500:
            raise RuntimeError(f"Server error from Scrip Master API (HTTP {response.status_code})")

        try:
            response.raise_for_status()
            res_json = response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to parse Scrip Master API response: {e}") from e

        data = res_json.get("data", {})
        if not data or "filesPaths" not in data:
            raise RuntimeError(f"Unexpected response format: 'data.filesPaths' missing: {res_json}")

        return data

    def download_file(self, url: str, target_path: Path) -> Path:
        """
        Streams download of a file from url to target_path.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _LOGGER.info("Downloading %s to %s", url, target_path)

        try:
            with requests.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to download file from {url}: {e}") from e

        return target_path

    def download_segments(
        self,
        segments: Optional[Union[str, List[str]]] = None,
        output_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Path]:
        """
        Downloads CSV master files.
        :param segments: Optional single segment string, comma-separated string, or list of segments.
                         If None or empty, downloads all available segments.
        :param output_dir: Directory where CSV files should be saved (defaults to self.cache_dir).
        :return: Dict mapping segment name to downloaded Path.
        """
        out_path = Path(output_dir) if output_dir else self.cache_dir
        out_path.mkdir(parents=True, exist_ok=True)

        data = self.get_master_file_paths()
        urls: List[str] = data.get("filesPaths", [])

        # Parse requested segments (if any)
        filter_segments = None
        if segments:
            if isinstance(segments, str):
                filter_segments = {s.strip().lower() for s in segments.split(",") if s.strip()}
            else:
                filter_segments = {s.strip().lower() for s in segments if s and s.strip()}

        downloaded: Dict[str, Path] = {}

        for url in urls:
            seg = extract_segment_from_url(url)
            if filter_segments and seg not in filter_segments:
                continue

            dest_filename = f"{seg}.csv"
            dest_file = out_path / dest_filename
            self.download_file(url, dest_file)
            downloaded[seg] = dest_file

        return downloaded

    def search_scrip(
        self,
        query: str,
        segment: Optional[str] = None,
        search_by: str = "symbol",
        cache_dir: Optional[Union[str, Path]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Searches cached CSV master files for matching symbols or tokens.
        :param query: Symbol or token to search for (e.g. 'RELIANCE', '11536').
        :param segment: Optional segment name (e.g. 'nse_cm'). If omitted, searches all available CSVs.
        :param search_by: 'symbol' (matches pTrdSymbol or pSymbol) or 'token' (exact match on pSymbol).
        :param cache_dir: Directory containing cached CSVs (defaults to self.cache_dir).
        :return: List of matching records with parsed expiry dates.
        """
        search_path = Path(cache_dir) if cache_dir else self.cache_dir
        if not search_path.exists():
            _LOGGER.warning("Cache directory %s does not exist. Run with --download first.", search_path)
            return []

        csv_files: List[Path] = []
        if segment:
            seg_lower = segment.strip().lower()
            matching_file = search_path / f"{seg_lower}.csv"
            if matching_file.exists():
                csv_files.append(matching_file)
            else:
                # Look for matching pattern
                csv_files.extend(search_path.glob(f"*{seg_lower}*.csv"))
        else:
            csv_files = sorted(list(search_path.glob("*.csv")))

        if not csv_files:
            _LOGGER.warning("No CSV files found in %s to search.", search_path)
            return []

        results: List[Dict[str, Any]] = []
        query_upper = query.strip().upper()

        for csv_file in csv_files:
            try:
                with open(csv_file, mode="r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        p_symbol = (row.get("pSymbol") or row.get("psymbol") or "").strip()
                        p_trd_symbol = (row.get("pTrdSymbol") or row.get("ptrdsymbol") or "").strip()
                        p_exch_seg = (row.get("pExchSeg") or row.get("pexchseg") or "").strip()
                        l_lot_size = (row.get("lLotSize") or row.get("llotsize") or "").strip()
                        l_expiry_date = (row.get("lExpiryDate") or row.get("lexpirydate") or "").strip()

                        is_match = False
                        if search_by == "token":
                            if query_upper == p_symbol.upper():
                                is_match = True
                        else:  # default 'symbol'
                            if query_upper in p_trd_symbol.upper() or query_upper in p_symbol.upper():
                                is_match = True

                        if is_match:
                            parsed_expiry = parse_expiry_date(l_expiry_date, p_exch_seg)
                            item = dict(row)
                            item["pSymbol"] = p_symbol
                            item["pTrdSymbol"] = p_trd_symbol
                            item["pExchSeg"] = p_exch_seg
                            item["lLotSize"] = l_lot_size
                            item["lExpiryDate"] = l_expiry_date
                            item["formattedExpiryDate"] = parsed_expiry
                            results.append(item)
            except Exception as e:
                _LOGGER.error("Error reading %s: %s", csv_file, e)

        return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kotak Neo Scrip Master API tool for downloading and searching instruments."
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download scrip master CSV files (segment is optional; defaults to all segments)",
    )
    parser.add_argument(
        "--list-urls",
        action="store_true",
        help="List available scrip master CSV download URLs from the API",
    )
    parser.add_argument(
        "--segment",
        default=None,
        help="Optional exchange segment (e.g. nse_cm, nse_fo). If omitted, processes all segments.",
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        default=None,
        help="Search for a symbol or token in cached CSV files (segment is optional)",
    )
    parser.add_argument(
        "--search-by",
        choices=["symbol", "token"],
        default="symbol",
        help="Field to search by: 'symbol' (default) or 'token'",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_CACHE_DIR,
        help=f"Directory to save/read CSV master files (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Kotak Neo API token (defaults to NEO_API_TOKEN env var)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"Kotak Neo Base URL (defaults to NEO_BASE_URL env var or {DEFAULT_BASE_URL})",
    )

    args = parser.parse_args()

    client = ScripMasterClient(
        api_token=args.token,
        base_url=args.base_url,
        cache_dir=args.output_dir,
    )

    if args.list_urls:
        try:
            data = client.get_master_file_paths()
            print("Base Folder:", data.get("baseFolder", "N/A"))
            print("Files Paths:")
            for url in data.get("filesPaths", []):
                seg = extract_segment_from_url(url)
                print(f"  - [{seg}] {url}")
        except Exception as e:
            print(f"Error listing file paths: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.download:
        try:
            print(f"Downloading master CSV files to '{args.output_dir}'...")
            downloaded = client.download_segments(segments=args.segment, output_dir=args.output_dir)
            if downloaded:
                print(f"Successfully downloaded {len(downloaded)} segment file(s):")
                for seg, path in downloaded.items():
                    print(f"  - {seg}: {path}")
            else:
                print("No files were downloaded. Verify segments or API response.")
        except Exception as e:
            print(f"Error downloading files: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.search:
        results = client.search_scrip(
            query=args.search,
            segment=args.segment,
            search_by=args.search_by,
            cache_dir=args.output_dir,
        )
        if not results:
            print(f"No instruments found matching '{args.search}'.")
        else:
            print(f"Found {len(results)} matching instrument(s):")
            header = f"{'Symbol (pSymbol)':<18} {'Segment (es)':<14} {'Trading Symbol (ts)':<24} {'Lot Size (qt)':<14} {'Expiry (IST)':<24}"
            print(header)
            print("-" * len(header))
            for item in results:
                p_sym = item.get("pSymbol", "")
                p_seg = item.get("pExchSeg", "")
                p_trd = item.get("pTrdSymbol", "")
                p_lot = item.get("lLotSize", "")
                expiry = item.get("formattedExpiryDate") or "N/A"
                print(f"{p_sym:<18} {p_seg:<14} {p_trd:<24} {p_lot:<14} {expiry:<24}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
