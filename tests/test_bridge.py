from __future__ import annotations

import contextlib
import io
import json
import unittest

from ukumog_engine.apps import json_bridge
from ukumog_engine.ports import handle_request


class BridgeContractTests(unittest.TestCase):
    def test_engine_info_request_reports_supported_commands(self) -> None:
        response = handle_request({"command": "engine_info"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["name"], "ukumog-engine")
        self.assertIn("analyze", response["supported_commands"])
        self.assertEqual(response["board_size"], 11)

    def test_analyze_request_accepts_rows_and_returns_best_move_payload(self) -> None:
        response = handle_request(
            {
                "command": "analyze",
                "position": {
                    "rows": [
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                        "B.B.B.B....",
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                    ],
                    "side_to_move": "black",
                },
                "engine": {
                    "depth": 2,
                    "time_ms": 0,
                    "analyze_root": True,
                },
            }
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["command"], "analyze")
        self.assertEqual(response["analysis"]["best_move"], {"index": 63, "row": 5, "col": 8})
        self.assertEqual(response["analysis"]["depth"], 2)
        self.assertTrue(response["tactics"]["winning_moves"])

    def test_play_move_request_returns_next_position_and_terminal_result(self) -> None:
        response = handle_request(
            {
                "command": "play_move",
                "position": {
                    "rows": [
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                        "B.B.B.B....",
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                        "...........",
                    ],
                    "side_to_move": "black",
                },
                "move": {"row": 5, "col": 8},
            }
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"], "win")
        self.assertEqual(response["position_after"]["side_to_move"], "white")

    def test_json_bridge_emits_machine_readable_error_payload(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = json_bridge.main(["--request", '{"command":"play_move"}'])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("position", payload["error"])


if __name__ == "__main__":
    unittest.main()
