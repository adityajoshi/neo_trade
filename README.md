# Neo Trade

A Python project to automate stock trading using the NeoAPI client (Kotak Neo). It includes scripts to place orders from a CSV file and to search for stock scrips.

## Features
- **Automated Trading**: Reads trade instructions from a CSV file and places orders.
- **Scrip Search**: Utility to search for stock symbols and get details.
- **Secure Authentication**: Uses environment variables for credentials and interactive TOTP for login.

## Prerequisites
- Python 3.x
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

This script reads trade instructions from `trades.csv`, authenticates, and places orders.

1. Create a `trades.csv` file in the project root. The format is **semicolon-separated** with the following columns:
   `stock_id;txn_type;quantity;order_type`

   **Example `trades.csv`**:
   ```csv
   PAGEIND-EQ;B;1;MKT
   PGHH-EQ;B;1;MKT
   ```
   - `stock_id`: Trading symbol (e.g., `PAGEIND-EQ`)
   - `txn_type`: Transaction type (`B` for Buy, `S` for Sell)
   - `quantity`: Number of shares (integer)
   - `order_type`: Order type (e.g., `MKT`, `L` for Limit)

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

## File Structure

- `main.py`: Main script for placing orders from CSV.
- `search.py`: Utility script for searching scrip details.
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
