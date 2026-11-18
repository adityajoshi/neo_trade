import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import io
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure parent directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Provide mock for neo_api_client if not installed in current environment
try:
    import neo_api_client
    from neo_api_client.exceptions import ApiException
except ImportError:
    class ApiException(Exception):
        pass

    neo_mock = MagicMock()
    neo_exceptions_mock = MagicMock()
    neo_exceptions_mock.ApiException = ApiException
    sys.modules["neo_api_client"] = neo_mock
    sys.modules["neo_api_client.exceptions"] = neo_exceptions_mock

from scrip_master import (
    ScripMasterClient,
    require_env_vars,
    login_client,
    parse_expiry_date,
    extract_segment_from_url,
    IST_TIMEZONE,
    NSE_CDE_EPOCH_OFFSET,
    main as cli_main,
)


class TestScripMasterUtils(unittest.TestCase):
    def test_extract_segment_from_url(self):
        urls = {
            "https://lapi.kotaksecurities.com/.../transformed/cde_fo.csv": "cde_fo",
            "https://lapi.kotaksecurities.com/.../transformed/mcx_fo.csv": "mcx_fo",
            "https://lapi.kotaksecurities.com/.../transformed/nse_fo.csv": "nse_fo",
            "https://lapi.kotaksecurities.com/.../transformed/bse_fo.csv": "bse_fo",
            "https://lapi.kotaksecurities.com/.../transformed/nse_com.csv": "nse_com",
            "https://lapi.kotaksecurities.com/.../transformed-v1/bse_cm-v1.csv": "bse_cm",
            "https://lapi.kotaksecurities.com/.../transformed-v1/nse_cm-v1.csv": "nse_cm",
        }
        for url, expected in urls.items():
            self.assertEqual(extract_segment_from_url(url), expected)

    def test_parse_expiry_date_nse_fo_and_cde_fo(self):
        raw_epoch = 1700000000
        # For nse_fo and cde_fo, offset 315511200 must be added
        expected_epoch = raw_epoch + NSE_CDE_EPOCH_OFFSET
        expected_dt = datetime.fromtimestamp(expected_epoch, tz=timezone.utc).astimezone(IST_TIMEZONE)
        expected_str = expected_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        self.assertEqual(parse_expiry_date(raw_epoch, "nse_fo"), expected_str)
        self.assertEqual(parse_expiry_date(str(raw_epoch), "cde_fo"), expected_str)

    def test_parse_expiry_date_mcx_and_bse(self):
        raw_epoch = 1700000000
        # For mcx_fo and bse_fo, direct epoch conversion
        expected_dt = datetime.fromtimestamp(raw_epoch, tz=timezone.utc).astimezone(IST_TIMEZONE)
        expected_str = expected_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        self.assertEqual(parse_expiry_date(raw_epoch, "mcx_fo"), expected_str)
        self.assertEqual(parse_expiry_date(raw_epoch, "bse_fo"), expected_str)

    def test_parse_expiry_date_invalid_or_empty(self):
        self.assertIsNone(parse_expiry_date(None, "nse_fo"))
        self.assertIsNone(parse_expiry_date("", "nse_fo"))
        self.assertIsNone(parse_expiry_date("invalid_epoch", "nse_fo"))
        self.assertIsNone(parse_expiry_date(0, "nse_fo"))
        self.assertIsNone(parse_expiry_date(-100, "nse_fo"))


class TestRequireEnvVars(unittest.TestCase):
    def test_missing_env_vars_raises_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                require_env_vars(["CONSUMER_KEY", "MOBILE_NO"])
            self.assertIn("Missing required environment variables", str(ctx.exception))

    def test_all_env_vars_present(self):
        with patch.dict(os.environ, {"A": "1", "B": "2"}):
            require_env_vars(["A", "B"])


class TestLoginClient(unittest.TestCase):
    @patch("scrip_master.NeoAPI")
    def test_successful_login(self, MockNeoAPI):
        mock_client = MockNeoAPI.return_value
        cred_details = {
            "neo_fin_key": "fin_key",
            "consumer_key": "ckey",
            "mobno": "9999999999",
            "ucc": "ucc123",
            "mpin": "1234",
        }
        client = login_client("654321", cred_details)
        MockNeoAPI.assert_called_once_with(
            consumer_key="ckey",
            environment="prod",
            access_token=None,
            neo_fin_key="fin_key",
        )
        mock_client.totp_login.assert_called_once_with(
            mobile_number="9999999999", ucc="ucc123", totp="654321"
        )
        mock_client.totp_validate.assert_called_once_with(mpin="1234")
        self.assertEqual(client, mock_client)

    @patch("scrip_master.NeoAPI")
    def test_login_api_exception(self, MockNeoAPI):
        mock_client = MockNeoAPI.return_value
        mock_client.totp_login.side_effect = ApiException("Login failed")
        cred_details = {
            "consumer_key": "ckey",
            "mobno": "9999999999",
            "ucc": "ucc123",
            "mpin": "1234",
        }
        client = login_client("654321", cred_details)
        self.assertIsNone(client)


