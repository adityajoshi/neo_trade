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


if __name__ == "__main__":
    require_env_vars(['NEO_FIN_KEY', 'CONSUMER_KEY', 'MOBILE_NO', 'UCC', 'MPIN'])
    var_neo_fin_key = os.getenv('NEO_FIN_KEY')
    var_consumer_key = os.getenv('CONSUMER_KEY')
    var_ucc = os.getenv('UCC')
    var_mobno = os.getenv('MOBILE_NO')
    var_mpin = os.getenv('MPIN')
    
    parser = argparse.ArgumentParser(description='Search for stock symbol')
    parser.add_argument('--symbol', required=True, help='Stock symbol to search')
    args = parser.parse_args()
    var_symbol = args.symbol

    client = NeoAPI(environment='prod', access_token=None, neo_fin_key=var_neo_fin_key, consumer_key=var_consumer_key)
    totp = getpass.getpass("Enter TOTP: ")
    if client:
        client.totp_login(mobile_number=var_mobno, ucc=var_ucc, totp=totp)
        client.totp_validate(mpin=var_mpin)
        try:
            # get scrip search details for particular exchange segment
            data = client.search_scrip(exchange_segment = "nse_cm", symbol = var_symbol,  expiry = "", option_type = "", strike_price = "")
            print(data)
        except Exception as e:
            print("Exception when calling scrip search api->scrip_search: %s\n" % e)
