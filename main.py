from neo_api_client import NeoAPI
import datetime
import csv
import argparse
import os
import getpass
import sys


try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def require_env_vars(names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


def read_stocks_from_csv(filename):
    """
    Reads a CSV file containing stock trading information.
    The CSV should have columns: stock_id;buy_or_sell;quantity
    Returns a list of dictionaries with the stock data.
    """
    stocks = []
    try:
        with open(filename, 'r') as file:
            reader = csv.reader(file, delimiter=';')
            for row in reader:
                if len(row) == 4:
                    stock_id, txn_type, qty, order_type = row
                    stocks.append({
                        'stock_id': stock_id,
                        'txn_type': txn_type,
                        'qty': int(qty),
                        'order_type': order_type
                    })
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
    except ValueError as e:
        print(f"Error parsing CSV: {e}")
    return stocks

def login_client(totp, cred_details):
    client = NeoAPI(environment='prod', access_token=None, neo_fin_key=cred_details['neo_fin_key'], consumer_key=cred_details['consumer_key'])
    if client:
        client.totp_login(mobile_number=cred_details['mobno'], ucc=cred_details['ucc'], totp=totp)
        client.totp_validate(mpin=cred_details['mpin'])
    return client

def get_holdings(client):
    try:
        response = client.holdings()
        if 'data' in response and response['data']:
            print(f"{'Symbol':<15} {'Qty':<10} {'Avg Price':<15} {'Closing Price':<15}")
            print("-" * 55)
            for holding in response['data']:
                symbol = holding.get('symbol', 'N/A')
                qty = holding.get('quantity', 0)
                avg_price = holding.get('averagePrice', 0.0)
                ltp = holding.get('closingPrice', 0.0)
                print(f"{symbol:<15} {qty:<10} {avg_price:<15.2f} {ltp:<15.2f}")
        else:
            print("No holdings found.")
    except Exception as e:
        print(f"Error fetching holdings: {e}")

def book_trade(client, cred_details, trade_details):
    try:
        stock_id = trade_details['stock_id']
        txn_type = trade_details['txn_type']
        qty = trade_details['qty']
        tracker_id = trade_details['tracker_id']
        ord_type = trade_details['order_type']


        client.place_order(
                exchange_segment="nse_cm",
                product="CNC",
                price="0",
                order_type=ord_type,
                quantity=qty,
                validity="DAY",
                trading_symbol=stock_id,
                transaction_type=txn_type,
                amo="NO",
                disclosed_quantity="0",
                market_protection="0",
                pf="N",
                trigger_price="0",
                tag=tracker_id,
                scrip_token=None,
                square_off_type=None,
                stop_loss_type=None,
                stop_loss_value=None,
                square_off_value=None,
                last_traded_price=None,
                trailing_stop_loss=None,
                trailing_sl_value=None,
                )
        print(f"Order placed for {stock_id}")
        return True
    except Exception as e:
        print(f"Error placing order for {stock_id}: {e}")
        return False

if __name__ == '__main__':
    try:
        # Parse arguments
        parser = argparse.ArgumentParser(description='Place orders from CSV using NeoAPI.')
        parser.add_argument('--csv', default='trades.csv', help='Path to the CSV file containing trades')
        parser.add_argument('--dry-run', action='store_true', help='Simulate trades without placing orders')
        parser.add_argument('--holdings', action='store_true', help="Display current holdings")
        args = parser.parse_args()

        if not args.dry_run:
            require_env_vars(['NEO_FIN_KEY', 'CONSUMER_KEY', 'MOBILE_NO', 'UCC', 'MPIN'])
        
        cred_details = {
            'neo_fin_key': os.getenv('NEO_FIN_KEY'),
            'consumer_key': os.getenv('CONSUMER_KEY'),
            'ucc': os.getenv('UCC'),
            'mobno': os.getenv('MOBILE_NO'),
            'mpin': os.getenv('MPIN')    
        }
        
        client = None
        if not args.dry_run:
            totp = getpass.getpass("Enter TOTP: ")
            client = login_client(totp, cred_details)
            if not client:
                print("Failed to authenticate. Exiting.")
                sys.exit(1)
            print("Authentication successful. Processing trades...")
        else:
            print("Running in DRY RUN mode. No orders will be placed.")
            # terminate script when dry run, mimic earlier behavior
            sys.exit(0)
        
        if args.holdings:
            get_holdings(client)
        else:
            success_count = 0
            fail_count = 0
            stocks = read_stocks_from_csv(args.csv)
            if not stocks:
                print("No stocks to trade or file not found/empty.")
                sys.exit(0)


            for stock in stocks:
                tracker_id = stock['stock_id'] + "-" + datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
                trade_details = {
                    'stock_id': stock['stock_id'],
                    'txn_type': stock['txn_type'],
                    'qty': stock['qty'],
                    'tracker_id': tracker_id,
                    'order_type': stock['order_type']
                }
                if book_trade(client, trade_details, dry_run=args.dry_run):
                    success_count += 1
                else:
                    fail_count += 1

        print(f"\nSummary: {success_count} successful, {fail_count} failed.")

    except Exception as e:
        print(f"Unexpected error: {e}")
