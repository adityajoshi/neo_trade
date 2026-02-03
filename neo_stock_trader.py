from neo_api_client import NeoAPI
import datetime
import csv
import argparse

def read_stocks_from_csv(filename):
    """
    Reads a CSV file containing stock trading information.
    The CSV should have columns: stock_id;buy_or_sell;quantity
    Returns a list of dictionaries with the stock data.
    """
    stocks = []
    with open(filename, 'r') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            if len(row) == 3:
                stock_id, txn_type, qty = row
                stocks.append({
                    'stock_id': stock_id,
                    'txn_type': txn_type,
                    'qty': int(qty)
                })
    return stocks

def book_trade(totp, stock_id, txn_type, qty, tracker_id):
    client = NeoAPI(environment='prod', access_token=None, neo_fin_key='neotradeapi', consumer_key='place_holder1')
    if client:
        client.totp_login(mobile_number="place_holder_2", ucc="place_holder3", totp=user_input)
        client.totp_validate(mpin="place_holder4")

    client.place_order(
            exchange_segment="nse_cm",
            product="CNC",
            price="0",
            order_type="MKT",
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process stock trades with TOTP login.')
    parser.add_argument('--totp', required=True, help='TOTP code for authentication')
    args = parser.parse_args()
    
    totp = args.totp

    stocks = read_stocks_from_csv('trades.csv')
    for stock in stocks:
        stock_id, txn_type, qty, tracker_id = stock['stock_id'], stock['txn_type'], stock['qty'], stock['stock_id']+"-"+datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')

        book_trade(args.totp, stock_id, txn_type, tracker_id)