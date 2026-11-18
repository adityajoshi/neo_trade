import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import io
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure parent directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scrip_master import (
    ScripMasterClient,
    parse_expiry_date,
    extract_segment_from_url,
    IST_TIMEZONE,
    NSE_CDE_EPOCH_OFFSET,
    DEFAULT_BASE_URL,
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


class TestScripMasterClient(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.client = ScripMasterClient(
            api_token="test-token-123",
            base_url="https://api.testkotak.com",
            cache_dir=self.test_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_missing_token_raises_error(self):
        with patch.dict(os.environ, {}, clear=True):
            client = ScripMasterClient(api_token=None)
            with self.assertRaises(RuntimeError) as ctx:
                client.get_master_file_paths()
            self.assertIn("Missing API token", str(ctx.exception))

    @patch("requests.get")
    def test_get_master_file_paths_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "filesPaths": [
                    "https://lapi.kotaksecurities.com/v1/transformed-v1/nse_cm-v1.csv",
                    "https://lapi.kotaksecurities.com/v1/transformed/nse_fo.csv",
                ],
                "baseFolder": "https://lapi.kotaksecurities.com/v1",
            }
        }
        mock_get.return_value = mock_response

        data = self.client.get_master_file_paths()

        mock_get.assert_called_once_with(
            "https://api.testkotak.com/script-details/1.0/masterscrip/file-paths",
            headers={"Authorization": "test-token-123", "Accept": "application/json"},
            timeout=30,
        )
        self.assertEqual(len(data["filesPaths"]), 2)
        self.assertEqual(data["baseFolder"], "https://lapi.kotaksecurities.com/v1")

    @patch("requests.get")
    def test_get_master_file_paths_http_errors(self, mock_get):
        error_cases = [
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (429, "Too many requests"),
            (500, "Server error"),
        ]
        for status_code, expected_msg in error_cases:
            mock_resp = MagicMock()
            mock_resp.status_code = status_code
            mock_get.return_value = mock_resp
            with self.assertRaises(RuntimeError) as ctx:
                self.client.get_master_file_paths()
            self.assertIn(expected_msg, str(ctx.exception))

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
    @patch("sys.argv", ["scrip_master.py", "--list-urls", "--token", "tok123"])
    @patch.object(ScripMasterClient, "get_master_file_paths")
    def test_cli_list_urls(self, mock_paths):
        mock_paths.return_value = {
            "filesPaths": ["https://example.com/nse_cm-v1.csv"],
            "baseFolder": "https://example.com",
        }
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            cli_main()
            output = fake_out.getvalue()
            self.assertIn("Base Folder:", output)
            self.assertIn("https://example.com/nse_cm-v1.csv", output)

    @patch("sys.argv", ["scrip_master.py", "--download", "--token", "tok123"])
    @patch.object(ScripMasterClient, "download_segments")
    def test_cli_download_all_segments(self, mock_download):
        mock_download.return_value = {"nse_cm": Path("scrip_master_data/nse_cm.csv")}
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            cli_main()
            output = fake_out.getvalue()
            self.assertIn("Successfully downloaded 1 segment file(s)", output)
            mock_download.assert_called_once_with(segments=None, output_dir="scrip_master_data")

    @patch("sys.argv", ["scrip_master.py", "--search", "RELIANCE"])
    @patch.object(ScripMasterClient, "search_scrip")
    def test_cli_search(self, mock_search):
        mock_search.return_value = [
            {
                "pSymbol": "2885",
                "pExchSeg": "nse_cm",
                "pTrdSymbol": "RELIANCE-EQ",
                "lLotSize": "1",
                "formattedExpiryDate": "N/A",
            }
        ]
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            cli_main()
            output = fake_out.getvalue()
            self.assertIn("Found 1 matching instrument(s)", output)
            self.assertIn("RELIANCE-EQ", output)


if __name__ == "__main__":
    unittest.main()
