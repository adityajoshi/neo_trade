# neo_trade

A Python script to automate stock trading using the NeoAPI client. It reads trade instructions from a CSV file, authenticates with TOTP, and places orders.

## Overview
- **Main file**: `main.py` — Reads trades from a CSV, authenticates with TOTP, and places orders using the NeoAPI client.
- **CSV format**: Semicolon-separated columns: `stock_id;txn_type;quantity;order_type` (e.g., `PAGEIND-EQ;B;1;MKT`).
- **Notes**: `quantity` must be an integer. `order_type` (for example `MKT`) determines the order execution type. The script generates a `tracker_id` for each trade (stock_id + timestamp).
- **Authentication**: Uses TOTP (entered interactively when running `main.py`) and validates with MPIN.

## Requirements
- Python 3.x
- Dependencies listed in `requirements.txt`

Install dependencies:
```bash
pip install -r requirements.txt
```

## Setup
1. Copy `sample.env` to `.env` and fill in your credentials:
   ```bash
   cp sample.env .env
   # Edit .env with real values
   ```

2. Required environment variables (in `.env`):
   ```
   NEO_FIN_KEY=your_neo_fin_key
   CONSUMER_KEY=your_consumer_key
   MOBILE_NO=your_mobile_number
   UCC=your_ucc
   MPIN=your_mpin
   ```

3. Prepare a CSV file named `trades.csv` in the same directory with semicolon-separated rows matching the format: `stock_id;txn_type;quantity;order_type`.

   Example:
   ```
   PAGEIND-EQ;B;1;MKT
   PGHH-EQ;B;1;MKT
   ```

## Run
```bash
python main.py
```
Enter your TOTP when prompted. The script will process the CSV and place orders.

## Files
- `main.py` — Main script
- `requirements.txt` — Python dependencies
- `sample.env` — Template for environment variables
- `README.md` — This file
- `.gitignore` — Ignores `.env`, `__pycache__`, etc.

## Notes
- Ensure `.env` is not committed (added to `.gitignore`).
- The script handles exceptions and prints errors for robustness.
- For public sharing, use `sample.env` and avoid committing secrets.
