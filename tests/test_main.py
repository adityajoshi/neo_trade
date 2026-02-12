import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os

# Ensure the parent directory is in the path to import main
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import read_stocks_from_csv, get_authenticated_client, book_trade

class TestReadStocksFromCSV(unittest.TestCase):
    def test_read_valid_csv(self):
        csv_content = "PAGEIND-EQ;B;1;MKT\nPGHH-EQ;S;2;L"
        with patch("builtins.open", mock_open(read_data=csv_content)):
            stocks = read_stocks_from_csv("trades.csv")
            self.assertEqual(len(stocks), 2)
            self.assertEqual(stocks[0]['stock_id'], 'PAGEIND-EQ')
            self.assertEqual(stocks[0]['txn_type'], 'B')
            self.assertEqual(stocks[0]['qty'], 1)
            self.assertEqual(stocks[0]['order_type'], 'MKT')
            self.assertEqual(stocks[1]['stock_id'], 'PGHH-EQ')
            self.assertEqual(stocks[1]['txn_type'], 'S')
            self.assertEqual(stocks[1]['qty'], 2)
            self.assertEqual(stocks[1]['order_type'], 'L')

    def test_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            stocks = read_stocks_from_csv("non_existent.csv")
            self.assertEqual(stocks, [])

    def test_invalid_data(self):
        csv_content = "INVALID_ROW"
        with patch("builtins.open", mock_open(read_data=csv_content)):
            stocks = read_stocks_from_csv("invalid.csv")
            self.assertEqual(stocks, [])

class TestGetAuthenticatedClient(unittest.TestCase):
    @patch('main.NeoAPI')
    def test_successful_login(self, MockNeoAPI):
        mock_client_instance = MockNeoAPI.return_value
        cred_details = {
            'neo_fin_key': 'key',
            'consumer_key': 'ckey',
            'mobno': '1234567890',
            'ucc': 'ucc123',
            'mpin': '1234'
        }
        totp = '123456'

        client = get_authenticated_client(cred_details, totp)

        MockNeoAPI.assert_called_once_with(
            environment='prod',
            access_token=None,
            neo_fin_key='key',
            consumer_key='ckey'
        )
        mock_client_instance.totp_login.assert_called_once_with(
            mobile_number='1234567890',
            ucc='ucc123',
            totp='123456'
        )
        mock_client_instance.totp_validate.assert_called_once_with(mpin='1234')
        self.assertEqual(client, mock_client_instance)

    @patch('main.NeoAPI')
    def test_init_exception(self, MockNeoAPI):
        MockNeoAPI.side_effect = Exception("Init failed")
        cred_details = {
            'neo_fin_key': 'key',
            'consumer_key': 'ckey',
            'mobno': '1234567890',
            'ucc': 'ucc123',
            'mpin': '1234'
        }
        client = get_authenticated_client(cred_details, '123456')
        self.assertIsNone(client)

class TestBookTrade(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.trade_details = {
            'stock_id': 'STOCK1',
            'txn_type': 'B',
            'qty': 10,
            'tracker_id': 'tracker1',
            'order_type': 'MKT'
        }

    def test_dry_run(self):
        # Should not call place_order
        result = book_trade(self.client, self.trade_details, dry_run=True)
        self.assertTrue(result)
        self.client.place_order.assert_not_called()

    def test_successful_trade(self):
        result = book_trade(self.client, self.trade_details, dry_run=False)
        self.assertTrue(result)
        self.client.place_order.assert_called_once_with(
            exchange_segment="nse_cm",
            product="CNC",
            price="0",
            order_type="MKT",
            quantity=10,
            validity="DAY",
            trading_symbol="STOCK1",
            transaction_type="B",
            amo="NO",
            disclosed_quantity="0",
            market_protection="0",
            pf="N",
            trigger_price="0",
            tag="tracker1",
            scrip_token=None,
            square_off_type=None,
            stop_loss_type=None,
            stop_loss_value=None,
            square_off_value=None,
            last_traded_price=None,
            trailing_stop_loss=None,
            trailing_sl_value=None,
        )

    def test_failed_trade(self):
        self.client.place_order.side_effect = Exception("Order failed")
        result = book_trade(self.client, self.trade_details, dry_run=False)
        self.assertFalse(result)
        self.client.place_order.assert_called_once()

if __name__ == '__main__':
    unittest.main()
