import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import io
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, date, timedelta

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

from historical_data import (
    INTERVAL_MAX_DAYS,
    MAX_ALLOWED_CHUNKS,
    MAX_TOTAL_SPAN_DAYS,
    RETENTION_INCEPTION_DATE,
    parse_date,
    validate_and_generate_chunks,
    resolve_neosymbol,
    HistoricalDataClient,
    save_candles_to_csv,
    login_client,
    main as cli_main,
)


class TestValidationAndChunking(unittest.TestCase):
    def test_single_chunk_within_limits(self):
        chunks = validate_and_generate_chunks("2025-01-01", "2025-01-20", "5min")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], ("2025-01-01", "2025-01-20"))

    def test_multi_chunk_exact_split(self):
        # 15min limit is 60 days
        chunks = validate_and_generate_chunks("2025-01-01", "2025-03-11", "15min")
        self.assertEqual(len(chunks), 2)
        # Chunk 1: Jan 1 to Mar 1 (60 days)
        self.assertEqual(chunks[0], ("2025-01-01", "2025-03-01"))
        # Chunk 2: Mar 2 to Mar 11 (10 days)
        self.assertEqual(chunks[1], ("2025-03-02", "2025-03-11"))

    def test_non_overlapping_contiguous_chunks(self):
        chunks = validate_and_generate_chunks("2024-01-01", "2024-03-31", "30min")  # 30min is 90d
        self.assertEqual(len(chunks), 2)
        chunk1_end = datetime.strptime(chunks[0][1], "%Y-%m-%d").date()
        chunk2_start = datetime.strptime(chunks[1][0], "%Y-%m-%d").date()
        self.assertEqual(chunk2_start - chunk1_end, timedelta(days=1))

    def test_from_date_greater_than_to_date_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_and_generate_chunks("2025-05-10", "2025-05-01", "15min")
        self.assertIn("cannot be later than to_date", str(ctx.exception))

    def test_future_date_rejected(self):
        future_date = (datetime.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
        with self.assertRaises(ValueError) as ctx:
            validate_and_generate_chunks("2025-01-01", future_date, "D")
        self.assertIn("cannot be in the future", str(ctx.exception))

    def test_date_prior_to_retention_limit_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_and_generate_chunks("2020-12-15", "2021-02-01", "D")
        self.assertIn("earlier than Kotak Neo's data retention limit", str(ctx.exception))

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_and_generate_chunks("2025-01-01", "2025-01-10", "2min")
        self.assertIn("Invalid interval '2min'", str(ctx.exception))

    def test_max_total_span_per_interval_rejected(self):
        # 1min has MAX_TOTAL_SPAN_DAYS of 180 days
        with self.assertRaises(ValueError) as ctx:
            validate_and_generate_chunks("2024-01-01", "2024-08-01", "1min")  # ~213 days
        self.assertIn("exceeds the maximum allowed span", str(ctx.exception))

    def test_max_allowed_chunks_rule(self):
        # Setting max_allowed_chunks to 2 to verify threshold enforcement
        with self.assertRaises(ValueError) as ctx:
            validate_and_generate_chunks("2025-01-01", "2025-04-10", "5min", max_allowed_chunks=2)
        self.assertIn("exceeds the maximum allowed safety threshold of 2 chunks", str(ctx.exception))


class TestSymbolResolution(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.nse_cm_csv = Path(self.test_dir) / "nse_cm.csv"
        # Create mock scrip master with BEL and NIFTY
        self.nse_cm_csv.write_text(
            "pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,lLotSize\n"
            "383,,nse_cm,,BEL,BEL-EQ,1\n"
            "26000,,nse_cm,,NIFTY,NIFTY,1\n"
            "11536,,nse_cm,,TCS,TCS-EQ,1\n"
        )
        self.nse_fo_csv = Path(self.test_dir) / "nse_fo.csv"
        self.nse_fo_csv.write_text(
            "pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,lLotSize\n"
            "99999,,nse_fo,,BEL,BEL26NOVFUT,250\n"
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_direct_neosymbol_passthrough(self):
        seg, token = resolve_neosymbol("nse_cm|26000", scrip_dir=self.test_dir)
        self.assertEqual(seg, "nse_cm")
        self.assertEqual(token, "26000")

    def test_direct_neosymbol_invalid_format(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_neosymbol("invalid_segment|1234", scrip_dir=self.test_dir)
        self.assertIn("Invalid neosymbol format", str(ctx.exception))

    def test_resolve_bel_by_symbol_name(self):
        # Passing base name 'BEL' matches pSymbolName 'BEL' and pTrdSymbol 'BEL-EQ'
        seg, token = resolve_neosymbol("BEL", segment="nse_cm", scrip_dir=self.test_dir)
        self.assertEqual(seg, "nse_cm")
        self.assertEqual(token, "383")

    def test_resolve_bel_with_eq_suffix(self):
        seg, token = resolve_neosymbol("BEL-EQ", segment="nse_cm", scrip_dir=self.test_dir)
        self.assertEqual(seg, "nse_cm")
        self.assertEqual(token, "383")

    def test_resolve_nifty_by_trd_symbol(self):
        seg, token = resolve_neosymbol("NIFTY", segment="nse_cm", scrip_dir=self.test_dir)
        self.assertEqual(seg, "nse_cm")
        self.assertEqual(token, "26000")

    def test_resolve_by_token(self):
        seg, token = resolve_neosymbol("11536", segment="nse_cm", scrip_dir=self.test_dir)
        self.assertEqual(seg, "nse_cm")
        self.assertEqual(token, "11536")

    def test_resolve_segment_scoping(self):
        # When querying for BEL in nse_fo, it should resolve to the F&O contract token
        seg, token = resolve_neosymbol("BEL", segment="nse_fo", scrip_dir=self.test_dir)
        self.assertEqual(seg, "nse_fo")
        self.assertEqual(token, "99999")

    def test_missing_scrip_dir_raises_filenotfound(self):
        non_existent = Path(self.test_dir) / "does_not_exist"
        with self.assertRaises(FileNotFoundError) as ctx:
            resolve_neosymbol("BEL", scrip_dir=non_existent)
        self.assertIn("Scrip master cache directory", str(ctx.exception))

    def test_unknown_symbol_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_neosymbol("UNKNOWN_SYMBOL", segment="nse_cm", scrip_dir=self.test_dir)
        self.assertIn("Could not resolve instrument token", str(ctx.exception))


class TestHistoricalDataClient(unittest.TestCase):
    def setUp(self):
        self.client = HistoricalDataClient(consumer_key="test-key")

    @patch("requests.get")
    def test_fetch_chunk_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "interval": "15min",
            "data": {
                "candles": [
                    ["2025-01-01T09:15:00+0530", 100.0, 105.0, 99.5, 104.0, 5000, 0],
                    ["2025-01-01T09:30:00+0530", 104.0, 106.0, 103.5, 105.5, 4500, 0],
                ]
            },
        }
        mock_get.return_value = mock_response

        candles = self.client.fetch_chunk("nse_cm|383", "2025-01-01", "2025-01-10", "15min")
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0][0], "2025-01-01T09:15:00+0530")
        self.assertEqual(candles[0][1], 100.0)

    @patch("requests.get")
    @patch("time.sleep")
    def test_fetch_chunk_rate_limit_retry(self, mock_sleep, mock_get):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.1"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "data": {"candles": [["2025-01-01T09:15:00+0530", 10, 20, 5, 15, 100, 0]]}
        }

        mock_get.side_effect = [resp_429, resp_200]

        candles = self.client.fetch_chunk("nse_cm|383", "2025-01-01", "2025-01-10", "15min")
        self.assertEqual(len(candles), 1)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(0.1)

    @patch.object(HistoricalDataClient, "fetch_chunk")
    def test_fetch_historical_data_concurrent_assembly_and_deduplication(self, mock_fetch_chunk):
        # Simulate chunks completing out of order with overlapping boundary timestamp
        chunk1_candles = [
            ["2025-01-01T09:15:00+0530", 100, 101, 99, 100.5, 1000, 0],
            ["2025-01-02T15:30:00+0530", 105, 106, 104, 105.0, 1200, 0],
        ]
        chunk2_candles = [
            ["2025-01-02T15:30:00+0530", 105, 106, 104, 105.0, 1200, 0],  # Duplicate boundary
            ["2025-01-03T09:15:00+0530", 106, 108, 105, 107.0, 1500, 0],
        ]

        def side_effect(neosymbol, start, end, interval):
            if start == "2025-01-01":
                return chunk1_candles
            return chunk2_candles

        mock_fetch_chunk.side_effect = side_effect

        chunks = [("2025-01-01", "2025-01-02"), ("2025-01-03", "2025-01-04")]
        results = self.client.fetch_historical_data("nse_cm|383", chunks, "15min")

        # Total 3 unique candles after deduplicating the boundary candle
        self.assertEqual(len(results), 3)
        # Verify strict ascending order
        self.assertEqual(results[0][0], "2025-01-01T09:15:00+0530")
        self.assertEqual(results[1][0], "2025-01-02T15:30:00+0530")
        self.assertEqual(results[2][0], "2025-01-03T09:15:00+0530")


