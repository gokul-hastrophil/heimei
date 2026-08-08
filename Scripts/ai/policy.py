#!/usr/bin/env python3
"""Scripts/ai/policy.py — read .ai/policy.toml and print it as JSON.

Trusted, read-only helper: `common.sh`'s `ai_policy_get()` shells out
to this instead of hand-rolling a TOML parser in Bash. Uses only the
Python 3.11+ standard library (`tomllib`) — no new dependency. Prints
the entire policy as one JSON document to stdout; callers use `jq` to
extract the field they need, so there is exactly one place that
understands TOML syntax.

Usage: policy.py <path-to-policy.toml>
Exit 1 with a message on stderr if the file is missing or invalid —
deliberately fails closed, never prints a partial/best-effort result.
"""

import json
import sys

try:
    import tomllib
except ImportError:  # pragma: no cover - guards against Python < 3.11
    print("policy.py requires Python 3.11+ (tomllib)", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: policy.py <path-to-policy.toml>", file=sys.stderr)
        return 1

    path = sys.argv[1]
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        print(f"policy file not found: {path}", file=sys.stderr)
        return 1
    except tomllib.TOMLDecodeError as exc:
        print(f"policy file is not valid TOML: {path}: {exc}", file=sys.stderr)
        return 1

    json.dump(data, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
