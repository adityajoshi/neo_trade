# Neo Trade

A Python project to automate stock trading using the NeoAPI client (Kotak Neo). It includes scripts to place orders from a CSV file and to search for stock scrips.

## Features
- **Automated Trading**: Reads trade instructions from a CSV file and places orders.
- **Scrip Search**: Utility to search for stock symbols and get details via NeoAPI.
- **Scrip Master Integration**: Downloads instrument master CSV files directly from Kotak Neo Scrip Master API, with caching, optional segment filtering, symbol/token search, and IST expiry date conversion.
- **Secure Authentication**: Uses environment variables for credentials and interactive TOTP for login.

## Prerequisites
- Python 3.12+ (Tested with 3.12 and 3.14)
- Kotak Neo API credentials (sign up at Kotak Neo API portal)

## Installation

1. Clone the repository (if applicable) or download the source code.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Copy the sample environment file to `.env`:
   ```bash
   cp sample.env .env
   ```

2. Edit `.env` and fill in your Kotak Neo credentials:
   ```ini
   NEO_FIN_KEY=your_neo_fin_key
   CONSUMER_KEY=your_consumer_key
   MOBILE_NO=your_mobile_number
   UCC=your_ucc
   MPIN=your_mpin
   ```

## Usage

### 1. Placing Orders (`main.py`)

This script reads trade instructions from `trades.csv`, authenticates, and places orders. It supports Market (`MKT`) and Limit (`L`) orders with the Cash N Carry (`CNC`) product type.

1. Create a `trades.csv` file in the project root. The format is **semicolon-separated** with the following columns:
   `stock_id;txn_type;quantity;order_type;price`

   *(Note: 4 columns `stock_id;txn_type;quantity;order_type` are also supported for backward compatibility, where price defaults to `0`)*.

   **Example `trades.csv`**:
   ```csv
   PAGEIND-EQ;B;1;MKT;0
   PGHH-EQ;B;1;L;45000
   ```
   - `stock_id`: Trading symbol (e.g., `PAGEIND-EQ`)
   - `txn_type`: Transaction type (`B` for Buy, `S` for Sell)
   - `quantity`: Number of shares (integer)
   - `order_type`: Order type (`MKT` for Market, `L` for Limit)
   - `price`: Limit price (required and positive for `L` orders; optional or `0` for `MKT` orders)

2. Run the script:
   ```bash
   python main.py
   ```

3. Enter your TOTP when prompted. The script will process each row in `trades.csv` and place the order.

### 2. Searching Scrips (`search.py`)

This utility allows you to search for a stock symbol in the NSE Cash Market (nse_cm) segment.

Run the script with the `--symbol` argument:
```bash
python search.py --symbol <STOCK_SYMBOL>
```

**Example:**
```bash
python search.py --symbol RELIANCE
```

This will output the scrip details returned by the API.

### 3. Scrip Master & Instrument Files (`scrip_master.py`)

This utility integrates with Kotak Neo's **Scrip Master API** to fetch CSV download paths, download scrip master files across exchange segments, and perform fast offline searches with parsed expiry dates.

#### A. List Available Master CSV URLs
```bash
python scrip_master.py --list-urls
```

#### B. Download Master CSV Files
Download all available exchange segments:
```bash
python scrip_master.py --download
```

Download specific segment(s) (`--segment` is optional, e.g. `nse_cm`, `nse_fo`, `bse_cm`):
```bash
python scrip_master.py --download --segment nse_cm
python scrip_master.py --download --segment nse_cm,nse_fo
```

Custom output folder (defaults to `scrip_master_data/`):
```bash
python scrip_master.py --download --output-dir my_data
```

#### C. Search Cached Scrips
Search for a symbol across all downloaded segments:
```bash
python scrip_master.py --search RELIANCE
```

Search within a specific segment:
```bash
python scrip_master.py --search RELIANCE --segment nse_fo
```

Search by exact instrument token:
```bash
python scrip_master.py --search 11536 --search-by token
```