class TestCSVExport(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_candles_to_csv_creates_dir_and_file(self):
        candles = [
            ["2025-01-01T09:15:00+0530", 100.0, 105.0, 99.0, 104.5, 12345, 0],
            ["2025-01-01T09:30:00+0530", 104.5, 107.0, 104.0, 106.0, 9876, 0],
        ]
        out_file = Path(self.test_dir) / "subdir" / "test_output.csv"
        saved_path = save_candles_to_csv(candles, out_file)

        self.assertEqual(saved_path, out_file)
        self.assertTrue(out_file.exists())

        lines = out_file.read_text().strip().split("\n")
        self.assertEqual(lines[0], "timestamp,open,high,low,close,volume,oi")
        self.assertIn("2025-01-01T09:15:00+0530,100.0,105.0,99.0,104.5,12345,0", lines[1])
        self.assertEqual(len(lines), 3)


class TestHistoricalDataCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.scrip_dir = Path(self.test_dir) / "scrip_master_data"
        self.scrip_dir.mkdir(parents=True, exist_ok=True)
        (self.scrip_dir / "nse_cm.csv").write_text(
            "pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,lLotSize\n"
            "383,,nse_cm,,BEL,BEL-EQ,1\n"
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cli_validation_failure_exits_before_auth(self):
        # from_date > to_date should exit with status 1
        test_args = [
            "historical_data.py",
            "--symbol", "BEL",
            "--from-date", "2025-02-01",
            "--to-date", "2025-01-01",
            "--interval", "15min",
        ]
        with patch("sys.argv", test_args):
            with patch("sys.stderr", new=io.StringIO()) as fake_err:
                with self.assertRaises(SystemExit) as ctx:
                    cli_main()
                self.assertEqual(ctx.exception.code, 1)
                self.assertIn("Validation Error", fake_err.getvalue())

    @patch("getpass.getpass", return_value="123456")
    @patch("historical_data.login_client")
    @patch.object(HistoricalDataClient, "fetch_historical_data")
    def test_cli_success_saves_csv_in_output_dir(self, mock_fetch, mock_login, mock_getpass):
        mock_login.return_value = MagicMock()
        mock_fetch.return_value = [
            ["2025-01-01T09:15:00+0530", 100, 105, 99, 104, 5000, 0]
        ]

        out_dir = Path(self.test_dir) / "custom_output"
        test_args = [
            "historical_data.py",
            "--symbol", "BEL",
            "--from-date", "2025-01-01",
            "--to-date", "2025-01-10",
            "--interval", "15min",
            "--scrip-dir", str(self.scrip_dir),
            "--output-dir", str(out_dir),
        ]

        with patch.dict(os.environ, {
            "CONSUMER_KEY": "ckey",
            "MOBILE_NO": "1234567890",
            "UCC": "ucc123",
            "MPIN": "1234",
        }):
            with patch("sys.argv", test_args):
                with patch("sys.stdout", new=io.StringIO()) as fake_out:
                    cli_main()
                    output = fake_out.getvalue()
                    self.assertIn("Resolved symbol 'BEL' -> neosymbol: nse_cm|383", output)
                    self.assertIn("Successfully saved 1 candle(s)", output)

        # Verify output file generated in out_dir
        generated_csvs = list(out_dir.glob("*.csv"))
        self.assertEqual(len(generated_csvs), 1)
        self.assertIn("BEL_nse_cm_15min", generated_csvs[0].name)


if __name__ == "__main__":
    unittest.main()
