#!/usr/bin/env python3
"""Scripts/ai/issue_sections.py — parse a GitHub issue-form body.

Reads a rendered issue-form body from stdin (the shape GitHub renders
each field as: "### <Label>\n\n<answer>\n\n") and prints
{"<Label>": "<answer>"} as JSON on stdout.

Trusted, read-only text parsing only: this never executes, evaluates,
or shell-interpolates anything from the issue body — it is pattern-
matched with a plain regex and the result is only ever consumed
through `jq`. Standard-library only (`re`, `json`) — no new
dependency.
"""

import json
import re
import sys

_HEADER_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def parse(text: str) -> dict:
    matches = list(_HEADER_RE.finditer(text))
    sections = {}
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections[header] = content
    return sections


def main() -> int:
    text = sys.stdin.read()
    json.dump(parse(text), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