class TestScripMasterClient(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_neo_client = MagicMock()
        self.client = ScripMasterClient(
            client=self.mock_neo_client,
            cache_dir=self.test_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_missing_client_raises_error(self):
        client = ScripMasterClient(client=None)
        with self.assertRaises(RuntimeError) as ctx:
            client.get_master_file_paths()
        self.assertIn("Authentication required", str(ctx.exception))

    def test_get_master_file_paths_success_with_filespaths(self):
        self.mock_neo_client.scrip_master.return_value = {
            "filesPaths": [
                "https://lapi.kotaksecurities.com/v1/transformed-v1/nse_cm-v1.csv",
                "https://lapi.kotaksecurities.com/v1/transformed/nse_fo.csv",
            ],
            "baseFolder": "https://lapi.kotaksecurities.com/v1",
        }
        data = self.client.get_master_file_paths()
        self.mock_neo_client.scrip_master.assert_called_once()
        self.assertEqual(len(data["filesPaths"]), 2)
        self.assertEqual(data["baseFolder"], "https://lapi.kotaksecurities.com/v1")

    def test_get_master_file_paths_success_nested_data(self):
        self.mock_neo_client.scrip_master.return_value = {
            "data": {
                "filesPaths": [
                    "https://lapi.kotaksecurities.com/v1/transformed-v1/nse_cm-v1.csv",
                ],
                "baseFolder": "https://lapi.kotaksecurities.com/v1",
            }
        }
        data = self.client.get_master_file_paths()
        self.assertEqual(len(data["filesPaths"]), 1)

    def test_get_master_file_paths_exception(self):
        self.mock_neo_client.scrip_master.side_effect = Exception("Network timeout")
        with self.assertRaises(RuntimeError) as ctx:
            self.client.get_master_file_paths()
        self.assertIn("Failed to fetch scrip master file paths", str(ctx.exception))

    def test_get_master_file_paths_unexpected_format(self):
        self.mock_neo_client.scrip_master.return_value = {"status": "error"}
        with self.assertRaises(RuntimeError) as ctx:
            self.client.get_master_file_paths()
        self.assertIn("Unexpected response format", str(ctx.exception))

    @patch("requests.get")
    def test_download_file(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"pSymbol,pExchSeg\n", b"11536,nse_cm\n"]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        mock_get.return_value = mock_resp

        target_file = Path(self.test_dir) / "test_download.csv"
        saved_path = self.client.download_file("https://example.com/file.csv", target_file)

        self.assertEqual(saved_path, target_file)
        self.assertTrue(target_file.exists())
        content = target_file.read_bytes()
        self.assertEqual(content, b"pSymbol,pExchSeg\n11536,nse_cm\n")

    @patch.object(ScripMasterClient, "get_master_file_paths")
    @patch.object(ScripMasterClient, "download_file")
    def test_download_segments_all_when_optional_segment_omitted(self, mock_download_file, mock_paths):
        mock_paths.return_value = {
            "filesPaths": [
                "https://lapi.kotaksecurities.com/transformed-v1/nse_cm-v1.csv",
                "https://lapi.kotaksecurities.com/transformed/nse_fo.csv",
            ]
        }

        downloaded = self.client.download_segments(segments=None)

        self.assertEqual(len(downloaded), 2)
        self.assertIn("nse_cm", downloaded)
        self.assertIn("nse_fo", downloaded)
        self.assertEqual(mock_download_file.call_count, 2)

    @patch.object(ScripMasterClient, "get_master_file_paths")
    @patch.object(ScripMasterClient, "download_file")
    def test_download_segments_filtered_when_segment_provided(self, mock_download_file, mock_paths):
        mock_paths.return_value = {
            "filesPaths": [
                "https://lapi.kotaksecurities.com/transformed-v1/nse_cm-v1.csv",
                "https://lapi.kotaksecurities.com/transformed/nse_fo.csv",
                "https://lapi.kotaksecurities.com/transformed-v1/bse_cm-v1.csv",
            ]
        }

        # Segment as string
        downloaded = self.client.download_segments(segments="nse_cm")
        self.assertEqual(len(downloaded), 1)
        self.assertIn("nse_cm", downloaded)
        self.assertNotIn("nse_fo", downloaded)
        self.assertNotIn("bse_cm", downloaded)

        # Segment as list
        downloaded_list = self.client.download_segments(segments=["nse_fo", "bse_cm"])
        self.assertEqual(len(downloaded_list), 2)
        self.assertIn("nse_fo", downloaded_list)
        self.assertIn("bse_cm", downloaded_list)

    def test_search_scrip_across_all_and_filtered_segments(self):
        # Create mock CSV files
        nse_cm_csv = Path(self.test_dir) / "nse_cm.csv"
        nse_cm_csv.write_text(
            "pSymbol,pExchSeg,pTrdSymbol,lLotSize,lExpiryDate\n"
            "2885,nse_cm,RELIANCE-EQ,1,0\n"
            "11536,nse_cm,TCS-EQ,1,0\n"
        )

        nse_fo_csv = Path(self.test_dir) / "nse_fo.csv"
        nse_fo_csv.write_text(
            "pSymbol,pExchSeg,pTrdSymbol,lLotSize,lExpiryDate\n"
            "45678,nse_fo,RELIANCE26NOVFUT,250,1700000000\n"
            "45679,nse_fo,INFY26NOVFUT,400,1700000000\n"
        )

        # 1. Search all segments (segment=None)
        results = self.client.search_scrip("RELIANCE", segment=None)
        self.assertEqual(len(results), 2)
        symbols = [r["pTrdSymbol"] for r in results]
        self.assertIn("RELIANCE-EQ", symbols)
        self.assertIn("RELIANCE26NOVFUT", symbols)

        # Verify parsed expiry date populated
        fo_result = [r for r in results if r["pTrdSymbol"] == "RELIANCE26NOVFUT"][0]
        self.assertIsNotNone(fo_result["formattedExpiryDate"])
        self.assertIn("IST", fo_result["formattedExpiryDate"])

        # 2. Search filtered by segment
        results_cm_only = self.client.search_scrip("RELIANCE", segment="nse_cm")
        self.assertEqual(len(results_cm_only), 1)
        self.assertEqual(results_cm_only[0]["pTrdSymbol"], "RELIANCE-EQ")

        # 3. Search by token
        token_results = self.client.search_scrip("11536", search_by="token")
        self.assertEqual(len(token_results), 1)
        self.assertEqual(token_results[0]["pTrdSymbol"], "TCS-EQ")

        # 4. Search no match
        no_match = self.client.search_scrip("UNKNOWN")
        self.assertEqual(no_match, [])

    def test_search_scrip_missing_cache_dir(self):
        client = ScripMasterClient(cache_dir=Path(self.test_dir) / "non_existent")
        results = client.search_scrip("RELIANCE")
        self.assertEqual(results, [])


class TestScripMasterCLI(unittest.TestCase):
    @patch("getpass.getpass", return_value="123456")
    @patch("scrip_master.login_client")
    @patch("sys.argv", ["scrip_master.py", "--list-urls"])
    def test_cli_list_urls(self, mock_login, mock_getpass):
        mock_client = MagicMock()
        mock_client.scrip_master.return_value = {
            "filesPaths": ["https://example.com/nse_cm-v1.csv"],
            "baseFolder": "https://example.com",
        }
        mock_login.return_value = mock_client
        with patch.dict(os.environ, {
            "CONSUMER_KEY": "ckey",
            "MOBILE_NO": "1234567890",
            "UCC": "ucc123",
            "MPIN": "1234",
        }):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                cli_main()
                output = fake_out.getvalue()
                self.assertIn("Base Folder:", output)
                self.assertIn("https://example.com/nse_cm-v1.csv", output)

    @patch("getpass.getpass", return_value="123456")
    @patch("scrip_master.login_client")
    @patch("sys.argv", ["scrip_master.py", "--download"])
    @patch.object(ScripMasterClient, "download_segments")
    def test_cli_download_all_segments(self, mock_download, mock_login, mock_getpass):
        mock_login.return_value = MagicMock()
        mock_download.return_value = {"nse_cm": Path("scrip_master_data/nse_cm.csv")}
        with patch.dict(os.environ, {
            "CONSUMER_KEY": "ckey",
            "MOBILE_NO": "1234567890",
            "UCC": "ucc123",
            "MPIN": "1234",
        }):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                cli_main()
                output = fake_out.getvalue()
                self.assertIn("Successfully downloaded 1 segment file(s)", output)
                mock_download.assert_called_once_with(segments=None, output_dir="scrip_master_data")

    @patch("getpass.getpass", return_value="123456")
    @patch("scrip_master.login_client", return_value=None)
    @patch("sys.argv", ["scrip_master.py", "--download"])
    def test_cli_login_failure_exits(self, mock_login, mock_getpass):
        with patch.dict(os.environ, {
            "CONSUMER_KEY": "ckey",
            "MOBILE_NO": "1234567890",
            "UCC": "ucc123",
            "MPIN": "1234",
        }):
            with self.assertRaises(SystemExit) as ctx:
                cli_main()
            self.assertEqual(ctx.exception.code, 1)

    @patch("sys.argv", ["scrip_master.py", "--search", "RELIANCE"])
    @patch.object(ScripMasterClient, "search_scrip")
    def test_cli_search_no_auth_required(self, mock_search):
        mock_search.return_value = [
            {
                "pSymbol": "2885",
                "pExchSeg": "nse_cm",
                "pTrdSymbol": "RELIANCE-EQ",
                "lLotSize": "1",
                "formattedExpiryDate": "N/A",
            }
        ]
        # Environment is empty, verifying no auth is triggered
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                cli_main()
                output = fake_out.getvalue()
                self.assertIn("Found 1 matching instrument(s)", output)
                self.assertIn("RELIANCE-EQ", output)


if __name__ == "__main__":
    unittest.main()
