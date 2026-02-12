import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure the parent directory is in the path to import search
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from search import search_for_scrip

class TestSearchForScrip(unittest.TestCase):
    @patch('search.NeoAPI')
    def test_search_success(self, MockNeoAPI):
        mock_client = MockNeoAPI.return_value
        cred_details = {
            'neo_fin_key': 'key',
            'consumer_key': 'ckey',
            'mobno': '1234567890',
            'ucc': 'ucc123',
            'mpin': '1234'
        }
        totp = '123456'
        expected_data = [{'symbol': 'RELIANCE'}]
        mock_client.search_scrip.return_value = expected_data

        result = search_for_scrip('RELIANCE', cred_details, totp)

        self.assertEqual(result, expected_data)
        MockNeoAPI.assert_called_once_with(
            environment='prod',
            access_token=None,
            neo_fin_key='key',
            consumer_key='ckey'
        )
        mock_client.totp_login.assert_called_once_with(
            mobile_number='1234567890',
            ucc='ucc123',
            totp='123456'
        )
        mock_client.totp_validate.assert_called_once_with(mpin='1234')
        mock_client.search_scrip.assert_called_once_with(
            exchange_segment="nse_cm",
            symbol='RELIANCE',
            expiry="",
            option_type="",
            strike_price=""
        )

    @patch('search.NeoAPI')
    def test_search_failure(self, MockNeoAPI):
        mock_client = MockNeoAPI.return_value
        cred_details = {
            'neo_fin_key': 'key',
            'consumer_key': 'ckey',
            'mobno': '1234567890',
            'ucc': 'ucc123',
            'mpin': '1234'
        }
        totp = '123456'
        mock_client.search_scrip.side_effect = Exception("API Error")

        result = search_for_scrip('RELIANCE', cred_details, totp)

        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
