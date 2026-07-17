from __future__ import annotations

import csv
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_strategy import _valid_buy_fixture
from xauusd_scalper import NO_TRADE, Candle, load_trade_state
from xauusd_scalper.cli import build_parser, main


def _write_candles(path: Path, candles: list[Candle]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        for candle in candles:
            writer.writerow(
                [
                    candle.time.isoformat(),
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                ]
            )


class CliTests(unittest.TestCase):
    def test_state_path_is_mandatory(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--m5", "m5.csv", "--m15", "m15.csv", "--h1", "h1.csv"])

    def test_successful_signal_is_recorded_automatically_and_not_repeated(self) -> None:
        m5, m15, h1 = _valid_buy_fixture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.csv" for name in ("m5", "m15", "h1")}
            _write_candles(paths["m5"], m5)
            _write_candles(paths["m15"], m15)
            _write_candles(paths["h1"], h1)
            state_path = root / "state.json"
            argv = [
                "xauusd-scalper",
                "--m5",
                str(paths["m5"]),
                "--m15",
                str(paths["m15"]),
                "--h1",
                str(paths["h1"]),
                "--state",
                str(state_path),
            ]

            first_output = io.StringIO()
            with patch.object(sys, "argv", argv), redirect_stdout(first_output):
                self.assertEqual(0, main())

            state = load_trade_state(state_path)
            self.assertEqual(1, state.session_trade_counts["2026-07-03"]["New York"])
            self.assertIn("Market Bias: Bullish", first_output.getvalue())

            second_output = io.StringIO()
            with patch.object(sys, "argv", argv), redirect_stdout(second_output):
                self.assertEqual(0, main())

            self.assertEqual(f"{NO_TRADE}\n", second_output.getvalue())
            unchanged = load_trade_state(state_path)
            self.assertEqual(1, unchanged.session_trade_counts["2026-07-03"]["New York"])


if __name__ == "__main__":
    unittest.main()
