"""Read-only command-line entry point; Python standard library only."""

import argparse
import json
import sys
from pathlib import Path

from .core import DataError, analyze


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review fictional student follow-up records")
    parser.add_argument("--data", required=True, help="JSON input file")
    parser.add_argument("--start", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="inclusive YYYY-MM-DD")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.data).read_text(encoding="utf-8"))
        result = analyze(payload, args.start, args.end)
    except (DataError, OSError, ValueError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