#### D. Python Library Usage
```python
from neo_api_client import NeoAPI
from scrip_master import ScripMasterClient, login_client

# 1. Authenticate with NeoAPI
cred_details = {
    "consumer_key": "your_consumer_key",
    "mobno": "your_mobile_number",
    "ucc": "your_ucc",
    "mpin": "your_mpin",
    "neo_fin_key": "your_neo_fin_key",
}
neo_client = login_client(totp="123456", cred_details=cred_details)

# 2. Use ScripMasterClient with authenticated client
client = ScripMasterClient(client=neo_client)

# List file paths
data = client.get_master_file_paths()

# Download all segments (or specify segments=['nse_cm'])
downloaded = client.download_segments()

# Search across cached files (no auth required if files already downloaded)
search_client = ScripMasterClient()
results = search_client.search_scrip("RELIANCE")
for r in results:
    print(r["pTrdSymbol"], r["pExchSeg"], r["formattedExpiryDate"])
```

### 4. Historical Candle Data (`historical_data.py`)

This tool downloads historical OHLCV candlestick data across arbitrary date ranges, automatically chunking requests according to interval constraints, validating against rate-limit safety rules, resolving symbols (such as `BEL`, `NIFTY`, `RELIANCE`) from local scrip master files, and executing concurrent calls using consumer_key authentication.

#### A. Basic Usage
Fetch 15-minute historical candles for a stock:
```bash
python historical_data.py --symbol BEL --from-date 2025-01-01 --to-date 2025-03-31 --interval 15min
```

You can also pass the consumer key directly via `--consumer-key` (or set `CONSUMER_KEY` in your `.env`):
```bash
python historical_data.py --symbol BEL --from-date 2025-01-01 --to-date 2025-03-31 --interval 15min --consumer-key your-consumer-key
```

Fetch daily candles for an index:
```bash
python historical_data.py --symbol NIFTY --from-date 2024-01-01 --to-date 2024-12-31 --interval D
```

Specify a custom output path or directory:
```bash
python historical_data.py --symbol BEL --from-date 2025-01-01 --to-date 2025-02-15 --interval 5min --output-dir historical_data_output
```

#### B. Interval Limits & Predefined Safety Rules
The API imposes single-request date limits per interval. The script automatically divides requests into non-overlapping chunks:
* `1min`, `3min`, `5min`: Max **30 days** per chunk (Max total span: 180 days)
* `10min`, `15min`: Max **60 days** per chunk (Max total span: 365 days)
* `30min`, `60min`: Max **90 days** per chunk (Max total span: 730 days)
* `D` (Daily), `W` (Weekly): Max **180 days** per chunk (Max total span: 1825 days / 5 years)

**Safety Pre-Checks:**
* Rejects requests exceeding **15 chunks** before contacting the API to avoid `HTTP 429 Too Many Requests`.
* Rejects dates prior to Kotak's retention inception date (`2021-01-01`) or future dates.
* Requires only `CONSUMER_KEY` (no 2FA / TOTP needed); all chunks are fetched concurrently using a worker pool (`max_workers=5`).
* Automatically deduplicates timestamps and exports sorted candles to CSV in `historical_data_output/`.

## File Structure

- `main.py`: Main script for placing orders from CSV.
- `search.py`: Utility script for searching scrip details via NeoAPI.
- `scrip_master.py`: Tool for downloading and querying Scrip Master CSV files.
- `historical_data.py`: Tool for fetching, chunking, and exporting historical OHLCV data.
- `trades.csv`: Input file for trade instructions (user-created).
- `requirements.txt`: Python dependencies.
- `sample.env`: Template for environment variables.
- `README.md`: Project documentation.

## Troubleshooting

- **Missing Environment Variables**: If you see an error about missing environment variables, ensure you have created the `.env` file and it contains all the required keys (`NEO_FIN_KEY`, `CONSUMER_KEY`, etc.).
- **CSV Errors**: Ensure `trades.csv` exists and uses semicolons (`;`) as delimiters, not commas.
- **Authentication Failed**: Double-check your MPIN and ensure the TOTP you enter is current.
- **Dependencies**: If running `search.py` fails with module errors, make sure you ran `pip install -r requirements.txt`. Note that `neo-api-client` is installed from a git repository.

## Disclaimer
This software is for educational purposes only. Use it at your own risk. The authors are not responsible for any financial losses incurred.
