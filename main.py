from neo_api_client import NeoAPI
import datetime
import csv
import argparse
import os
import getpass


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

def book_trade(totp, cred_details, trade_details):
    try:
        stock_id = trade_details['stock_id']
        txn_type = trade_details['txn_type']
        qty = trade_details['qty']
        tracker_id = trade_details['tracker_id']
        ord_type = trade_details['order_type']
        
        client = NeoAPI(environment='prod', access_token=None, neo_fin_key=cred_details['neo_fin_key'], consumer_key=cred_details['consumer_key'])
        if client:
            client.totp_login(mobile_number=cred_details['mobno'], ucc=cred_details['ucc'], totp=totp)
            client.totp_validate(mpin=cred_details['mpin'])

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
    except Exception as e:
        print(f"Error placing order for {stock_id}: {e}")

if __name__ == '__main__':
    try:
        require_env_vars(['NEO_FIN_KEY', 'CONSUMER_KEY', 'MOBILE_NO', 'UCC', 'MPIN'])
        
        cred_details = {
            'neo_fin_key': os.getenv('NEO_FIN_KEY'),
            'consumer_key': os.getenv('CONSUMER_KEY'),
            'ucc': os.getenv('UCC'),
            'mobno': os.getenv('MOBILE_NO'),
            'mpin': os.getenv('MPIN')    
        }
        
        totp = getpass.getpass("Enter TOTP: ")
        
        stocks = read_stocks_from_csv('trades.csv')
        for stock in stocks:
            tracker_id = stock['stock_id'] + "-" + datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            trade_details = {
                'stock_id': stock['stock_id'],
                'txn_type': stock['txn_type'],
                'qty': stock['qty'],
                'tracker_id': tracker_id,
                'order_type': stock['order_type']
            }
            book_trade(totp, cred_details, trade_details)
    except Exception as e:
        print(f"Unexpected error: {e}")