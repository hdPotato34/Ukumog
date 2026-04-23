from __future__ import annotations

import argparse
import json
import sys

from ukumog_engine.ports import handle_request
from ukumog_engine.ports.service import RequestError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read a Ukumog JSON request and emit a JSON response.")
    parser.add_argument(
        "--request",
        type=str,
        default=None,
        help="Optional inline JSON request. If omitted, stdin is read.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON response for manual debugging.",
    )
    return parser.parse_args(argv)


def _read_request_text(args: argparse.Namespace) -> str:
    if args.request is not None:
        return args.request
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw = _read_request_text(args).strip()
        if not raw:
            raise RequestError("request body is empty")
        payload = json.loads(raw)
        response = handle_request(payload)
        exit_code = 0
    except (RequestError, json.JSONDecodeError, ValueError) as exc:
        response = {"ok": False, "error": str(exc)}
        exit_code = 1

    json.dump(response, sys.stdout, indent=2 if args.pretty else None, sort_keys=True)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
