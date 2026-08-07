#!/usr/bin/env python3
"""Scripts/ai/redact.py

Robust, deterministic redaction — stdin to stdout. Deliberately in
Python, not sed: correct multi-line handling (PEM private-key blocks
span many lines) is fragile to express as a sed one-liner, and this is
exactly the kind of security-relevant text transform Heimei's own
Standards favor a small, testable stdlib-only script for over a clever
shell pipeline, the same rationale as policy.py/issue_sections.py.

Called via common.sh's ai_redact(), which every caller in this control
plane already pipes through BEFORE bounding/truncating and BEFORE
hashing a to-be-published excerpt or artifact — never after. Redacting
after truncation risks a secret being cut mid-pattern at the boundary,
leaving an unredacted fragment in the final output; redacting first
means the whole match is replaced before any boundary is applied.

No secret value is ever echoed back in a diagnostic message by this
script — on any internal error it fails closed (see main()) without
printing the input it failed on.
"""

from __future__ import annotations

import re
import sys

# --- Private key / cert blocks (multi-line; matched before anything
# else touches the text, so nothing downstream can see a partial key). ---
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN ((?:OPENSSH|RSA|EC) PRIVATE KEY|PRIVATE KEY)-----"
    r".*?"
    r"-----END \1-----",
    re.DOTALL,
)

# --- Authorization: Bearer <token> — case-insensitive on both the
# header name and the scheme name. ---
_AUTH_BEARER_RE = re.compile(
    r"(?i)\b(authorization\s*:\s*bearer\s+)\S+"
)

# --- AWS access-key IDs. AKIA... = long-term user keys, ASIA... =
# temporary/STS keys. Both are exactly 4 letters + 16 upper/digit
# chars = 20 chars total. Not just the one example literal. ---
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

# --- GitHub's own token literal formats (gh[pousr]_...). ---
_GH_TOKEN_LITERAL_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")

# --- Generic NAME=value / NAME: value credential-shaped assignments —
# covers GH_TOKEN, GITHUB_TOKEN, OPENAI_API_KEY, ANTHROPIC_API_KEY, and
# any other *_TOKEN/*_API_KEY/*_SECRET/*_PASSWORD-shaped name, plus the
# bare words token/secret/password/api_key on their own. Case-
# insensitive; value is everything up to the next whitespace. ---
_GENERIC_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API[-_]?KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)"
    r"([\s]*[:=][\s]*)"
    r"\S+"
)

# --- Local filesystem paths that would otherwise leak the operator's
# username/home layout into a published artifact. ---
_HOME_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+")


def redact(text: str) -> str:
    """Applies every pattern in a fixed order. PEM blocks first (multi-line,
    must be replaced whole before any single-line pattern could partially
    match inside one), then single-line credential patterns, then paths.
    """
    text = _PEM_BLOCK_RE.sub("[REDACTED-PRIVATE-KEY-BLOCK]", text)
    text = _AUTH_BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _AWS_ACCESS_KEY_RE.sub("[REDACTED-AWS-ACCESS-KEY]", text)
    text = _GH_TOKEN_LITERAL_RE.sub("[REDACTED-TOKEN]", text)
    text = _GENERIC_CREDENTIAL_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text
    )
    text = _HOME_PATH_RE.sub("/home/[REDACTED-USER]", text)
    return text


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        text = raw.decode("utf-8", errors="replace")
        sys.stdout.write(redact(text))
        sys.stdout.flush()
        return 0
    except Exception:
        # Fail closed WITHOUT echoing the input that caused the
        # failure — a redaction bug must never become a leak.
        sys.stderr.write("redact.py: internal error while redacting — refusing to emit unredacted or partial output.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
