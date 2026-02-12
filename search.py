import os
import logging
import getpass
import argparse

from neo_api_client import NeoAPI
from neo_api_client.exceptions import ApiException

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

_LOGGER = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

def search_for_scrip(symbol, cred_details, totp):
    """
    Searches for a stock symbol in the NSE Cash Market using NeoAPI.
    """
    try:
        client = NeoAPI(environment='prod', access_token=None, neo_fin_key=cred_details['neo_fin_key'], consumer_key=cred_details['consumer_key'])
        if client:
            client.totp_login(mobile_number=cred_details['mobno'], ucc=cred_details['ucc'], totp=totp)
            client.totp_validate(mpin=cred_details['mpin'])

            # get scrip search details for particular exchange segment
            data = client.search_scrip(exchange_segment = "nse_cm", symbol = symbol,  expiry = "", option_type = "", strike_price = "")
            return data
    except Exception as e:
        print("Exception when calling scrip search api->scrip_search: %s\n" % e)
        return None

if __name__ == "__main__":
    require_env_vars(['NEO_FIN_KEY', 'CONSUMER_KEY', 'MOBILE_NO', 'UCC', 'MPIN'])

    cred_details = {
        'neo_fin_key': os.getenv('NEO_FIN_KEY'),
        'consumer_key': os.getenv('CONSUMER_KEY'),
        'ucc': os.getenv('UCC'),
        'mobno': os.getenv('MOBILE_NO'),
        'mpin': os.getenv('MPIN')
    }
    
    parser = argparse.ArgumentParser(description='Search for stock symbol')
    parser.add_argument('--symbol', required=True, help='Stock symbol to search')
    args = parser.parse_args()

    totp = getpass.getpass("Enter TOTP: ")

    data = search_for_scrip(args.symbol, cred_details, totp)
    if data:
        print(data)
