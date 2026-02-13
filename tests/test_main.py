import unittest
from unittest.mock import MagicMock, patch
import sys
import io
import os

# Add parent directory to path to import main
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import login_client, get_holdings, book_trade

class TestMain(unittest.TestCase):

    @patch('main.NeoAPI')
    def test_login_client(self, mock_neo_api):
        # Setup mock
        mock_client_instance = mock_neo_api.return_value
        cred_details = {
            'neo_fin_key': 'key',
            'consumer_key': 'consumer',
            'mobno': '1234567890',
            'ucc': 'ucc123',
            'mpin': '1234'
        }
        totp = '123456'

        # Execute
        client = login_client(totp, cred_details)

        # Verify
        mock_neo_api.assert_called_with(environment='prod', access_token=None, neo_fin_key='key', consumer_key='consumer')
        mock_client_instance.totp_login.assert_called_with(mobile_number='1234567890', ucc='ucc123', totp='123456')
        mock_client_instance.totp_validate.assert_called_with(mpin='1234')
        self.assertEqual(client, mock_client_instance)

    def test_get_holdings_success(self):
        # Setup mock client
        mock_client = MagicMock()
        mock_client.holdings.return_value = {
            'data': [
                {
                    'symbol': 'TATASTEEL',
                    'quantity': 10,
                    'averagePrice': 100.0,
                    'closingPrice': 105.0
                },
                {
                    'symbol': 'RELIANCE',
                    'quantity': 5,
                    'averagePrice': 2000.0,
                    'closingPrice': 2050.0
                }
            ]
        }

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        # Execute
        get_holdings(mock_client)

        # Restore stdout
        sys.stdout = sys.__stdout__

        # Verify output
        output = captured_output.getvalue()
        self.assertIn('TATASTEEL', output)
        self.assertIn('10', output)
        self.assertIn('100.00', output)
        self.assertIn('105.00', output)
        self.assertIn('RELIANCE', output)
        self.assertIn('5', output)
        self.assertIn('2000.00', output)
        self.assertIn('2050.00', output)

    def test_get_holdings_empty(self):
        # Setup mock client
        mock_client = MagicMock()
        mock_client.holdings.return_value = {'data': []}

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        # Execute
        get_holdings(mock_client)

        # Restore stdout
        sys.stdout = sys.__stdout__

        # Verify output
        output = captured_output.getvalue()
        self.assertIn("No holdings found.", output)

    def test_get_holdings_error(self):
        # Setup mock client
        mock_client = MagicMock()
        mock_client.holdings.side_effect = Exception("API Error")

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        # Execute
        get_holdings(mock_client)

        # Restore stdout
        sys.stdout = sys.__stdout__

        # Verify output
        output = captured_output.getvalue()
        self.assertIn("Error fetching holdings: API Error", output)

    @patch('main.login_client')
    def test_book_trade(self, mock_login_client):
        # Setup mock client
        mock_client = MagicMock()
        mock_login_client.return_value = mock_client

        cred_details = {'fake': 'creds'}
        totp = '123456'
        trade_details = {
            'stock_id': 'INFY',
            'txn_type': 'B',
            'qty': 10,
            'tracker_id': 'tracker-1',
            'order_type': 'L'
        }

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        # Execute
        book_trade(totp, cred_details, trade_details)

        # Restore stdout
        sys.stdout = sys.__stdout__

        # Verify
        mock_login_client.assert_called_with(totp, cred_details)
        mock_client.place_order.assert_called_once()
        args, kwargs = mock_client.place_order.call_args
        self.assertEqual(kwargs['trading_symbol'], 'INFY')
        self.assertEqual(kwargs['transaction_type'], 'B')
        self.assertEqual(kwargs['quantity'], 10)
        self.assertIn("Order placed for INFY", captured_output.getvalue())

if __name__ == '__main__':
    unittest.main()
