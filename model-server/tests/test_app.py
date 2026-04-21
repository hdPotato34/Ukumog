from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SERVING_DIR = ROOT / "model-server" / "src" / "serving"
UKUMOG_DIR = ROOT / "ukumog-engine"

for path in (str(SERVING_DIR), str(UKUMOG_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import app as app_module


def empty_board() -> list[list[None]]:
    return [[None for _ in range(11)] for _ in range(11)]


def valid_payload() -> dict[str, object]:
    return {
        "state": {
            "board": empty_board(),
            "turn": "B",
            "result": None,
        },
        "config": {
            "boardSize": 11,
        },
        "timeBudgetMs": 100,
        "maxDepth": 1,
    }


class UkumogAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app_module.app, raise_server_exceptions=False)

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["backend"], "ukumog")
        self.assertTrue(payload["engineVersion"])
        self.assertTrue(payload["pythonVersion"])

    def test_search_returns_standardized_payload(self) -> None:
        response = self.client.post("/search", json=valid_payload())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["backend"], "ukumog")
        self.assertEqual(payload["bestMove"]["row"], 5)
        self.assertEqual(payload["bestMove"]["col"], 5)
        self.assertEqual(payload["bestMove"]["notation"], "F6")

    def test_analyze_returns_standardized_payload(self) -> None:
        response = self.client.post("/analyze", json=valid_payload())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["backend"], "ukumog")
        self.assertIn("pv", payload)
        self.assertIn("nodes", payload)
        self.assertIn("timeMs", payload)

    def test_invalid_schema_returns_invalid_request(self) -> None:
        payload = valid_payload()
        payload["maxDepth"] = 0
        response = self.client.post("/search", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {
            "type": "error",
            "code": "invalid_request",
            "message": "Request body validation failed.",
        })

    def test_unsupported_board_size_returns_specific_error(self) -> None:
        payload = valid_payload()
        payload["config"]["boardSize"] = 9
        response = self.client.post("/search", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "unsupported_board_size")

    def test_internal_error_is_wrapped(self) -> None:
        with patch.object(app_module, "run_engine_analysis", side_effect=RuntimeError("boom")):
            response = self.client.post("/search", json=valid_payload())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {
            "type": "error",
            "code": "internal_error",
            "message": "The engine service hit an internal error.",
        })


if __name__ == "__main__":
    unittest.main()
