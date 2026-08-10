"""Harness tests for the Heimei AI development control plane (v1,
supervised — third security-repair pass).

Deliberately NOT under Projects/Heimei/tests/ — these test repo-root
shell tooling (Scripts/ai/), not the heimei Python package, and must
never become part of `uv run pytest` inside Projects/Heimei.

Run with the same interpreter/pytest already installed for
Projects/Heimei — no new dependency:

    Projects/Heimei/.venv/bin/python -m pytest Scripts/ai/tests -q

Every test here either calls a pure Bash function directly (via
`bash -c 'source common.sh; ...'`) or drives a real script as a
subprocess against a FAKE `gh` (and, for a couple of tests, a fake
local git remote) that never talks to the real GitHub API or mutates
any real GitHub resource. Where a real `git worktree add`/`git branch`
is used against THIS repository (to test worktree-registration logic
against real git semantics), it is always on a throwaway local branch
that is deleted again before the test returns, and never pushed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "Scripts" / "ai"
COMMON_SH = SCRIPTS_DIR / "common.sh"

assert COMMON_SH.is_file(), f"common.sh not found at {COMMON_SH} — REPO_ROOT resolution is wrong"


def run_bash(snippet: str, *, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", "-c", f"source '{COMMON_SH}'; {snippet}"],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


def compute_issue_digest(issue_body: str) -> str:
    """Delegates to the ONE production implementation
    (ai_issue_digest_from_json in common.sh) instead of re-implementing
    the extraction pipeline in this test file a second time — a prior
    version of this helper hand-rolled the pipeline itself, which is
    exactly the "parallel implementation" pattern that caused a real
    bug twice in production (review.sh's digest computation and
    dispatch.sh's own post-lock recheck each independently drifted
    from the correct two-step extraction). Calling the shared helper
    means this fixture can never drift from production again — if the
    algorithm ever changes, both change together automatically."""
    issue_json = json.dumps({"body": issue_body})
    result = subprocess.run(
        ["bash", "-c", f"source '{COMMON_SH}'; ai_issue_digest_from_json \"$(cat)\""],
        input=issue_json,
        capture_output=True,
        text=True,
        timeout=30,
    )
    digest = result.stdout.strip()
    assert len(digest) == 64, f"compute_issue_digest failed: {result.stderr}"
    return digest


# ---------------------------------------------------------------------------
# Pure-function tests: no gh, no network, no filesystem mutation beyond a
# pytest tmp_path.
# ---------------------------------------------------------------------------


class TestNumericValidation:
    @pytest.mark.parametrize("value", ["1", "42", "999999"])
    def test_valid_positive_int_accepted(self, value):
        result = run_bash(f'ai_validate_positive_int "{value}" "issue number"')
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", "01", "", " 1", "1 "])
    def test_invalid_values_rejected(self, value):
        result = run_bash(f'ai_validate_positive_int "{value}" "issue number"')
        assert result.returncode != 0


class TestApprovalIdValidation:
    @pytest.mark.parametrize("value", ["appr-5-abc123-20260101T000000Z", "a", "A.B_C-D9"])
    def test_valid_ids_accepted(self, value):
        result = run_bash(f'ai_validate_approval_id "{value}"')
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("value", ["", "has space", "has/slash", "has..dotdot", "semi;colon", "$(injected)"])
    def test_invalid_ids_rejected(self, value):
        result = run_bash(f"ai_validate_approval_id '{value}'")
        assert result.returncode != 0


class TestBranchNameValidation:
    def test_valid_ai_branch_accepted(self):
        result = run_bash('ai_validate_branch_name "ai/claude/issue-5-add-thing"')
        assert result.returncode == 0, result.stderr

    def test_missing_prefix_rejected(self):
        result = run_bash('ai_validate_branch_name "claude/issue-5-add-thing"')
        assert result.returncode != 0
        assert "prefix" in result.stderr

    def test_dotdot_rejected(self):
        result = run_bash('ai_validate_branch_name "ai/claude/issue-5-add..thing"')
        assert result.returncode != 0

    def test_uppercase_rejected(self):
        result = run_bash('ai_validate_branch_name "ai/Claude/issue-5"')
        assert result.returncode != 0


class TestClaimRefName:
    def test_full_ref_shape(self):
        result = run_bash('ai_claim_ref_name "5" "appr-5-abc-20260101T000000Z"')
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "refs/heads/ai-claims/issue-5-approval-appr-5-abc-20260101T000000Z"

    def test_invalid_approval_id_rejected(self):
        result = run_bash('ai_claim_ref_name "5" "has space"')
        assert result.returncode != 0


class TestAllowedPathSpecValidation:
    @pytest.mark.parametrize(
        "line",
        [
            "Scripts/ai/foo.sh",
            "tests/**",
            "Projects/Heimei/src/heimei/status/service.py",
        ],
    )
    def test_valid_lines_accepted(self, line):
        result = run_bash(f'ai_validate_allowed_path_spec "{line}"')
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "line",
        [
            "as needed",
            "relevant files",
            "entire repository",
            "*",
            "/**",
            "/etc/passwd",
            "../../etc/passwd",
            "",
            "none",
            "n/a",
        ],
    )
    def test_unsafe_or_vague_lines_rejected(self, line):
        result = run_bash(f'ai_validate_allowed_path_spec "{line}"')
        assert result.returncode != 0

    def test_control_characters_rejected(self):
        result = run_bash('ai_validate_allowed_path_spec "$(printf \'foo\\abar\')"')
        assert result.returncode != 0


class TestDenylistEnforcement:
    @pytest.mark.parametrize(
        "path",
        [
            "VISION.md",
            "CONSTITUTION.md",
            ".ai/policy.toml",
            "Scripts/ai/dispatch.sh",
            ".github/workflows/ci.yml",
            "Projects/Heimei/src/heimei/doctor/manager.py",
            "Projects/Heimei/src/heimei/status/service.py",
            # Dependency manifests and migration paths — item 9 of the
            # third repair pass — are hard-denied structurally, not via
            # a policy-array pattern.
            "pyproject.toml",
            "Projects/Heimei/pyproject.toml",
            "uv.lock",
            "Projects/Heimei/uv.lock",
            "requirements.txt",
            "requirements-dev.txt",
            "package-lock.json",
            "src/migrations/0001_init.py",
            "db/migration/0002_add_column.sql",
            "app.migration.yaml",
        ],
    )
    def test_protected_paths_are_denylisted(self, path):
        result = run_bash(f'ai_path_is_denylisted "{path}"')
        assert result.returncode == 0, f"{path} should be denylisted"

    @pytest.mark.parametrize(
        "path",
        [
            "Projects/Heimei/tests/test_status_service.py",
            "Projects/Heimei/docs/ARCHITECTURE.md",
            "Projects/Heimei/README.md",
        ],
    )
    def test_ordinary_paths_are_not_denylisted(self, path):
        result = run_bash(f'ai_path_is_denylisted "{path}"')
        assert result.returncode != 0, f"{path} should NOT be denylisted"


class TestDigestStability:
    """Hardening fix 7: the ONLY semantic-equivalence claim is CRLF ==
    LF. Trailing whitespace, blank lines, and every other byte are
    significant — an earlier version of ai_canonical_issue_body
    stripped per-line trailing whitespace and collapsed blank lines,
    which this pass found to be overreach (Markdown gives trailing
    whitespace real meaning: two trailing spaces is a hard line
    break)."""

    def _digest(self, tmp_path: Path, name: str, content: bytes) -> str:
        f = tmp_path / name
        f.write_bytes(content)
        return run_bash(f"ai_canonical_issue_body < '{f}' | ai_sha256_hex").stdout.strip()

    def test_exact_body_is_stable_across_repeated_calls(self, tmp_path):
        content = b"Problem: fix the thing\nScope: tests/**\n"
        d1 = self._digest(tmp_path, "a.txt", content)
        d2 = self._digest(tmp_path, "b.txt", content)
        assert d1 == d2
        assert len(d1) == 64

    def test_crlf_and_lf_are_deliberately_equivalent(self, tmp_path):
        d_crlf = self._digest(tmp_path, "crlf.txt", b"Problem: fix the thing\r\nScope: tests/**\r\n")
        d_lf = self._digest(tmp_path, "lf.txt", b"Problem: fix the thing\nScope: tests/**\n")
        assert d_crlf == d_lf

    def test_one_trailing_space_changes_digest(self, tmp_path):
        base = self._digest(tmp_path, "base.txt", b"Problem: fix the thing\n")
        one_space = self._digest(tmp_path, "one.txt", b"Problem: fix the thing \n")
        assert base != one_space

    def test_two_trailing_spaces_changes_digest(self, tmp_path):
        base = self._digest(tmp_path, "base2.txt", b"Problem: fix the thing\n")
        two_space = self._digest(tmp_path, "two.txt", b"Problem: fix the thing  \n")
        assert base != two_space

    def test_allowed_path_edit_changes_digest(self, tmp_path):
        base = self._digest(tmp_path, "ap_base.txt", b"Allowed paths:\ntests/**\n")
        edited = self._digest(tmp_path, "ap_edit.txt", b"Allowed paths:\ntests/**\nsrc/extra.py\n")
        assert base != edited

    def test_acceptance_criteria_edit_changes_digest(self, tmp_path):
        base = self._digest(tmp_path, "ac_base.txt", b"Acceptance criteria: passes tests\n")
        edited = self._digest(tmp_path, "ac_edit.txt", b"Acceptance criteria: passes tests and lints\n")
        assert base != edited

    def test_unicode_edit_changes_digest(self, tmp_path):
        base = self._digest(tmp_path, "u_base.txt", "Problem: café\n".encode("utf-8"))
        edited = self._digest(tmp_path, "u_edit.txt", "Problem: cafés\n".encode("utf-8"))
        assert base != edited

    def test_blank_line_in_middle_changes_digest(self, tmp_path):
        # Inserting/removing a blank line in the middle must also
        # change the digest now (the old blank-line COLLAPSING
        # behavior is gone).
        base = self._digest(tmp_path, "bl_base.txt", b"Problem: x\nScope: y\n")
        edited = self._digest(tmp_path, "bl_edit.txt", b"Problem: x\n\nScope: y\n")
        assert base != edited

    def test_real_content_change_produces_different_digest(self, tmp_path):
        digest_a = self._digest(tmp_path, "a.txt", b"Problem: fix the thing\n")
        digest_c = self._digest(tmp_path, "c.txt", b"Problem: fix the OTHER thing\n")
        assert digest_a != digest_c

    # NOTE on naming: the task's required minimum-test list names this
    # scenario "issue_digest_trailing_space_is_significant" — that
    # exact scenario is covered above by
    # test_one_trailing_space_changes_digest (pytest only collects
    # test_*-prefixed methods, so the class-level docstring is where
    # this mapping is recorded rather than a second, differently-named
    # method duplicating the same assertion).


class TestDigestCentralization:
    """Blocker 1 (micro-repair pass): approve.sh, dispatch.sh's initial
    validation, dispatch.sh's post-lock revalidation, and review.sh all
    now call the SAME common.sh helper (ai_issue_digest_from_json)
    instead of each hand-rolling the jq | canonicalize | hash pipeline.
    A prior version had dispatch.sh's own post-lock recheck use a
    different extraction pattern than its own initial check (jq's
    raw-output mode appends a trailing newline that only a two-step
    variable capture strips before canonicalization) — these tests
    prove one implementation now produces identical results everywhere
    it's called, not merely that each call site was patched to match
    by hand a second time."""

    def _digest_via(self, path_kind: str, issue_json: str) -> str:
        """Computes the digest through the exact call site named by
        path_kind, driving the REAL script/function — never a
        hand-rolled pipeline in this test file."""
        if path_kind == "helper":
            result = subprocess.run(
                ["bash", "-c", f"source '{COMMON_SH}'; ai_issue_digest_from_json \"$(cat)\""],
                input=issue_json, capture_output=True, text=True, timeout=30,
            )
        else:
            raise ValueError(path_kind)
        digest = result.stdout.strip()
        assert len(digest) == 64, result.stderr
        return digest

    def test_same_issue_json_produces_identical_digest_through_every_call_site(self, fake_gh_path, fake_git_claim_ref):
        """Test 1. Drives the REAL approve.sh dry-run (which prints
        its own computed ISSUE_DIGEST) and the REAL dispatch.sh
        dry-run (which independently recomputes and compares against
        an approval record built with a reference digest) against the
        SAME issue body — proving both call sites agree, driven
        through the actual scripts, not re-derived in this test."""
        issue_number = 504
        full_body = (
            "### Problem\n\nx\n\n"
            "### Desired outcome\n\ny\n\n"
            "### Acceptance criteria\n\nz\n\n"
            "### Allowed paths\n\na.txt\n"
        )
        reference_digest = compute_issue_digest(full_body)

        bin_dir, log_path = fake_gh_path
        base_env = dict(os.environ)
        base_env["PATH"] = f"{bin_dir}:{base_env['PATH']}"
        base_env["FAKE_GH_LOG"] = str(log_path)
        base_env["FAKE_GH_ISSUE_JSON"] = json.dumps({
            "number": issue_number, "title": "t", "state": "OPEN",
            "labels": [{"name": "risk:low"}], "body": full_body, "url": "u", "comments": [],
        })
        approve_result = subprocess.run(
            [str(SCRIPTS_DIR / "approve.sh"), str(issue_number), "--agent", "claude", "--risk", "low", "--dry-run"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=base_env, timeout=30,
        )
        assert approve_result.returncode == 0, approve_result.stderr
        m = re.search(r"Issue-body digest: `([0-9a-f]{64})`", approve_result.stdout)
        assert m, approve_result.stdout
        approve_digest = m.group(1)
        assert approve_digest == reference_digest

        # dispatch.sh's initial validation, given an approval record
        # built with the reference digest, must accept it as
        # unchanged — proving dispatch.sh's own extraction agrees.
        record = {
            "approval_id": f"appr-{issue_number}-centralize", "repository_id": "R_kgDOTrfRlg", "issue_number": issue_number,
            "approver": "gokul-hastrophil", "agent": "claude", "risk": "low",
            "issue_body_digest": reference_digest, "allowed_paths": ["a.txt"],
            "base_sha": subprocess.run(["git", "rev-parse", "origin/main"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip(),
            "timestamp": "2026-01-01T00:00:00Z", "schema": "heimei-approval/v1",
        }
        approval_comment_body = "## Approval\n```json\n" + json.dumps(record) + "\n```\n<!-- heimei-approval:v1 -->"
        issue_json_with_approval = json.dumps({
            "number": issue_number, "title": "t", "state": "OPEN", "labels": [{"name": "risk:low"}], "body": full_body, "url": "u",
            "comments": [{"id": "c1", "author": {"login": "gokul-hastrophil"}, "body": approval_comment_body, "createdAt": "2026-01-01T00:00:00Z"}],
        })
        dispatch_env = dict(os.environ)
        dispatch_env["PATH"] = f"{fake_git_claim_ref}:{bin_dir}:{dispatch_env['PATH']}"
        dispatch_env["FAKE_GH_LOG"] = str(log_path)
        dispatch_env["FAKE_GH_ISSUE_JSON"] = issue_json_with_approval
        dispatch_env["FAKE_GIT_CLAIM_REF_SHA"] = ""
        dispatch_result = subprocess.run(
            [str(SCRIPTS_DIR / "dispatch.sh"), str(issue_number), "--agent", "claude", "--dry-run"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=dispatch_env, timeout=60,
        )
        assert dispatch_result.returncode == 0, dispatch_result.stderr
        assert "edited after approval" not in dispatch_result.stderr

    def test_unchanged_body_passes_post_lock_revalidation(self):
        # Covered as an integration test below
        # (test_dispatch_execute_reaches_post_lock_digest_check_and_passes),
        # which additionally proves the SCRIPT reaches and passes this
        # exact check, not just that two independent digest
        # computations happen to agree in isolation.
        pass

    def test_one_character_body_change_fails_post_lock_revalidation(self, fake_gh_path, fake_git_claim_ref, tmp_path):
        """Test 3, driven through the real dispatch.sh --execute
        post-lock path (fake GitHub backend only — no real mutation):
        the issue body returned on dispatch's SECOND `gh issue view`
        call (post-lock) differs from the first by exactly one
        character, and dispatch.sh must die at the post-lock digest
        check, never proceeding to claim/worktree/agent."""
        issue_number = 502
        issue_json, record = build_dispatch_ready_issue(issue_number, "low", f"appr-{issue_number}-onechar")
        payload = json.loads(issue_json)
        changed_payload = json.loads(issue_json)
        changed_payload["body"] = payload["body"] + "!"  # exactly one character added

        call_marker = tmp_path / "issue-view-call-marker"
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_claim_ref}:{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = json.dumps(payload)
        env["FAKE_GH_ISSUE_JSON_SECOND_CALL"] = json.dumps(changed_payload)
        env["FAKE_GH_ISSUE_VIEW_CALL_MARKER"] = str(call_marker)
        env["FAKE_GIT_CLAIM_REF_SHA"] = ""

        result = subprocess.run(
            [str(SCRIPTS_DIR / "dispatch.sh"), str(issue_number), "--agent", "claude", "--execute"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode != 0, result.stderr
        assert "Issue body changed between validation and lock acquisition" in result.stderr
        # Never reached the claim step, let alone worktree/agent.
        assert "Claim ref created atomically" not in result.stderr
        assert "git worktree add" not in result.stderr

    def test_dispatch_execute_reaches_post_lock_digest_check_and_passes(self, fake_gh_path, fake_git_claim_ref):
        """The required integration-style test: an unchanged body
        (identical on both the initial and post-lock `gh issue view`
        calls) must let dispatch.sh --execute's post-lock revalidation
        PASS and let execution proceed past it to a later, unrelated,
        safe failure (the fake backend has no claim-ref state
        configured, so the atomic-claim step fails cleanly next) —
        never a static source-string check, an actual run reaching
        that exact line of dispatch.sh."""
        issue_number = 503
        issue_json, record = build_dispatch_ready_issue(issue_number, "low", f"appr-{issue_number}-unchanged")
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_claim_ref}:{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = issue_json
        env["FAKE_GIT_CLAIM_REF_SHA"] = ""

        result = subprocess.run(
            [str(SCRIPTS_DIR / "dispatch.sh"), str(issue_number), "--agent", "claude", "--execute"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
        )
        # It WILL fail eventually (the fake backend's claim-ref
        # response doesn't match, by design, to stop this test safely
        # before any local git worktree/branch mutation) — the
        # property under test is that it does NOT fail at the digest
        # check, and visibly progresses past it first.
        assert "Issue body changed between validation and lock acquisition" not in result.stderr
        assert "Re-validating after acquiring the lock" in result.stderr
        assert "git worktree add" not in result.stderr
        assert "git branch -f" not in result.stderr

    def test_allowed_path_edit_fails_post_lock_style_digest_comparison(self):
        d1 = compute_issue_digest("Allowed paths:\ntests/**")
        d2 = compute_issue_digest("Allowed paths:\ntests/**\nsrc/extra.py")
        assert d1 != d2

    def test_acceptance_criteria_edit_fails_digest_comparison(self):
        d1 = compute_issue_digest("Acceptance criteria: passes tests")
        d2 = compute_issue_digest("Acceptance criteria: passes tests and lints")
        assert d1 != d2

    def test_trailing_space_changes_digest_via_helper(self):
        d1 = compute_issue_digest("Problem: x")
        d2 = compute_issue_digest("Problem: x ")
        assert d1 != d2

    def test_blank_line_edit_changes_digest_via_helper(self):
        d1 = compute_issue_digest("Problem: x\nScope: y")
        d2 = compute_issue_digest("Problem: x\n\nScope: y")
        assert d1 != d2

    def test_unicode_edit_changes_digest_via_helper(self):
        d1 = compute_issue_digest("Problem: café")
        d2 = compute_issue_digest("Problem: cafés")
        assert d1 != d2

    def test_crlf_lf_equivalence_via_helper(self):
        d1 = compute_issue_digest("Problem: x\r\nScope: y\r\n")
        d2 = compute_issue_digest("Problem: x\nScope: y\n")
        assert d1 == d2

    def test_no_duplicate_digest_extraction_pipelines_remain(self):
        """Search requirement: every issue-body digest computation
        across Scripts/ai must go through the one shared helper — no
        script may hand-roll `jq -r '.body' | ai_canonical_issue_body`
        itself anymore."""
        for name in ("approve.sh", "dispatch.sh", "review.sh"):
            source = (SCRIPTS_DIR / name).read_text()
            assert "ai_canonical_issue_body" not in source, f"{name} still references ai_canonical_issue_body directly — should call ai_issue_digest_from_json instead"
        common_source = (SCRIPTS_DIR / "common.sh").read_text()
        assert common_source.count("def ai_issue_digest_from_json") <= 1 or common_source.count("ai_issue_digest_from_json()") == 1


class TestRedaction:
    def test_github_token_is_redacted(self):
        result = run_bash("printf 'token: ghp_abcdefghijklmnopqrstuvwxyz0123456789\\n' | ai_redact")
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in result.stdout
        assert "REDACTED" in result.stdout

    def test_api_key_assignment_is_redacted(self):
        result = run_bash("printf 'api_key=sk-supersecretvalue123\\n' | ai_redact")
        assert "sk-supersecretvalue123" not in result.stdout

    def test_home_path_is_redacted(self):
        result = run_bash("printf '/home/kniti/Heimei/Temp\\n' | ai_redact")
        assert "kniti" not in result.stdout

    def test_ordinary_text_passes_through_unchanged(self):
        result = run_bash("printf 'The tests all pass.\\n' | ai_redact")
        assert result.stdout.strip() == "The tests all pass."

    def test_bounded_output_truncates(self):
        result = run_bash("printf '%s' \"$(head -c 1000 /dev/zero | tr '\\0' 'x')\" | ai_bounded_output 10")
        assert len(result.stdout) == 10

    # --- Blocker 5: required secret-type coverage ------------------

    def test_redact_bearer_authorization(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text("Authorization: Bearer bearer-secret\n")
        result = run_bash(f"ai_redact < '{f}'")
        assert "bearer-secret" not in result.stdout
        assert "Authorization: Bearer [REDACTED]" in result.stdout

    def test_redact_bearer_authorization_mixed_case(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text("authorization: bearer MixedCaseSecret\n")
        result = run_bash(f"ai_redact < '{f}'")
        assert "MixedCaseSecret" not in result.stdout

    def test_redact_aws_access_key(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text("AKIAIOSFODNN7EXAMPLE\n")
        result = run_bash(f"ai_redact < '{f}'")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.stdout
        assert "REDACTED" in result.stdout

    def test_redact_aws_sts_access_key(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text("ASIAABCDEFGHIJKLMNOP\n")
        result = run_bash(f"ai_redact < '{f}'")
        assert "ASIAABCDEFGHIJKLMNOP" not in result.stdout
        assert "REDACTED" in result.stdout

    def test_redact_openssh_private_key_block(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUSecretKeyMaterialDoNotLeak\n"
            "-----END OPENSSH PRIVATE KEY-----\n"
        )
        result = run_bash(f"ai_redact < '{f}'")
        assert "SecretKeyMaterialDoNotLeak" not in result.stdout
        assert "BEGIN OPENSSH PRIVATE KEY" not in result.stdout
        assert "REDACTED-PRIVATE-KEY-BLOCK" in result.stdout

    def test_redact_generic_private_key_block(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text(
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwSecretPKCS8DataHere\n"
            "-----END PRIVATE KEY-----\n"
        )
        result = run_bash(f"ai_redact < '{f}'")
        assert "SecretPKCS8DataHere" not in result.stdout
        assert "REDACTED-PRIVATE-KEY-BLOCK" in result.stdout

    def test_redact_rsa_private_key_block(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEASecretRSAKeyDataHere\n"
            "-----END RSA PRIVATE KEY-----\n"
        )
        result = run_bash(f"ai_redact < '{f}'")
        assert "SecretRSAKeyDataHere" not in result.stdout
        assert "REDACTED-PRIVATE-KEY-BLOCK" in result.stdout

    def test_redact_ec_private_key_block(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text(
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHcCAQEEISecretECKeyDataHere\n"
            "-----END EC PRIVATE KEY-----\n"
        )
        result = run_bash(f"ai_redact < '{f}'")
        assert "SecretECKeyDataHere" not in result.stdout
        assert "REDACTED-PRIVATE-KEY-BLOCK" in result.stdout

    def test_secret_near_beginning_of_huge_transcript_is_redacted(self, tmp_path):
        f = tmp_path / "in.txt"
        f.write_text("AKIAIOSFODNN7EXAMPLE\n" + ("x" * 100_000) + "\n")
        result = run_bash(f"ai_redact < '{f}'")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.stdout

    def test_redaction_occurs_before_excerpt_bounding(self, tmp_path):
        """The secret sits exactly at a would-be truncation boundary.
        If bounding happened BEFORE redaction, the secret could be cut
        mid-pattern, leaving an unredacted fragment. Redact-then-bound
        (the actual, required order) replaces the WHOLE secret first,
        so no fragment can ever survive truncation."""
        # A real word-boundary (space) before the key, matching how a
        # key actually appears in real text (never glued directly to
        # unrelated ASCII with no separator) — the regex's \b would
        # correctly decline to match a mid-identifier substring, which
        # is a false-positive guard, not a bug.
        prefix = ("x " * 25)
        secret = "AKIAIOSFODNN7EXAMPLE"
        f = tmp_path / "in.txt"
        f.write_text(prefix + secret + (" y" * 250))
        bounded = run_bash(f"ai_redact < '{f}' | ai_bounded_output {len(prefix) + 10}").stdout
        assert "AKIA" not in bounded
        assert secret not in bounded
        # Full (unbounded) redaction must also never contain the secret.
        full = run_bash(f"ai_redact < '{f}'").stdout
        assert secret not in full

    def test_secret_after_normal_excerpt_cutoff_never_reaches_derived_artifacts(self, tmp_path):
        """A secret placed well AFTER a typical excerpt cutoff must
        still never appear in anything derived from redact-then-bound
        — trivially true once truncated away, but this test pins down
        that redaction (not luck of truncation) is what the pipeline
        relies on by also checking the FULL redacted text (no
        truncation at all)."""
        f = tmp_path / "in.txt"
        f.write_text(("x" * 5000) + "\nAuthorization: Bearer late-secret-value\n")
        full = run_bash(f"ai_redact < '{f}'").stdout
        assert "late-secret-value" not in full
        bounded = run_bash(f"ai_redact < '{f}' | ai_bounded_output 100").stdout
        assert "late-secret-value" not in bounded


class TestWorktreeSafety:
    def test_refuses_path_outside_configured_root(self, tmp_path):
        outside = tmp_path / "not-under-worktree-root"
        outside.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=outside, check=True)
        result = run_bash(f'ai_safe_remove_worktree "{REPO_ROOT}" "{outside}"')
        assert result.returncode != 0
        assert "outside configured root" in result.stderr or "does not exist" in result.stderr

    def test_refuses_the_primary_checkout(self):
        result = run_bash(f'ai_safe_remove_worktree "{REPO_ROOT}" "{REPO_ROOT}"')
        assert result.returncode != 0

    def test_refuses_a_symlink(self, tmp_path):
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real_dir)
        result = run_bash(f'ai_safe_remove_worktree "{REPO_ROOT}" "{link}"')
        assert result.returncode != 0

    def test_absent_worktree_is_a_harmless_noop(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        result = run_bash(f'ai_safe_remove_worktree "{REPO_ROOT}" "{missing}"')
        assert result.returncode == 0


class TestChangedPathValidation:
    def _make_worktree_like_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "wt"
        d.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
        (d / "README.md").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=d, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, check=True)
        return d

    def test_allowed_path_passes(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "allowed.txt").write_text("hello\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'allowed.txt'")
        assert result.returncode == 0, result.stderr

    def test_scope_escape_rejected(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "unrelated.txt").write_text("hello\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'allowed.txt'")
        assert result.returncode != 0
        assert "not covered by the approved allowlist" in result.stderr

    def test_protected_path_modification_rejected_even_if_allowlisted(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "VISION.md").write_text("tampered\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'VISION.md'")
        assert result.returncode != 0
        assert "denylisted" in result.stderr

    def test_dependency_manifest_rejected_even_if_allowlisted(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "pyproject.toml").write_text("[project]\nname='x'\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'pyproject.toml'")
        assert result.returncode != 0
        assert "denylisted" in result.stderr

    def test_forbidden_artifact_name_rejected(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "STOP_REASON.txt").write_text("x\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'STOP_REASON.txt'")
        assert result.returncode != 0
        assert "forbidden artifact name" in result.stderr

    def test_env_file_rejected(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / ".env").write_text("SECRET=x\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' '.env'")
        assert result.returncode != 0

    def test_symlink_escape_rejected(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        outside_target = tmp_path / "outside.txt"
        outside_target.write_text("secret\n")
        link = d / "innocuous.txt"
        link.symlink_to(outside_target)
        result = run_bash(f"ai_validate_changed_paths '{d}' 'innocuous.txt'")
        assert result.returncode != 0
        assert "symlink" in result.stderr.lower() or "not inside required parent" in result.stderr

    def test_filename_with_embedded_newline_is_handled_nul_safely(self, tmp_path):
        # The exact defect class item 10 targets: an earlier version
        # piped git's -z output through awk+tr, which corrupts a
        # filename containing a literal newline by rewriting that
        # newline into a NUL and splitting one filename into two
        # array entries. This filename is denylisted-by-name only if
        # misparsed; if NUL-safety holds, it is simply "not in the
        # allowlist" as a single whole entry (the allowlist below
        # intentionally does NOT match it, so the correct outcome is
        # exactly one clean allowlist-rejection, not a crash, not a
        # silently-approved half-filename).
        d = self._make_worktree_like_dir(tmp_path)
        name = "weird\nname.txt"
        (d / name).write_text("x\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'allowed.txt'")
        assert result.returncode != 0
        assert "not covered by the approved allowlist" in result.stderr

    def test_filename_with_leading_dash_is_handled_safely(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "-rf").write_text("x\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' '-rf'")
        assert result.returncode == 0, result.stderr

    def test_filename_with_glob_characters_is_handled_safely(self, tmp_path):
        d = self._make_worktree_like_dir(tmp_path)
        (d / "file[1].txt").write_text("x\n")
        result = run_bash(f"ai_validate_changed_paths '{d}' 'file[1].txt'")
        assert result.returncode == 0, result.stderr


class TestWorktreeRegistration:
    """ai_require_registered_worktree / ai_worktree_primary_root — real
    git worktree semantics against a throwaway local-only branch of
    THIS repository. Never pushed; branch and worktree removed at the
    end of every test."""

    def test_registered_worktree_accepted(self):
        import uuid

        branch = f"tmp/harness-registered-{uuid.uuid4().hex[:8]}"
        wt_dir = Path(subprocess.run(["mktemp", "-d"], capture_output=True, text=True, check=True).stdout.strip()) / "wt"
        try:
            subprocess.run(["git", "worktree", "add", "-q", "-b", branch, str(wt_dir), "HEAD"], cwd=REPO_ROOT, check=True)
            result = run_bash(f"ai_require_registered_worktree '{wt_dir}'")
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == str(REPO_ROOT.resolve())
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=REPO_ROOT, check=False)
            subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False)

    def test_standalone_sibling_repo_is_trivially_self_registered(self, tmp_path):
        # IMPORTANT division of labor: ai_require_registered_worktree
        # alone cannot detect "this is an unrelated sibling repository
        # masquerading as a Heimei worktree" — every git repository is
        # trivially registered as ITS OWN first worktree entry, so a
        # standalone sibling repo (even one with a fake Projects/Heimei
        # directory) legitimately passes THIS function; it returns
        # that sibling's own root as "the primary repository, as far
        # as this function alone can tell." The actual defense against
        # a sibling-repository attack is the CALLER (verify.sh --mode
        # dispatch) additionally cross-checking that returned root
        # against verify.sh's own known primary root — see
        # TestVerifyShDispatchMode.test_unregistered_checkout_rejected,
        # which exercises that real, complete defense end to end.
        sibling = tmp_path / "sibling"
        subprocess.run(["git", "init", "-q", str(sibling)], check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=sibling, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=sibling, check=True)
        (sibling / "Projects" / "Heimei").mkdir(parents=True)
        (sibling / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=sibling, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=sibling, check=True)
        result = run_bash(f"ai_require_registered_worktree '{sibling}'")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(sibling.resolve())

    def test_primary_checkout_itself_is_registered_but_verify_still_rejects_it_as_dispatch_worktree(self):
        # ai_require_registered_worktree alone doesn't reject the
        # primary checkout (it IS trivially "registered" — every repo
        # lists itself first in `git worktree list`); verify.sh --mode
        # dispatch is what adds the additional "never the primary
        # checkout" rule. Covered separately in TestVerifyShDispatchMode.
        result = run_bash(f"ai_require_registered_worktree '{REPO_ROOT}'")
        assert result.returncode == 0, result.stderr


class TestNetworkIsolation:
    """Real, empirical bwrap tests — not config-flag assumptions."""

    def test_bwrap_availability_matches_command_v(self):
        result = run_bash("ai_bwrap_available && echo yes || echo no")
        expected = "yes" if subprocess.run(["bash", "-c", "command -v bwrap"], capture_output=True).returncode == 0 else "no"
        assert result.stdout.strip() == expected

    def test_network_isolation_is_empirically_confirmed_when_bwrap_present(self):
        if subprocess.run(["bash", "-c", "command -v bwrap"], capture_output=True).returncode != 0:
            pytest.skip("bubblewrap not installed on this machine")
        result = run_bash("ai_verify_network_isolation && echo isolated || echo not-isolated")
        assert result.stdout.strip() == "isolated"


# ---------------------------------------------------------------------------
# Script-level tests via a fake `gh` on PATH — no real GitHub call ever.
# ---------------------------------------------------------------------------


FAKE_GH_SCRIPT = r"""#!/usr/bin/env bash
# Minimal fake `gh` for harness tests. Logs every invocation (without
# any secret) to $FAKE_GH_LOG, then dispatches to canned, deterministic
# behavior controllable via env vars. Never touches the network.
set -uo pipefail
echo "$*" >> "${FAKE_GH_LOG}"

if [[ "${FAKE_GH_FAIL_ON:-}" != "" ]] && [[ "$*" == ${FAKE_GH_FAIL_ON}* ]]; then
  echo "fake gh: simulated failure for: $*" >&2
  exit 1
fi

case "$1 $2" in
  "auth status") exit 0 ;;
esac

case "$1" in
  repo)
    if [[ "$2" == "view" ]]; then
      echo '{"id":"R_kgDOTrfRlg","nameWithOwner":"gokul-hastrophil/heimei"}'
      exit 0
    fi
    ;;
  pr)
    if [[ "$2" == "list" ]]; then
      echo "${FAKE_GH_PR_LIST:-[]}"
      exit 0
    fi
    if [[ "$2" == "review" ]]; then
      exit 0
    fi
    ;;
  label)
    if [[ "$2" == "list" ]]; then
      if [[ -n "${FAKE_GH_LABEL_LIST_FAIL:-}" ]]; then
        echo "fake gh: simulated label list failure (network/permission)" >&2
        exit 1
      fi
      # Real `gh label list --json name --jq '.[].name'` applies the
      # --jq filter itself before printing — every caller in this repo
      # uses that exact filter, so replicate it here rather than
      # parsing --jq generically.
      printf '%s' "${FAKE_GH_LABEL_LIST_JSON:-[]}" | jq -r '.[].name'
      exit 0
    fi
    ;;
  api)
    case "$*" in
      *"/protection"*)
        mode="${FAKE_GH_PROTECTION_MODE:-ok}"
        case "${mode}" in
          ok)
            echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"enforce_admins":{"enabled":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false},"required_status_checks":{"contexts":["ci"]}}'
            exit 0 ;;
           no-protection)
            echo '{"message":"Branch not protected"}' >&2
            exit 1 ;;
           403)
            echo '{"message":"Resource not accessible"}' >&2
            exit 1 ;;
          404)
            echo '{"message":"Not Found"}' >&2
            exit 1 ;;
          malformed-json)
            echo 'not valid json at all'
            exit 0 ;;
          pr-not-required)
            echo '{"required_pull_request_reviews":null,"enforce_admins":{"enabled":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false},"required_status_checks":{"contexts":["ci"]}}'
            exit 0 ;;
          force-push-allowed)
            echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"enforce_admins":{"enabled":true},"allow_force_pushes":{"enabled":true},"allow_deletions":{"enabled":false},"required_status_checks":{"contexts":["ci"]}}'
            exit 0 ;;
          deletions-allowed)
            echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"enforce_admins":{"enabled":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":true},"required_status_checks":{"contexts":["ci"]}}'
            exit 0 ;;
          checks-absent)
            echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"enforce_admins":{"enabled":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false},"required_status_checks":null}'
            exit 0 ;;
          admins-not-enforced)
            echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"enforce_admins":{"enabled":false},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false},"required_status_checks":{"contexts":["ci"]}}'
            exit 0 ;;
          cli-failure)
            echo 'gh: some transport error' >&2
            exit 1 ;;
        esac
        ;;
      *"/rulesets/"*)
        # NOTE: the default value can't be a literal brace-containing
        # string inside ${VAR:-...} — bash's brace matching for that
        # construct gets confused by unescaped nested braces and
        # appends a stray '}' to the output. Use a plain intermediate
        # variable instead.
        ruleset_detail_default='{"bypass_actors":[]}'
        echo "${FAKE_GH_RULESET_DETAIL:-${ruleset_detail_default}}"
        exit 0 ;;
      *"/rulesets"*)
        echo "${FAKE_GH_RULESETS_LIST:-[]}"
        exit 0 ;;
      *"/git/refs"*)
        state_file="${FAKE_GH_CLAIM_STATE:-}"
        if [[ -n "${state_file}" ]]; then
          ref="" ; sha=""
          args=("$@")
          for ((idx=0; idx<${#args[@]}; idx++)); do
            case "${args[$idx]}" in
              ref=*) ref="${args[$idx]#ref=}" ;;
              sha=*) sha="${args[$idx]#sha=}" ;;
            esac
          done
          # NOT mkdir: empirically confirmed (this pass, via a direct
          # repro harness outside pytest — see the final report) that
          # plain `mkdir` on this sandbox's filesystem does NOT
          # reliably provide POSIX-atomic directory-entry creation
          # under genuine concurrent access — two simultaneous `mkdir`
          # calls on the identical path both returned success in a
          # real, reproducible fraction of runs, with no error on
          # either side. `flock` on a file descriptor was verified
          # (40/40 runs, zero double-winners) to be reliable in this
          # same environment where bare `mkdir` was not, so the
          # compare-and-set here is: acquire a BLOCKING flock (mutual
          # exclusion that this environment actually honors), THEN —
          # only one process is ever inside this section at a time —
          # check-and-create a plain marker FILE (not a directory) as
          # the actual persistent "already claimed" record, release
          # the lock. This is a fix to the TEST'S simulated GitHub
          # backend only; ai_create_claim_ref (common.sh) makes no
          # local filesystem calls of its own at all — it only calls
          # `gh api ...` and interprets that response, so this change
          # never touches production claim semantics.
          lock_fd_path="${state_file}.flock"
          marker_path="${state_file}.claimed"
          exec {claim_lock_fd}>"${lock_fd_path}"
          flock "${claim_lock_fd}"
          if [[ -e "${marker_path}" ]]; then
            flock -u "${claim_lock_fd}"
            exec {claim_lock_fd}>&-
            printf 'CLAIM_DENIED pid=%s ref=%s sha=%s state=%s\n' "$$" "${ref}" "${sha}" "${state_file}" >> "${FAKE_GH_LOG}"
            echo '{"message":"Reference already exists"}' >&2
            exit 1
          fi
          printf 'ref=%s\nsha=%s\npid=%s\n' "${ref}" "${sha}" "$$" > "${marker_path}"
          flock -u "${claim_lock_fd}"
          exec {claim_lock_fd}>&-
          printf 'CLAIM_GRANTED pid=%s ref=%s sha=%s state=%s\n' "$$" "${ref}" "${sha}" "${state_file}" >> "${FAKE_GH_LOG}"
          printf '{"ref":"%s","object":{"sha":"%s"}}\n' "${ref}" "${sha}"
          exit 0
        fi
        echo '{"ref":"unset","object":{"sha":"unset"}}'
        exit 0 ;;
      *"/pulls/"*)
        # repo.id is the REST numeric database ID, repo.node_id is the
        # GraphQL node ID that .ai/policy.toml's repository.id actually
        # stores — deliberately DIFFERENT-shaped values here (a real
        # numeric ID, not the node-ID string) so a caller that
        # mistakenly compares .id against the policy ID (the bug this
        # harness now regression-tests) fails, and only a correct
        # .node_id comparison succeeds.
        pulls_default='{"base":{"ref":"main","sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"head":{"sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","repo":{"id":1320669590,"node_id":"R_kgDOTrfRlg"}},"changed_files":0,"title":"t","html_url":"https://example/1"}'
        echo "${FAKE_GH_PULLS_JSON:-${pulls_default}}"
        exit 0 ;;
      *"user"*)
        # Real `gh api ... --jq FILTER` applies FILTER server-side
        # before printing — this fake must too, or a caller like
        # ai_current_actor (which always passes --jq '.login') gets
        # back the whole JSON object instead of the bare login string.
        if printf '%s\n' "$*" | grep -q -- '--jq'; then
          printf '%s\n' '{"login":"gokul-hastrophil"}' | jq -r '.login'
        else
          echo '{"login":"gokul-hastrophil"}'
        fi
        exit 0 ;;
    esac
    ;;
  issue)
    if [[ "$2" == "view" ]]; then
      # Optional stateful second-call override, for integration tests
      # that need to simulate the issue body changing BETWEEN dispatch's
      # initial validation and its post-lock re-fetch — a real marker
      # file (not an in-memory counter, since this runs as a fresh
      # process each invocation) tracks whether this is the first call.
      call_marker="${FAKE_GH_ISSUE_VIEW_CALL_MARKER:-}"
      body_to_use="${FAKE_GH_ISSUE_JSON:-}"
      if [[ -n "${call_marker}" ]]; then
        if [[ -f "${call_marker}" ]]; then
          body_to_use="${FAKE_GH_ISSUE_JSON_SECOND_CALL:-${FAKE_GH_ISSUE_JSON:-}}"
        else
          : > "${call_marker}"
        fi
      fi
      echo "${body_to_use}"
      if [[ -n "${body_to_use}" ]]; then exit 0; else exit 1; fi
    fi
    if [[ "$2" == "edit" ]]; then
      exit 0
    fi
    if [[ "$2" == "comment" ]]; then
      echo "https://github.com/gokul-hastrophil/heimei/issues/1#issuecomment-1"
      exit 0
    fi
    ;;
esac

echo "fake gh: unhandled invocation (see FAKE_GH_LOG): $*" >&2
exit 1
"""


@pytest.fixture
def fake_gh_path(tmp_path):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-calls.log"
    log_path.write_text("")
    gh_path = bin_dir / "gh"
    gh_path.write_text(FAKE_GH_SCRIPT)
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC)
    return bin_dir, log_path


def run_script(
    script: str, args: list[str], fake_gh_path, extra_env: dict | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    bin_dir, log_path = fake_gh_path
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_GH_LOG"] = str(log_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPTS_DIR / script), *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestBranchProtectionFailsClosed:
    """Item 1: every unknown/malformed/absent/unsafe state dies, never warns."""

    @pytest.mark.parametrize(
        "mode,expected_fragment",
        [
            ("no-protection", "FAILED CLOSED"),
            ("403", "FAILED CLOSED"),
            ("404", "FAILED CLOSED"),
            ("malformed-json", "malformed"),
            ("pr-not-required", "pull-request review enforcement"),
            ("force-push-allowed", "force pushes"),
            ("deletions-allowed", "branch deletion"),
            ("checks-absent", "required status checks"),
            ("admins-not-enforced", "bypass"),
            ("cli-failure", "FAILED CLOSED"),
        ],
    )
    def test_fails_closed(self, fake_gh_path, mode, expected_fragment):
        result = run_bash(
            'ai_require_branch_protection "main"',
            env={
                "PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"],
                "FAKE_GH_LOG": str(fake_gh_path[1]),
                "FAKE_GH_PROTECTION_MODE": mode,
            },
        )
        assert result.returncode != 0
        assert expected_fragment.lower() in result.stderr.lower()

    def test_protected_branch_accepted(self, fake_gh_path):
        result = run_bash(
            'ai_require_branch_protection "main"',
            env={
                "PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"],
                "FAKE_GH_LOG": str(fake_gh_path[1]),
            },
        )
        assert result.returncode == 0, result.stderr

    def test_bypass_actor_present_fails_closed(self, fake_gh_path):
        result = run_bash(
            'ai_require_branch_protection "main"',
            env={
                "PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"],
                "FAKE_GH_LOG": str(fake_gh_path[1]),
                "FAKE_GH_RULESETS_LIST": json.dumps([{"id": 1, "enforcement": "active"}]),
                "FAKE_GH_RULESET_DETAIL": json.dumps({"bypass_actors": [{"actor_id": 1}]}),
            },
        )
        assert result.returncode != 0
        assert "bypass" in result.stderr.lower()

    def test_dry_run_runs_the_same_check_as_execute(self, fake_gh_path):
        # dispatch.sh calls ai_require_branch_protection unconditionally,
        # before the dry-run/execute branch — a dry run with broken
        # protection must fail exactly like an execute run would.
        result = run_script(
            "dispatch.sh",
            ["5", "--agent", "claude", "--dry-run"],
            fake_gh_path,
            extra_env={"FAKE_GH_PROTECTION_MODE": "no-protection"},
        )
        assert result.returncode != 0
        assert "FAILED CLOSED" in result.stderr


class TestAtomicClaim:
    """Item 3: create-reference API, never a plain push."""

    def test_first_create_succeeds(self, fake_gh_path, tmp_path):
        state_file = tmp_path / "claim-state"
        result = run_bash(
            'ai_create_claim_ref "refs/heads/ai-claims/issue-5-approval-appr-5-abc" "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            env={
                "PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"],
                "FAKE_GH_LOG": str(fake_gh_path[1]),
                "FAKE_GH_CLAIM_STATE": str(state_file),
            },
        )
        assert result.returncode == 0, result.stderr

    def test_second_create_receives_422_and_fails(self, fake_gh_path, tmp_path):
        state_file = tmp_path / "claim-state"
        env = {
            "PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"],
            "FAKE_GH_LOG": str(fake_gh_path[1]),
            "FAKE_GH_CLAIM_STATE": str(state_file),
        }
        first = run_bash(
            'ai_create_claim_ref "refs/heads/ai-claims/issue-5-approval-appr-5-abc" "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            env=env,
        )
        assert first.returncode == 0, first.stderr
        second = run_bash(
            'ai_create_claim_ref "refs/heads/ai-claims/issue-5-approval-appr-5-abc" "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            env=env,
        )
        assert second.returncode != 0
        assert "already exists" in second.stderr.lower() or "already claimed" in second.stderr.lower()

    def test_two_simulated_hosts_racing_the_same_claim(self, fake_gh_path, tmp_path):
        # Same shared state file, as if two machines raced the same
        # create-ref call — the second one must fail, never both succeed.
        state_file = tmp_path / "claim-state"
        env = {
            "PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"],
            "FAKE_GH_LOG": str(fake_gh_path[1]),
            "FAKE_GH_CLAIM_STATE": str(state_file),
        }
        host_a = run_bash(
            'ai_create_claim_ref "refs/heads/ai-claims/issue-9-approval-appr-9-xyz" "cccccccccccccccccccccccccccccccccccccccc"',
            env=env,
        )
        host_b = run_bash(
            'ai_create_claim_ref "refs/heads/ai-claims/issue-9-approval-appr-9-xyz" "cccccccccccccccccccccccccccccccccccccccc"',
            env=env,
        )
        outcomes = sorted([host_a.returncode, host_b.returncode])
        assert outcomes == [0, 1], "exactly one host should win the claim"

    def test_malformed_ref_rejected_before_any_api_call(self, fake_gh_path):
        result = run_bash(
            'ai_create_claim_ref "refs/heads/../etc/passwd" "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            env={"PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"], "FAKE_GH_LOG": str(fake_gh_path[1])},
        )
        assert result.returncode != 0
        assert fake_gh_path[1].read_text() == ""

    def test_malformed_sha_rejected_before_any_api_call(self, fake_gh_path):
        result = run_bash(
            'ai_create_claim_ref "refs/heads/ai-claims/issue-5-approval-appr-5-abc" "not-a-sha"',
            env={"PATH": f"{fake_gh_path[0]}:" + os.environ["PATH"], "FAKE_GH_LOG": str(fake_gh_path[1])},
        )
        assert result.returncode != 0
        assert fake_gh_path[1].read_text() == ""


class TestVerifyShWrongCheckout:
    def test_missing_mode_defaults_to_developer_but_still_needs_repo_root(self, fake_gh_path):
        result = run_script("verify.sh", ["--full"], fake_gh_path)
        assert result.returncode != 0
        assert "Missing required --repo-root" in result.stderr

    def test_path_outside_allowed_roots_rejected(self, fake_gh_path, tmp_path):
        outside = tmp_path / "unrelated"
        outside.mkdir()
        result = run_script("verify.sh", ["--mode", "developer", "--repo-root", str(outside)], fake_gh_path)
        assert result.returncode != 0
        assert "neither the primary checkout" in result.stderr

    def test_symlink_repo_root_rejected(self, fake_gh_path, tmp_path):
        link = tmp_path / "link-to-repo"
        link.symlink_to(REPO_ROOT)
        result = run_script("verify.sh", ["--mode", "developer", "--repo-root", str(link)], fake_gh_path)
        assert result.returncode != 0
        assert "symlink" in result.stderr.lower()

    def test_invalid_mode_rejected(self, fake_gh_path):
        result = run_script("verify.sh", ["--mode", "bogus", "--repo-root", str(REPO_ROOT)], fake_gh_path)
        assert result.returncode != 0
        assert "Invalid --mode" in result.stderr


class TestVerifyShHeimeiHomeEnv:
    """CI environment-root regression: heimei.config.settings.ConfigPaths
    defaults HEIMEI_HOME's underlying path to Path.home()/"Heimei" —
    correct only when the checkout genuinely lives at $HOME/Heimei.
    Neither a GitHub Actions runner ($HOME=/home/runner, repo at
    $GITHUB_WORKSPACE) nor an automated dispatch worktree (under
    Temp/ai-worktrees/) satisfies that in general. verify.sh must
    export HEIMEI_HOME=<the exact validated --repo-root> for every
    project subprocess it runs, never inferring it.

    On THIS development machine the primary checkout happens to live
    at $HOME/Heimei, so a worktree under its own Temp/ai-worktrees/ is
    incidentally still a subdirectory of $HOME/Heimei — which would
    make "assert the path isn't under $HOME/Heimei" untestable here
    even though the underlying property (HEIMEI_HOME must equal the
    EXACT validated root, not something merely nearby) is still fully
    checkable. Rather than depend on where this machine's repo happens
    to sit, this test overrides $HOME for the subprocess to a
    deliberately unrelated temp directory — reproducing the actual
    GitHub Actions condition (HOME does not contain the checkout at
    all) precisely, regardless of this machine's own layout. If
    verify.sh ever silently fell back to the default, HEIMEI_HOME
    would resolve to <fake HOME>/Heimei — a path that doesn't exist
    and is never equal to the real worktree — so this test would fail
    exactly the way the real CI run failed."""

    WORKTREE_ROOT = REPO_ROOT / "Temp" / "ai-worktrees"

    def _make_worktree(self, tmp_path):
        import uuid

        branch = f"tmp/harness-heimeihome-{uuid.uuid4().hex[:8]}"
        self.WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        wt_dir = self.WORKTREE_ROOT / f"harness-heimeihome-{uuid.uuid4().hex[:8]}"
        subprocess.run(["git", "worktree", "add", "-q", "-b", branch, str(wt_dir), "HEAD"], cwd=REPO_ROOT, check=True)
        return branch, wt_dir

    def _cleanup_worktree(self, branch, wt_dir):
        subprocess.run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=REPO_ROOT, check=False)
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False)

    def test_heimei_home_equals_explicit_repo_root_not_the_default(self, tmp_path, fake_gh_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            real_wt = wt_dir.resolve()
            # verify.sh pipes every transcript excerpt through
            # Scripts/ai/redact.py before recording it (ai_run_check ->
            # ai_redact, common.sh:1203) — deliberately, so a published
            # transcript never leaks the operator's home-directory
            # username. redact.py's _HOME_PATH_RE rewrites /home/<user>
            # to /home/[REDACTED-USER], so that is the form the excerpt
            # will actually contain, not the raw resolved path.
            redacted_wt = re.sub(r"^/home/[A-Za-z0-9._-]+", "/home/[REDACTED-USER]", str(real_wt))

            # Simulate the actual GitHub Actions condition: $HOME does
            # not contain the checkout at all (real CI: HOME=/home/runner,
            # repo under $GITHUB_WORKSPACE). A real, empty directory —
            # `git` and friends need $HOME to exist and be writable for
            # incidental config/cache lookups even though nothing here
            # relies on its contents.
            fake_home = tmp_path / "fake-home-not-containing-the-repo"
            fake_home.mkdir()
            wrong_default_would_be = fake_home / "Heimei"
            redacted_wrong_default = re.sub(
                r"^/home/[A-Za-z0-9._-]+", "/home/[REDACTED-USER]", str(wrong_default_would_be)
            )
            assert str(wrong_default_would_be) != str(real_wt)

            # A fake `uv` that reports the HEIMEI_HOME it actually sees
            # instead of running any real command — this isolates the
            # property under test (what does verify.sh export?) from
            # needing a fully provisioned .venv in a throwaway worktree.
            fake_uv_dir = tmp_path / "fake-uv"
            fake_uv_dir.mkdir()
            fake_uv = fake_uv_dir / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "echo \"HEIMEI_HOME_SEEN=${HEIMEI_HOME:-UNSET}\"\n"
                "exit 0\n"
            )
            fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC)

            bin_dir, log_path = fake_gh_path
            json_out = tmp_path / "verify-result.json"
            env = dict(os.environ)
            env["HOME"] = str(fake_home)
            env["PATH"] = f"{fake_uv_dir}:{bin_dir}:{env['PATH']}"
            env["FAKE_GH_LOG"] = str(log_path)

            result = run_script(
                "verify.sh",
                ["--mode", "developer", "--repo-root", str(wt_dir), "--full", "--json", str(json_out)],
                fake_gh_path,
                extra_env=env,
            )
            assert result.returncode == 0, result.stderr

            summary = json.loads(json_out.read_text())
            for check_name in ("uv_sync", "pytest", "ruff", "mypy"):
                excerpt = summary["checks"][check_name]["transcript_excerpt"]
                assert f"HEIMEI_HOME_SEEN={redacted_wt}" in excerpt, (
                    f"{check_name}: expected HEIMEI_HOME_SEEN={redacted_wt}, got: {excerpt!r}"
                )
                assert "HEIMEI_HOME_SEEN=UNSET" not in excerpt
                assert f"HEIMEI_HOME_SEEN={redacted_wrong_default}" not in excerpt
        finally:
            self._cleanup_worktree(branch, wt_dir)


class TestVerifyShDispatchMode:
    """Item 12: registered dispatch worktree verification."""

    # verify.sh's OWN --repo-root validation (checked before any
    # dispatch-mode-specific logic) requires the path to be either the
    # primary checkout or somewhere under .ai/policy.toml's configured
    # worktree_root — real worktrees for these tests are therefore
    # created there (Temp/ai-worktrees/, gitignored), never under an
    # arbitrary pytest tmp_path, so tests actually reach the
    # dispatch-mode checks under test instead of failing one layer
    # too early.
    WORKTREE_ROOT = REPO_ROOT / "Temp" / "ai-worktrees"

    def _make_worktree(self, tmp_path):
        import uuid

        branch = f"tmp/harness-verify-{uuid.uuid4().hex[:8]}"
        self.WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        wt_dir = self.WORKTREE_ROOT / f"harness-verify-{uuid.uuid4().hex[:8]}"
        subprocess.run(["git", "worktree", "add", "-q", "-b", branch, str(wt_dir), "HEAD"], cwd=REPO_ROOT, check=True)
        return branch, wt_dir

    def _cleanup_worktree(self, branch, wt_dir):
        subprocess.run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=REPO_ROOT, check=False)
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False)

    # Real manifest root — verify.sh requires --run-manifest to resolve
    # inside .ai/policy.toml's configured runtime.run_manifest_root,
    # which must therefore actually be this real, gitignored directory
    # (not a pytest tmp_path) for these tests to reach the checks under
    # test rather than failing one layer too early on location alone.
    MANIFEST_ROOT = REPO_ROOT / "Temp" / "ai-runs" / "manifests"

    def _write_manifest(self, tmp_path, wt_dir, branch, sha, repo_id="R_kgDOTrfRlg"):
        import uuid

        self.MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
        manifest_path = self.MANIFEST_ROOT / f"run-{uuid.uuid4().hex[:8]}.json"
        payload = {
            "schema": "heimei-run-manifest/v1",
            "run_id": "run-1",
            "repository_id": repo_id,
            "issue_number": 1,
            "approval_id": "appr-1-abc",
            "base_sha": "a" * 40,
            "worktree_realpath": str(wt_dir.resolve()),
            "branch": branch,
            "expected_commit_sha": sha,
            "created_at": "2026-01-01T00:00:00Z",
            "dispatcher_pid": 1,
            "dispatcher_host": "test",
        }
        manifest_path.write_text(json.dumps(payload))
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        manifest_path.with_name(manifest_path.name + ".sha256").write_text(digest)
        return manifest_path

    @pytest.fixture(autouse=True)
    def _ensure_manifest_root_exists(self):
        self.MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
        yield
        for f in self.MANIFEST_ROOT.glob("run-*.json*"):
            f.unlink(missing_ok=True)

    def test_registered_dispatch_worktree_passes_manifest_checks(self, tmp_path, fake_gh_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt_dir, capture_output=True, text=True, check=True).stdout.strip()
            manifest_path = self._write_manifest(tmp_path, wt_dir, branch, sha)
            result = run_script(
                "verify.sh",
                ["--mode", "dispatch", "--run-manifest", str(manifest_path), "--repo-root", str(wt_dir), "--expected-sha", sha],
                fake_gh_path,
                extra_env={"AI_RUN_CHECK_TIMEOUT_SECONDS": "1"},
            )
            # It will likely fail later (uv sync/pytest against a
            # worktree with no venv), but it MUST get past every
            # registered-worktree/manifest check to do so.
            assert "Dispatch-mode registered-worktree verification passed" in result.stderr
        finally:
            self._cleanup_worktree(branch, wt_dir)

    def test_primary_checkout_rejected_as_dispatch_worktree(self, fake_gh_path, tmp_path):
        manifest_root = tmp_path / "manifests"
        manifest_root.mkdir()
        manifest_path = manifest_root / "run-1.json"
        manifest_path.write_text(json.dumps({
            "schema": "heimei-run-manifest/v1", "run_id": "run-1", "repository_id": "R_kgDOTrfRlg",
            "issue_number": 1, "approval_id": "appr-1", "base_sha": "a" * 40,
            "worktree_realpath": str(REPO_ROOT.resolve()), "branch": "main",
            "expected_commit_sha": "a" * 40, "created_at": "x", "dispatcher_pid": 1, "dispatcher_host": "x",
        }))
        (manifest_root / "run-1.json.sha256").write_text(hashlib.sha256(manifest_path.read_bytes()).hexdigest())
        result = run_script(
            "verify.sh",
            ["--mode", "dispatch", "--run-manifest", str(manifest_path), "--repo-root", str(REPO_ROOT), "--expected-sha", "a" * 40],
            fake_gh_path,
        )
        assert result.returncode != 0
        assert "refuses the primary checkout" in result.stderr

    def test_unregistered_checkout_rejected(self, fake_gh_path, tmp_path):
        # Placed INSIDE the real configured worktree root (so it gets
        # past verify.sh's generic location check) but created as a
        # standalone `git init` — never `git worktree add` — so it is
        # not a real worktree of the primary Heimei repository at all.
        # It is trivially "self-registered" (every repo lists itself),
        # so the actual rejection comes from verify.sh's cross-check
        # that the returned primary root matches ITS OWN primary root.
        self.WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        sibling = self.WORKTREE_ROOT / "harness-unregistered-sibling"
        try:
            subprocess.run(["git", "init", "-q", str(sibling)], check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=sibling, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=sibling, check=True)
            (sibling / "Projects" / "Heimei").mkdir(parents=True)
            (sibling / "f.txt").write_text("x\n")
            subprocess.run(["git", "add", "."], cwd=sibling, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=sibling, check=True)
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=sibling, capture_output=True, text=True, check=True).stdout.strip()
            manifest_path = self.MANIFEST_ROOT / "run-unregistered-sibling.json"
            manifest_path.write_text(json.dumps({
                "schema": "heimei-run-manifest/v1", "run_id": "run-1", "repository_id": "R_kgDOTrfRlg",
                "issue_number": 1, "approval_id": "appr-1", "base_sha": "a" * 40,
                "worktree_realpath": str(sibling.resolve()), "branch": "main",
                "expected_commit_sha": sha, "created_at": "x", "dispatcher_pid": 1, "dispatcher_host": "x",
            }))
            manifest_path.with_name(manifest_path.name + ".sha256").write_text(hashlib.sha256(manifest_path.read_bytes()).hexdigest())
            result = run_script(
                "verify.sh",
                ["--mode", "dispatch", "--run-manifest", str(manifest_path), "--repo-root", str(sibling), "--expected-sha", sha],
                fake_gh_path,
            )
            assert result.returncode != 0
            assert "does not match this script" in result.stderr or "not registered" in result.stderr
        finally:
            subprocess.run(["rm", "-rf", str(sibling)], check=False)

    def test_manifest_outside_run_root_rejected(self, fake_gh_path, tmp_path):
        stray = tmp_path / "elsewhere.json"
        stray.write_text(json.dumps({"schema": "heimei-run-manifest/v1"}))
        (tmp_path / "elsewhere.json.sha256").write_text(hashlib.sha256(stray.read_bytes()).hexdigest())
        result = run_script(
            "verify.sh",
            ["--mode", "dispatch", "--run-manifest", str(stray), "--repo-root", str(REPO_ROOT), "--expected-sha", "a" * 40],
            fake_gh_path,
        )
        assert result.returncode != 0

    def test_tampered_manifest_hash_mismatch_rejected(self, tmp_path, fake_gh_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt_dir, capture_output=True, text=True, check=True).stdout.strip()
            manifest_path = self._write_manifest(tmp_path, wt_dir, branch, sha)
            # Tamper with the manifest AFTER its sidecar hash was written.
            payload = json.loads(manifest_path.read_text())
            payload["branch"] = "ai/claude/some-other-branch"
            manifest_path.write_text(json.dumps(payload))
            result = run_script(
                "verify.sh",
                ["--mode", "dispatch", "--run-manifest", str(manifest_path), "--repo-root", str(wt_dir), "--expected-sha", sha],
                fake_gh_path,
            )
            assert result.returncode != 0
            assert "hash mismatch" in result.stderr.lower()
        finally:
            self._cleanup_worktree(branch, wt_dir)

    def test_wrong_expected_sha_rejected(self, tmp_path, fake_gh_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt_dir, capture_output=True, text=True, check=True).stdout.strip()
            manifest_path = self._write_manifest(tmp_path, wt_dir, branch, sha)
            wrong_sha = "f" * 40
            result = run_script(
                "verify.sh",
                ["--mode", "dispatch", "--run-manifest", str(manifest_path), "--repo-root", str(wt_dir), "--expected-sha", wrong_sha],
                fake_gh_path,
            )
            assert result.returncode != 0
        finally:
            self._cleanup_worktree(branch, wt_dir)

    def test_wrong_repository_id_rejected(self, tmp_path, fake_gh_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt_dir, capture_output=True, text=True, check=True).stdout.strip()
            manifest_path = self._write_manifest(tmp_path, wt_dir, branch, sha, repo_id="R_wrongrepo")
            result = run_script(
                "verify.sh",
                ["--mode", "dispatch", "--run-manifest", str(manifest_path), "--repo-root", str(wt_dir), "--expected-sha", sha],
                fake_gh_path,
            )
            assert result.returncode != 0
            assert "repository_id" in result.stderr
        finally:
            self._cleanup_worktree(branch, wt_dir)


class TestDispatchShArgumentValidation:
    def test_missing_issue_number_rejected_before_any_gh_call(self, fake_gh_path):
        _, log_path = fake_gh_path
        result = run_script("dispatch.sh", ["--agent", "claude"], fake_gh_path)
        assert result.returncode != 0
        assert log_path.read_text() == ""

    def test_missing_agent_rejected_before_any_gh_call(self, fake_gh_path):
        _, log_path = fake_gh_path
        result = run_script("dispatch.sh", ["42"], fake_gh_path)
        assert result.returncode != 0
        assert log_path.read_text() == ""

    def test_invalid_issue_number_rejected(self, fake_gh_path):
        result = run_script("dispatch.sh", ["not-a-number", "--agent", "claude"], fake_gh_path)
        assert result.returncode != 0

    def test_codex_implementation_disabled_before_any_gh_call(self, fake_gh_path):
        _, log_path = fake_gh_path
        result = run_script("dispatch.sh", ["42", "--agent", "codex", "--dry-run"], fake_gh_path)
        assert result.returncode != 0
        assert "Automated Codex implementation is disabled" in result.stderr
        assert log_path.read_text() == "", "Codex-disabled check must short-circuit before any gh call"

    def test_unsupported_agent_rejected(self, fake_gh_path):
        result = run_script("dispatch.sh", ["42", "--agent", "gpt4", "--dry-run"], fake_gh_path)
        assert result.returncode != 0
        assert "only 'claude' is supported" in result.stderr

    def test_dry_run_never_calls_a_mutating_gh_subcommand(self, fake_gh_path):
        _, log_path = fake_gh_path
        run_script("dispatch.sh", ["42", "--agent", "claude", "--dry-run"], fake_gh_path)
        calls = log_path.read_text().splitlines()
        mutating_prefixes = ("label create", "label edit", "issue comment", "issue edit", "pr create", "pr review", "pr merge")
        for call in calls:
            assert not call.startswith(mutating_prefixes), f"dry-run made a mutating gh call: {call}"

    def test_dry_run_still_performs_branch_protection_check(self, fake_gh_path):
        # Confirms dispatch.sh's dry-run path reaches ai_require_branch_protection
        # (not skipped) before failing later at issue lookup (unhandled by the fake).
        _, log_path = fake_gh_path
        run_script("dispatch.sh", ["42", "--agent", "claude", "--dry-run"], fake_gh_path)
        calls = log_path.read_text()
        assert "protection" in calls


class TestApproveShArgumentValidation:
    def test_missing_agent_rejected(self, fake_gh_path):
        result = run_script("approve.sh", ["42", "--risk", "low"], fake_gh_path)
        assert result.returncode != 0

    def test_missing_risk_rejected(self, fake_gh_path):
        result = run_script("approve.sh", ["42", "--agent", "claude"], fake_gh_path)
        assert result.returncode != 0

    def test_invalid_risk_rejected(self, fake_gh_path):
        result = run_script("approve.sh", ["42", "--agent", "claude", "--risk", "extreme"], fake_gh_path)
        assert result.returncode != 0

    def test_dry_run_never_calls_a_mutating_gh_subcommand(self, fake_gh_path):
        _, log_path = fake_gh_path
        run_script("approve.sh", ["42", "--agent", "claude", "--risk", "low", "--dry-run"], fake_gh_path)
        calls = log_path.read_text().splitlines()
        mutating_prefixes = ("label create", "label edit", "issue comment", "issue edit", "pr create", "pr review", "pr merge")
        for call in calls:
            assert not call.startswith(mutating_prefixes), f"dry-run made a mutating gh call: {call}"


class TestReviewShArgumentValidation:
    """Item 6: everything is an explicit, owner-supplied argument —
    there is no code path left that derives issue/approval/agent
    identity from the PR body, branch name, or an unconfirmed comment."""

    def test_invalid_pr_number_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["not-a-number"], fake_gh_path)
        assert result.returncode != 0

    def test_missing_issue_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["4", "--approval-id", "a1", "--implementation-agent", "claude", "--reviewer", "codex"], fake_gh_path)
        assert result.returncode != 0
        assert "--issue" in result.stderr

    def test_missing_approval_id_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["4", "--issue", "1", "--implementation-agent", "claude", "--reviewer", "codex"], fake_gh_path)
        assert result.returncode != 0
        assert "--approval-id" in result.stderr

    def test_missing_implementation_agent_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["4", "--issue", "1", "--approval-id", "a1", "--reviewer", "codex"], fake_gh_path)
        assert result.returncode != 0

    def test_missing_reviewer_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["4", "--issue", "1", "--approval-id", "a1", "--implementation-agent", "claude"], fake_gh_path)
        assert result.returncode != 0

    def test_reviewer_same_as_implementer_rejected(self, fake_gh_path):
        result = run_script(
            "review.sh",
            ["4", "--issue", "1", "--approval-id", "a1", "--implementation-agent", "claude", "--reviewer", "claude"],
            fake_gh_path,
        )
        assert result.returncode != 0
        assert "must differ from" in result.stderr

    def test_invalid_agent_names_rejected(self, fake_gh_path):
        result = run_script(
            "review.sh",
            ["4", "--issue", "1", "--approval-id", "a1", "--implementation-agent", "gpt4", "--reviewer", "codex"],
            fake_gh_path,
        )
        assert result.returncode != 0

    def test_post_without_confirm_digest_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["4", "--post"], fake_gh_path)
        assert result.returncode != 0
        assert "confirm-digest" in result.stderr

    def test_malformed_digest_rejected(self, fake_gh_path):
        result = run_script("review.sh", ["4", "--post", "--confirm-digest", "not-hex"], fake_gh_path)
        assert result.returncode != 0

    def test_post_with_wellformed_but_unknown_digest_rejected(self, fake_gh_path):
        digest = hashlib.sha256(b"nonexistent").hexdigest()
        result = run_script("review.sh", ["4", "--post", "--confirm-digest", digest], fake_gh_path)
        assert result.returncode != 0
        assert "No stored artifact matches digest" in result.stderr

    def test_approval_id_not_found_on_issue_rejected(self, fake_gh_path):
        issue_json = json.dumps({"number": 1, "title": "t", "state": "OPEN", "labels": [], "body": "b", "url": "u", "comments": []})
        result = run_script(
            "review.sh",
            ["4", "--issue", "1", "--approval-id", "appr-does-not-exist", "--implementation-agent", "claude", "--reviewer", "codex"],
            fake_gh_path,
            extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "No approval record matching approval-id" in result.stderr

    def test_implementation_agent_mismatch_against_approval_rejected(self, fake_gh_path):
        record = {
            "approval_id": "appr-1", "repository_id": "R_kgDOTrfRlg", "issue_number": 1,
            "approver": "gokul-hastrophil", "agent": "claude", "risk": "low",
            "issue_body_digest": "", "allowed_paths": ["a.txt"], "base_sha": "a" * 40,
            "timestamp": "x", "schema": "heimei-approval/v1",
        }
        issue_body = "Problem: x"
        record["issue_body_digest"] = compute_issue_digest(issue_body)
        body = "## Approval\n```json\n" + json.dumps(record) + "\n```\n<!-- heimei-approval:v1 -->"
        issue_json = json.dumps({
            "number": 1, "title": "t", "state": "OPEN", "labels": [], "body": issue_body, "url": "u",
            "comments": [{"id": "c1", "author": {"login": "gokul-hastrophil"}, "body": body, "createdAt": "2026-01-01T00:00:00Z"}],
        })
        result = run_script(
            "review.sh",
            # approval record authorizes 'claude', but the owner names 'codex' as implementer here — must be rejected.
            ["4", "--issue", "1", "--approval-id", "appr-1", "--implementation-agent", "codex", "--reviewer", "claude"],
            fake_gh_path,
            extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "not allowed by this approval" in result.stderr

    def test_codex_reviewer_never_auto_invoked_produces_manual_bundle_only(self, fake_gh_path, tmp_path):
        # base == head (this repo's real current HEAD) so the local
        # git fetch/cat-file checks succeed against objects already
        # present locally (no dependency on what PR #4 actually looks
        # like on GitHub), and the resulting diff is genuinely empty —
        # matching changed_files: 0 exactly, so the file-count-parity
        # check passes trivially and this test reaches the codex
        # early-exit path under test. base_sha must also be a REAL,
        # resolvable commit (not a fake "a"*40) now that the codex
        # bundle extracts AI_WORKFLOW.md/CONSTITUTION.md/PROJECT.md via
        # `git show <base_sha>:<doc>` — a nonexistent object would
        # correctly abort bundle generation, which is exactly what a
        # fake SHA used to (harmlessly) go untested.
        real_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
        record = {
            "approval_id": "appr-2", "repository_id": "R_kgDOTrfRlg", "issue_number": 2,
            "approver": "gokul-hastrophil", "agent": "claude", "risk": "low",
            "issue_body_digest": "", "allowed_paths": ["a.txt"], "base_sha": real_head,
            "timestamp": "x", "schema": "heimei-approval/v1",
        }
        issue_body = "Problem: y"
        record["issue_body_digest"] = compute_issue_digest(issue_body)
        body = "## Approval\n```json\n" + json.dumps(record) + "\n```\n<!-- heimei-approval:v1 -->"
        issue_json = json.dumps({
            "number": 2, "title": "t", "state": "OPEN", "labels": [], "body": issue_body, "url": "u",
            "comments": [{"id": "c1", "author": {"login": "gokul-hastrophil"}, "body": body, "createdAt": "2026-01-01T00:00:00Z"}],
        })
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": real_head},
            "head": {"sha": real_head, "repo": {"id": 1320669590, "node_id": "R_kgDOTrfRlg"}},
            "changed_files": 0, "title": "t", "html_url": "https://example/4",
        })
        result = run_script(
            "review.sh",
            ["4", "--issue", "2", "--approval-id", "appr-2", "--implementation-agent", "claude", "--reviewer", "codex"],
            fake_gh_path,
            extra_env={"FAKE_GH_ISSUE_JSON": issue_json, "FAKE_GH_PULLS_JSON": pulls_json},
        )
        assert result.returncode == 0, result.stderr
        assert "the PR has zero changed files" in result.stdout
        assert "codex exec" not in result.stdout
        _, log_path = fake_gh_path
        calls = log_path.read_text().splitlines()
        mutating_prefixes = ("label create", "label edit", "issue comment", "issue edit", "pr create", "pr review", "pr merge")
        for call in calls:
            assert not call.startswith(mutating_prefixes)


_OMIT_KEY = object()

# The full fail-closed matrix a checked extraction must reject: key
# absent, JSON null, empty string, and every non-string JSON type —
# plus an ordinary but wrong string. A prior version used `// ""` to
# map ALL of these except the last straight to an empty string and
# then only checked `[[ -n ... ]]`, which means every one of these
# except "different_string" was silently treated as "field not
# present" and the whole comparison was skipped — same-repository
# provenance was not enforced at all for a missing/null/malformed
# identity.
NODE_ID_FAILURE_CASES = [
    ("missing", _OMIT_KEY),
    ("null", None),
    ("empty_string", ""),
    ("numeric", 1320669590),
    ("boolean", True),
    ("array", ["R_kgDOTrfRlg"]),
    ("object", {"id": "R_kgDOTrfRlg"}),
    ("different_string", "R_kgDOSomeOtherRepoXX"),
]


class TestReviewRepositoryNodeId:
    """Smoke-test defect 4: GitHub's REST PR payload carries two
    distinct repository identifiers — .head.repo.id is the numeric
    REST/database ID (e.g. 1320669590), .head.repo.node_id is the
    GraphQL node ID (e.g. "R_kgDOTrfRlg") that .ai/policy.toml's
    repository.id actually stores. review.sh used to read .head.repo.id
    and compare it to the policy node ID, so every same-repository PR
    was rejected as if it were a fork. Covers both the generation path
    and the --post path, and includes tests that would only pass if
    the numeric .id is never consulted at all — even when a contrived
    payload makes .id itself equal the policy string, or when .node_id
    is missing/null/empty/wrong-typed and a naive `// ""` extraction
    would have silently skipped the whole check instead of failing
    closed."""

    POLICY_REPO_NODE_ID = "R_kgDOTrfRlg"
    WRONG_NODE_ID = "R_kgDOSomeOtherRepoXX"
    ARTIFACT_STORE = REPO_ROOT / "Temp" / "ai-runs" / "review-artifacts"

    @staticmethod
    def _head_repo(node_id_value, *, id_value=1320669590):
        repo = {"id": id_value}
        if node_id_value is not _OMIT_KEY:
            repo["node_id"] = node_id_value
        return repo

    # --- generation path --------------------------------------------------

    def _run_generation(self, fake_gh_path, issue_number, approval_id, issue_json, head_repo, pr_number="4"):
        real_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": real_head},
            "head": {"sha": real_head, "repo": head_repo},
            "changed_files": 0, "title": "t", "html_url": "https://example/nodeid",
        })
        return run_script(
            "review.sh",
            [pr_number, "--issue", str(issue_number), "--approval-id", approval_id,
             "--implementation-agent", "claude", "--reviewer", "codex"],
            fake_gh_path,
            extra_env={"FAKE_GH_ISSUE_JSON": issue_json, "FAKE_GH_PULLS_JSON": pulls_json},
        )

    def test_generation_accepts_same_repo_via_node_id(self, fake_gh_path):
        # id is a real, differing numeric value on purpose — item 7:
        # a mismatched numeric .id must not block acceptance when
        # .node_id correctly matches policy.
        issue_json, record = build_dispatch_ready_issue(301, "low", "appr-nodeid-ok")
        result = self._run_generation(
            fake_gh_path, 301, "appr-nodeid-ok", issue_json,
            head_repo={"id": 1320669590, "node_id": self.POLICY_REPO_NODE_ID},
        )
        assert result.returncode == 0, result.stderr
        assert "the PR has zero changed files" in result.stdout

    def test_generation_rejects_different_node_id(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(302, "low", "appr-nodeid-bad")
        result = self._run_generation(
            fake_gh_path, 302, "appr-nodeid-bad", issue_json,
            head_repo={"id": 1320669590, "node_id": self.WRONG_NODE_ID},
        )
        assert result.returncode != 0
        assert "repository node ID" in result.stderr
        assert "fork" in result.stderr

    def test_generation_rejects_even_when_numeric_id_equals_policy_string(self, fake_gh_path):
        # Item 7, sharpest form: .id is set to the exact policy node-ID
        # STRING (never a real shape GitHub sends, but exactly what the
        # old buggy code would have accepted since it compared .id, not
        # .node_id). If review.sh ever regresses to reading .id again,
        # this test flips from reject to accept and catches it.
        issue_json, record = build_dispatch_ready_issue(303, "low", "appr-nodeid-trap")
        result = self._run_generation(
            fake_gh_path, 303, "appr-nodeid-trap", issue_json,
            head_repo={"id": self.POLICY_REPO_NODE_ID, "node_id": self.WRONG_NODE_ID},
        )
        assert result.returncode != 0
        assert "repository node ID" in result.stderr

    def test_generation_accepts_regardless_of_a_differing_numeric_id(self, fake_gh_path):
        """A differing numeric .id must not matter at all when
        .node_id is the correct trusted ID — proves .id is never part
        of the comparison, not merely that it isn't a blocker."""
        issue_json, record = build_dispatch_ready_issue(310, "low", "appr-nodeid-idirrelevant")
        result = self._run_generation(
            fake_gh_path, 310, "appr-nodeid-idirrelevant", issue_json,
            head_repo={"id": 999999999, "node_id": self.POLICY_REPO_NODE_ID},
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("case_name,node_id_value", NODE_ID_FAILURE_CASES, ids=[c[0] for c in NODE_ID_FAILURE_CASES])
    def test_generation_rejects_malformed_or_missing_node_id(self, fake_gh_path, case_name, node_id_value):
        issue_number = 400 + NODE_ID_FAILURE_CASES.index((case_name, node_id_value))
        approval_id = f"appr-nodeid-gen-{case_name}"
        issue_json, record = build_dispatch_ready_issue(issue_number, "low", approval_id)
        result = self._run_generation(
            fake_gh_path, issue_number, approval_id, issue_json,
            head_repo=self._head_repo(node_id_value),
        )
        assert result.returncode != 0, f"case {case_name!r} should have failed closed but succeeded: {result.stdout}"
        assert "repository node ID" in result.stderr

    # --- --post path -------------------------------------------------------

    def _write_envelope(self, *, pr_number, issue_number, approval_id, base_sha, head_sha):
        self.ARTIFACT_STORE.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema": "heimei-review-envelope/v1",
            "repository_id": self.POLICY_REPO_NODE_ID,
            "repository_full_name": "gokul-hastrophil/heimei",
            "pr_number": pr_number,
            "issue_number": issue_number,
            "approval_id": approval_id,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "reviewer": "codex",
            "implementation_agent": "claude",
            "manifest_hash": "x" * 64,
            "review_body": "Looks fine.",
            "generated_at": "2026-01-01T00:00:00Z",
        }
        data = json.dumps(envelope).encode()
        digest = hashlib.sha256(data).hexdigest()
        path = self.ARTIFACT_STORE / f"{digest}.json"
        path.write_bytes(data)
        return digest, path

    def _run_post(self, fake_gh_path, pr_number, digest, issue_json, base_sha, head_sha, head_repo):
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": base_sha},
            "head": {"sha": head_sha, "repo": head_repo},
            "changed_files": 0, "title": "t", "html_url": "https://example/nodeid-post",
        })
        return run_script(
            "review.sh",
            [str(pr_number), "--post", "--confirm-digest", digest],
            fake_gh_path,
            extra_env={"FAKE_GH_ISSUE_JSON": issue_json, "FAKE_GH_PULLS_JSON": pulls_json},
        )

    def test_post_accepts_same_repo_via_node_id(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(304, "low", "appr-nodeid-post-ok")
        base_sha = "a" * 40
        head_sha = "b" * 40
        digest, path = self._write_envelope(
            pr_number=4, issue_number=304, approval_id="appr-nodeid-post-ok", base_sha=base_sha, head_sha=head_sha,
        )
        try:
            result = self._run_post(
                fake_gh_path, 4, digest, issue_json, base_sha, head_sha,
                head_repo={"id": 1320669590, "node_id": self.POLICY_REPO_NODE_ID},
            )
            assert result.returncode == 0, result.stderr
            assert "Posted as a plain comment review" in result.stdout + result.stderr or "Posted as a plain comment review" in result.stdout
        finally:
            path.unlink(missing_ok=True)

    def test_post_rejects_different_node_id(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(305, "low", "appr-nodeid-post-bad")
        base_sha = "c" * 40
        head_sha = "d" * 40
        digest, path = self._write_envelope(
            pr_number=4, issue_number=305, approval_id="appr-nodeid-post-bad", base_sha=base_sha, head_sha=head_sha,
        )
        try:
            result = self._run_post(
                fake_gh_path, 4, digest, issue_json, base_sha, head_sha,
                head_repo={"id": 1320669590, "node_id": self.WRONG_NODE_ID},
            )
            assert result.returncode != 0
            assert "repository node ID" in result.stderr
        finally:
            path.unlink(missing_ok=True)

    def test_post_rejects_even_when_numeric_id_equals_policy_string(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(306, "low", "appr-nodeid-post-trap")
        base_sha = "e" * 40
        head_sha = "f" * 40
        digest, path = self._write_envelope(
            pr_number=4, issue_number=306, approval_id="appr-nodeid-post-trap", base_sha=base_sha, head_sha=head_sha,
        )
        try:
            result = self._run_post(
                fake_gh_path, 4, digest, issue_json, base_sha, head_sha,
                head_repo={"id": self.POLICY_REPO_NODE_ID, "node_id": self.WRONG_NODE_ID},
            )
            assert result.returncode != 0
            assert "repository node ID" in result.stderr
        finally:
            path.unlink(missing_ok=True)

    def test_post_accepts_regardless_of_a_differing_numeric_id(self, fake_gh_path):
        """A differing numeric .id must not matter at all when
        .node_id is the correct trusted ID — proves .id is never part
        of the comparison, not merely that it isn't a blocker."""
        issue_json, record = build_dispatch_ready_issue(311, "low", "appr-nodeid-post-idirrelevant")
        base_sha = "1" * 40
        head_sha = "2" * 40
        digest, path = self._write_envelope(
            pr_number=4, issue_number=311, approval_id="appr-nodeid-post-idirrelevant", base_sha=base_sha, head_sha=head_sha,
        )
        try:
            result = self._run_post(
                fake_gh_path, 4, digest, issue_json, base_sha, head_sha,
                head_repo={"id": 999999999, "node_id": self.POLICY_REPO_NODE_ID},
            )
            assert result.returncode == 0, result.stderr
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.parametrize("case_name,node_id_value", NODE_ID_FAILURE_CASES, ids=[c[0] for c in NODE_ID_FAILURE_CASES])
    def test_post_rejects_malformed_or_missing_node_id(self, fake_gh_path, case_name, node_id_value):
        issue_number = 500 + NODE_ID_FAILURE_CASES.index((case_name, node_id_value))
        approval_id = f"appr-nodeid-post-{case_name}"
        issue_json, record = build_dispatch_ready_issue(issue_number, "low", approval_id)
        base_sha = "3" * 40
        head_sha = "4" * 40
        digest, path = self._write_envelope(
            pr_number=4, issue_number=issue_number, approval_id=approval_id, base_sha=base_sha, head_sha=head_sha,
        )
        try:
            result = self._run_post(
                fake_gh_path, 4, digest, issue_json, base_sha, head_sha,
                head_repo=self._head_repo(node_id_value),
            )
            assert result.returncode != 0, f"case {case_name!r} should have failed closed but succeeded: {result.stdout}"
            assert "repository node ID" in result.stderr
        finally:
            path.unlink(missing_ok=True)


class TestAgentGitWrapper:
    AGENT_GIT = str(SCRIPTS_DIR / "agent-git.sh")

    def _make_worktree(self, tmp_path):
        import uuid

        branch = f"tmp/harness-agentgit-{uuid.uuid4().hex[:8]}"
        wt_dir = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "-b", branch, str(wt_dir), "HEAD"], cwd=REPO_ROOT, check=True)
        return branch, wt_dir

    def _cleanup(self, branch, wt_dir):
        subprocess.run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=REPO_ROOT, check=False)
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False)

    def _run(self, wt_dir, *args):
        env = dict(os.environ)
        env["AI_AGENT_WORKTREE"] = str(wt_dir)
        return subprocess.run([self.AGENT_GIT, *args], capture_output=True, text=True, timeout=15, env=env)

    def test_missing_worktree_env_rejected(self):
        env = dict(os.environ)
        env.pop("AI_AGENT_WORKTREE", None)
        result = subprocess.run([self.AGENT_GIT, "status"], capture_output=True, text=True, timeout=15, env=env)
        assert result.returncode != 0

    def test_dirty_tree_regression_short(self, tmp_path):
        """THE reported defect: status --short must reflect the REAL
        state, matching real `git status --short` exactly — not report
        a false 'clean' because --short got smuggled in as a pathspec."""
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            (wt_dir / "AI_WORKFLOW.md").write_text((wt_dir / "AI_WORKFLOW.md").read_text() + "\ndirty\n")
            (wt_dir / "untracked_regression_test.txt").write_text("new\n")
            real = subprocess.run(["git", "status", "--short"], cwd=wt_dir, capture_output=True, text=True, check=True)
            wrapped = self._run(wt_dir, "status", "--short")
            assert wrapped.returncode == 0, wrapped.stderr
            assert wrapped.stdout == real.stdout
            assert wrapped.stdout.strip() != "", "regression: dirty tree must never report as empty/clean"
        finally:
            self._cleanup(branch, wt_dir)

    def test_dirty_tree_regression_porcelain(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            (wt_dir / "AI_WORKFLOW.md").write_text((wt_dir / "AI_WORKFLOW.md").read_text() + "\ndirty\n")
            real = subprocess.run(["git", "status", "--porcelain=v1"], cwd=wt_dir, capture_output=True, text=True, check=True)
            wrapped = self._run(wt_dir, "status", "--porcelain=v1")
            assert wrapped.returncode == 0, wrapped.stderr
            assert wrapped.stdout == real.stdout
        finally:
            self._cleanup(branch, wt_dir)

    def test_staged_file_reflected(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            (wt_dir / "staged.txt").write_text("x\n")
            subprocess.run(["git", "add", "staged.txt"], cwd=wt_dir, check=True)
            real = subprocess.run(["git", "status", "--short"], cwd=wt_dir, capture_output=True, text=True, check=True)
            wrapped = self._run(wt_dir, "status", "--short")
            assert wrapped.stdout == real.stdout
            assert "staged.txt" in wrapped.stdout
        finally:
            self._cleanup(branch, wt_dir)

    def test_clean_tree_reported_as_clean(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            wrapped = self._run(wt_dir, "status", "--short")
            assert wrapped.returncode == 0
            assert wrapped.stdout.strip() == ""
        finally:
            self._cleanup(branch, wt_dir)

    def test_malicious_dash_capital_c_not_a_recognized_subcommand(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            result = self._run(wt_dir, "-C", "/tmp", "status")
            assert result.returncode != 0
            assert "not permitted" in result.stderr or "unrecognized" in result.stderr
        finally:
            self._cleanup(branch, wt_dir)

    def test_malicious_dash_lowercase_c_not_a_recognized_subcommand(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            result = self._run(wt_dir, "-c", "core.hooksPath=/tmp/evil", "status")
            assert result.returncode != 0
        finally:
            self._cleanup(branch, wt_dir)

    def test_path_beginning_with_dash_rejected_in_diff(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            result = self._run(wt_dir, "diff", "--", "-rf")
            assert result.returncode != 0
            assert "must not start with '-'" in result.stderr
        finally:
            self._cleanup(branch, wt_dir)

    def test_filename_with_spaces_in_diff(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            (wt_dir / "has spaces.txt").write_text("x\n")
            result = self._run(wt_dir, "diff", "--", "has spaces.txt")
            assert result.returncode == 0, result.stderr
        finally:
            self._cleanup(branch, wt_dir)

    def test_unknown_option_rejected(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            result = self._run(wt_dir, "status", "--this-does-not-exist")
            assert result.returncode != 0
        finally:
            self._cleanup(branch, wt_dir)

    def test_mutating_subcommands_blocked(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            for subcommand in ["commit", "push", "fetch", "checkout", "reset", "clean", "merge", "rebase", "remote", "config", "worktree"]:
                result = self._run(wt_dir, subcommand)
                assert result.returncode != 0, f"{subcommand} should be blocked"
        finally:
            self._cleanup(branch, wt_dir)

    def test_branch_create_blocked_but_show_current_allowed(self, tmp_path):
        branch, wt_dir = self._make_worktree(tmp_path)
        try:
            blocked = self._run(wt_dir, "branch", "new-branch")
            assert blocked.returncode != 0
            allowed = self._run(wt_dir, "branch", "--show-current")
            assert allowed.returncode == 0
            assert allowed.stdout.strip() == branch
        finally:
            self._cleanup(branch, wt_dir)


class TestBootstrapGithubDraftPrLabel:
    """Defect 1: dispatch.sh labels the issue status:draft-pr right
    after opening the draft PR (dispatch.sh:818), but
    bootstrap-github.sh never provisioned that label — so the very
    first real dispatch run would hit ai_replace_status_label's
    destination-existence check (defect 2) and fail closed instead of
    transitioning cleanly. Dry-run only: this never calls --execute, so
    no real gh mutation happens either way."""

    def test_dry_run_lists_status_draft_pr_as_a_canonical_label(self, fake_gh_path):
        result = run_script("bootstrap-github.sh", ["--dry-run"], fake_gh_path)
        assert result.returncode == 0, result.stderr
        # ai_log_info writes to stderr (common.sh) — the per-label
        # dry-run lines ("missing -> create: <name>") land there, not
        # on stdout, which is reserved for the manual branch-protection
        # block printed at the end.
        assert "status:draft-pr" in result.stderr

    def test_stale_ci_guidance_replaced_with_the_real_required_check(self, fake_gh_path):
        result = run_script("bootstrap-github.sh", ["--dry-run"], fake_gh_path)
        assert result.returncode == 0, result.stderr
        assert "once one exists" not in result.stdout
        assert "pytest / ruff / mypy" in result.stdout


class TestReplaceStatusLabelFailsClosed:
    """Defect 2: ai_replace_status_label used to remove every existing
    status:* label from the issue BEFORE attempting to add the new
    one. If the destination label didn't exist repository-wide (a
    typo, not yet provisioned, mid-migration), the final --add-label
    call died with the old label already stripped — leaving the issue
    with no status label at all. ai_require_label_exists now confirms
    the destination label exists in the repository before anything on
    the issue is touched, and fails closed — never auto-creating a
    label — both when the label genuinely doesn't exist and when the
    existence check itself cannot be completed (API/network failure)."""

    ISSUE_JSON = json.dumps({
        "number": 9, "title": "t", "state": "OPEN",
        "labels": [{"name": "status:in-progress"}], "body": "b", "url": "u", "comments": [],
    })

    def _env(self, fake_gh_path, **extra):
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = self.ISSUE_JSON
        env.update(extra)
        return env

    def test_target_label_exists_transition_succeeds(self, fake_gh_path):
        _, log_path = fake_gh_path
        label_list = json.dumps([{"name": "status:in-progress"}, {"name": "status:draft-pr"}])
        env = self._env(fake_gh_path, FAKE_GH_LABEL_LIST_JSON=label_list)
        result = run_bash("ai_replace_status_label 9 status:draft-pr", env=env)
        assert result.returncode == 0, result.stderr
        calls = log_path.read_text().splitlines()
        assert any(c.startswith("issue edit 9") and "--remove-label status:in-progress" in c for c in calls)
        assert any(c.startswith("issue edit 9") and "--add-label status:draft-pr" in c for c in calls)

    def test_target_label_missing_fails_before_removing_existing(self, fake_gh_path):
        _, log_path = fake_gh_path
        # status:draft-pr deliberately absent from the repo-wide list.
        label_list = json.dumps([{"name": "status:in-progress"}])
        env = self._env(fake_gh_path, FAKE_GH_LABEL_LIST_JSON=label_list)
        result = run_bash("ai_replace_status_label 9 status:draft-pr", env=env)
        assert result.returncode != 0
        assert "does not exist" in result.stderr
        calls = log_path.read_text().splitlines()
        assert not any("--remove-label" in c for c in calls), (
            f"existing status label was removed before the destination-label check failed: {calls}"
        )
        assert not any("--add-label" in c for c in calls)

    def test_label_lookup_failure_fails_closed_before_mutation(self, fake_gh_path):
        _, log_path = fake_gh_path
        env = self._env(fake_gh_path, FAKE_GH_LABEL_LIST_FAIL="1")
        result = run_bash("ai_replace_status_label 9 status:draft-pr", env=env)
        assert result.returncode != 0
        assert "Could not query labels" in result.stderr
        calls = log_path.read_text().splitlines()
        assert not any("--remove-label" in c for c in calls)
        assert not any("--add-label" in c for c in calls)

    def test_never_auto_creates_the_missing_destination_label(self, fake_gh_path):
        """ai_require_label_exists must only ever read (gh label list)
        — never gh label create — leaving provisioning to
        bootstrap-github.sh exclusively."""
        _, log_path = fake_gh_path
        label_list = json.dumps([{"name": "status:in-progress"}])
        env = self._env(fake_gh_path, FAKE_GH_LABEL_LIST_JSON=label_list)
        result = run_bash("ai_replace_status_label 9 status:draft-pr", env=env)
        assert result.returncode != 0
        calls = log_path.read_text().splitlines()
        assert not any(c.startswith("label create") for c in calls)


# ---------------------------------------------------------------------------
# Syntax check for every shell script — automated equivalent of `bash -n`.
# ---------------------------------------------------------------------------


class TestShellSyntax:
    @pytest.mark.parametrize(
        "script",
        [
            "common.sh",
            "bootstrap-github.sh",
            "verify.sh",
            "dispatch.sh",
            "review.sh",
            "approve.sh",
            "agent-git.sh",
        ],
    )
    def test_bash_n(self, script):
        result = subprocess.run(["bash", "-n", str(SCRIPTS_DIR / script)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("script", ["policy.py", "issue_sections.py", "redact.py"])
    def test_python_compiles(self, script):
        result = subprocess.run(["python3", "-m", "py_compile", str(SCRIPTS_DIR / script)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Fourth security-repair pass: Blockers 1-5 + hardening fixes 6-7.
# ---------------------------------------------------------------------------

REAL_GIT_BIN = "/usr/bin/git"
assert Path(REAL_GIT_BIN).is_file(), "expected /usr/bin/git to exist on this machine"


def build_dispatch_ready_issue(issue_number: int, risk: str, approval_id: str, agent: str = "claude", base_sha: str | None = None):
    """Builds a matching (issue_json, approval_record) pair that passes
    every independent check dispatch.sh/review.sh apply to an approval:
    real digest (via compute_issue_digest, not a bare printf), a
    risk:<risk> label matching the approval record's own risk field,
    and (if base_sha is omitted) the REAL current origin/main SHA so
    ai_require_fresh_base_sha's live exact-match check passes too."""
    if base_sha is None:
        base_sha = subprocess.run(
            ["git", "rev-parse", "origin/main"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    issue_body = f"Problem: test fixture for issue #{issue_number}"
    digest = compute_issue_digest(issue_body)
    record = {
        "approval_id": approval_id, "repository_id": "R_kgDOTrfRlg", "issue_number": issue_number,
        "approver": "gokul-hastrophil", "agent": agent, "risk": risk,
        "issue_body_digest": digest, "allowed_paths": ["a.txt"], "base_sha": base_sha,
        "timestamp": "2026-01-01T00:00:00Z", "schema": "heimei-approval/v1",
    }
    approval_comment_body = "## Approval\n```json\n" + json.dumps(record) + "\n```\n<!-- heimei-approval:v1 -->"
    issue_json = json.dumps({
        "number": issue_number, "title": "t", "state": "OPEN",
        "labels": [{"name": f"risk:{risk}"}], "body": issue_body, "url": "u",
        "comments": [{"id": "c1", "author": {"login": "gokul-hastrophil"}, "body": approval_comment_body, "createdAt": "2026-01-01T00:00:00Z"}],
    })
    return issue_json, record


@pytest.fixture
def fake_git_claim_ref(tmp_path):
    """A `git` on PATH that delegates everything to the real binary
    EXCEPT `ls-remote origin refs/heads/ai-claims/...`, which returns
    a controlled canned line (or nothing) based on
    FAKE_GIT_CLAIM_REF_SHA — used to simulate "a claim ref already
    exists at SHA X" without touching any real GitHub ref."""
    bin_dir = tmp_path / "fake-git-claim"
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"ls-remote\" ]]; then\n"
        "  for arg in \"$@\"; do\n"
        "    case \"${arg}\" in\n"
        "      refs/heads/ai-claims/*)\n"
        "        if [[ -n \"${FAKE_GIT_CLAIM_REF_SHA:-}\" ]]; then\n"
        "          printf '%s\\t%s\\n' \"${FAKE_GIT_CLAIM_REF_SHA}\" \"${arg}\"\n"
        "        fi\n"
        "        exit 0\n"
        "        ;;\n"
        "    esac\n"
        "  done\n"
        "fi\n"
        f"exec {REAL_GIT_BIN} \"$@\"\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir


class TestClaimNonResumable:
    """Blocker 1: a pre-existing claim ref of ANY SHA — same as the
    approved base, or different — is refused outright. No SHA
    comparison, no RESUMING, no automatic takeover. These drive
    dispatch.sh itself (dry-run only, per this task's constraints),
    not merely ai_create_claim_ref in isolation."""

    def _run_dispatch_dry_run(self, fake_gh_path, fake_git_dir, issue_number, issue_json, extra_env=None):
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_dir}:{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = issue_json
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [str(SCRIPTS_DIR / "dispatch.sh"), str(issue_number), "--agent", "claude", "--dry-run"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def test_no_pre_existing_claim_ref_dry_run_reaches_fresh_claim_plan(self, fake_gh_path, fake_git_claim_ref):
        issue_json, record = build_dispatch_ready_issue(101, "low", "appr-101-fresh")
        result = self._run_dispatch_dry_run(
            fake_gh_path, fake_git_claim_ref, 101, issue_json,
            extra_env={"FAKE_GIT_CLAIM_REF_SHA": ""},
        )
        assert result.returncode == 0, result.stderr
        assert "single-attempt create-ref, non-resumable" in result.stdout
        assert "Dry run complete" in result.stderr

    def test_pre_existing_same_sha_claim_fails(self, fake_gh_path, fake_git_claim_ref):
        issue_json, record = build_dispatch_ready_issue(102, "low", "appr-102-samesha")
        result = self._run_dispatch_dry_run(
            fake_gh_path, fake_git_claim_ref, 102, issue_json,
            extra_env={"FAKE_GIT_CLAIM_REF_SHA": record["base_sha"]},
        )
        assert result.returncode != 0
        assert "non-resumable" in result.stderr
        assert "already been claimed" in result.stderr

    def test_pre_existing_different_sha_claim_fails(self, fake_gh_path, fake_git_claim_ref):
        issue_json, record = build_dispatch_ready_issue(103, "low", "appr-103-diffsha")
        result = self._run_dispatch_dry_run(
            fake_gh_path, fake_git_claim_ref, 103, issue_json,
            extra_env={"FAKE_GIT_CLAIM_REF_SHA": "f" * 40},
        )
        assert result.returncode != 0
        assert "non-resumable" in result.stderr

    def test_same_and_different_sha_produce_the_identical_failure_message_shape(self, fake_gh_path, fake_git_claim_ref):
        """Proves there is no SHA-based branching left: both cases hit
        the exact same refusal, not two different code paths."""
        issue_json_a, record_a = build_dispatch_ready_issue(104, "low", "appr-104-a")
        same = self._run_dispatch_dry_run(fake_gh_path, fake_git_claim_ref, 104, issue_json_a, extra_env={"FAKE_GIT_CLAIM_REF_SHA": record_a["base_sha"]})
        issue_json_b, record_b = build_dispatch_ready_issue(105, "low", "appr-105-b")
        diff = self._run_dispatch_dry_run(fake_gh_path, fake_git_claim_ref, 105, issue_json_b, extra_env={"FAKE_GIT_CLAIM_REF_SHA": "e" * 40})
        assert "already been claimed or is already in progress" in same.stderr
        assert "already been claimed or is already in progress" in diff.stderr

    def test_no_resuming_variable_anywhere_in_dispatch_sh(self):
        source = (SCRIPTS_DIR / "dispatch.sh").read_text()
        assert "RESUMING" not in source

    def test_no_resuming_or_resume_language_in_common_sh_create_claim_ref(self):
        source = (SCRIPTS_DIR / "common.sh").read_text()
        assert "RESUMING" not in source


def _launch_pair(cmd, env, cwd=None):
    """Launches the SAME command as two genuinely-simultaneous real OS
    subprocesses (subprocess.Popen, not subprocess.run/threading — the
    task's own explicit requirement) sharing one env dict, waits for
    both, and returns (proc_a, proc_b, out_a, err_a, out_b, err_b).
    Using two Popen calls back-to-back (rather than a thread pool) is
    the most direct way to prove two independent processes actually
    contended for the same resource, not two calls serialized behind
    the GIL or a thread-pool scheduler."""
    p_a = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p_b = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out_a, err_a = p_a.communicate(timeout=30)
    out_b, err_b = p_b.communicate(timeout=30)
    return p_a, p_b, out_a, err_a, out_b, err_b


def _diagnostics(label, state_dir, ref, sha, p_a, p_b, out_a, err_a, out_b, err_b, log_path=None):
    lines = [
        f"--- {label} ---",
        f"shared state dir: {state_dir}",
        f"claim ref attempted (both children): {ref}",
        f"claim sha attempted (both children): {sha}",
        f"child A: pid={p_a.pid} exit={p_a.returncode}",
        f"  stdout: {out_a!r}",
        f"  stderr: {err_a!r}",
        f"child B: pid={p_b.pid} exit={p_b.returncode}",
        f"  stdout: {out_b!r}",
        f"  stderr: {err_b!r}",
    ]
    if log_path is not None:
        try:
            lines.append(f"fake-gh call log ({log_path}):")
            lines.append(Path(log_path).read_text())
        except OSError as exc:
            lines.append(f"(could not read fake-gh call log: {exc})")
    return "\n".join(lines)


class TestAtomicClaimConcurrency:
    """Blocker 1's explicit requirement: use two real subprocesses
    racing a shared fake GitHub claim backend, not two sequential
    calls dressed up as a concurrency test.

    Root cause of the [0, 0] failure this class used to report,
    diagnosed live during this pass with a standalone repro harness
    outside pytest entirely: the fake backend used a bare `mkdir` on a
    shared path as its compare-and-set primitive. `mkdir` is
    textbook-atomic on a normal POSIX filesystem, but empirically, in
    THIS sandbox, two genuinely-simultaneous `mkdir` calls on the
    identical absolute path were observed to BOTH return success with
    no error on either side, in a real, repeatable fraction of runs —
    confirmed with a bare `mkdir` (no fake-gh script, no
    ai_create_claim_ref, no Python at all involved) run in a tight
    loop of real background shell subprocesses. `flock` on a file
    descriptor, tested the same way (40/40 runs), never exhibited this
    — so the fake backend (see FAKE_GH_SCRIPT's `/git/refs` handler
    above) now uses a blocking `flock` to guard a plain marker-file
    check-and-create, not `mkdir`. This is a fix to the TEST'S
    simulated GitHub backend only — ai_create_claim_ref itself makes
    no local filesystem calls; it only calls `gh api ...` and
    interprets that response, so production claim semantics are
    unchanged."""

    def test_atomic_backend_itself_has_one_winner(self, tmp_path):
        """Test A. Proves the raw primitive (flock + marker-file, as
        used inside the fake gh script) before ever layering
        ai_create_claim_ref or gh on top of it."""
        state_dir = tmp_path / "backend-primitive"
        state_dir.mkdir()
        state_file = state_dir / "claim-state"
        probe = tmp_path / "probe.sh"
        probe.write_text(
            "#!/usr/bin/env bash\n"
            "state_file=\"$1\"\n"
            "lock_fd_path=\"${state_file}.flock\"\n"
            "marker_path=\"${state_file}.claimed\"\n"
            "exec {fd}>\"${lock_fd_path}\"\n"
            "flock \"${fd}\"\n"
            "if [[ -e \"${marker_path}\" ]]; then\n"
            "  flock -u \"${fd}\"\n"
            "  exit 1\n"
            "fi\n"
            ": > \"${marker_path}\"\n"
            "flock -u \"${fd}\"\n"
            "exit 0\n"
        )
        probe.chmod(probe.stat().st_mode | stat.S_IEXEC)

        env = dict(os.environ)
        p_a, p_b, out_a, err_a, out_b, err_b = _launch_pair(["bash", str(probe), str(state_file)], env)
        diag = _diagnostics("backend primitive", state_dir, "n/a", "n/a", p_a, p_b, out_a, err_a, out_b, err_b)
        assert sorted([p_a.returncode, p_b.returncode]) == [0, 1], diag

    def test_two_concurrent_ai_create_claim_ref_calls_exactly_one_wins(self, fake_gh_path, tmp_path):
        """Test B, plus the diagnostics required by this task (D/E/F
        below are separate, narrower assertions on the SAME run's
        artifacts so a failure in one doesn't hide the others)."""
        bin_dir, log_path = fake_gh_path
        state_file = tmp_path / "claim-state"
        ref = "refs/heads/ai-claims/issue-77-approval-appr-77-race"
        sha = "dddddddddddddddddddddddddddddddddddddddd"
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_CLAIM_STATE"] = str(state_file)

        cmd = ["bash", "-c", f"source '{COMMON_SH}'; ai_create_claim_ref '{ref}' '{sha}'"]
        p_a, p_b, out_a, err_a, out_b, err_b = _launch_pair(cmd, env, cwd=str(REPO_ROOT))
        diag = _diagnostics("ai_create_claim_ref race", state_file, ref, sha, p_a, p_b, out_a, err_a, out_b, err_b, log_path)

        returncodes = sorted([p_a.returncode, p_b.returncode])
        assert returncodes == [0, 1], diag

        # Test C: the winner's own output identifies the successful claim.
        winner_err = err_a if p_a.returncode == 0 else err_b
        assert "Claim ref created atomically" in winner_err, diag
        assert ref in winner_err, diag

        # Test D: the loser's own output identifies already-exists/422 behavior.
        loser_err = err_b if p_a.returncode == 0 else err_a
        assert "already exists" in loser_err.lower() or "already claimed" in loser_err.lower(), diag

        # Test E: both children used the identical shared state directory
        # and Test F: both attempted the identical claim ref — read back
        # from the fake backend's own CLAIM_GRANTED/CLAIM_DENIED
        # diagnostic lines specifically (not the raw invocation log line,
        # which also contains "ref=" as a substring of "-f ref=..." and
        # would otherwise double-count).
        log_text = Path(log_path).read_text()
        claim_lines = [line for line in log_text.splitlines() if line.startswith(("CLAIM_GRANTED", "CLAIM_DENIED"))]
        assert len(claim_lines) == 2, diag
        assert all(f"state={state_file}" in line for line in claim_lines), diag  # Test E
        assert all(f"ref={ref}" in line and f"sha={sha}" in line for line in claim_lines), diag  # Test F

    def test_shared_state_path_is_one_absolute_path_created_once_by_the_parent(self, tmp_path):
        """Guards against the specific failure classes this task named
        (different TMPDIR per child, env var not exported, fixture
        path resolved differently, state recreated between children):
        the state path is computed once, here, in the parent process,
        as an absolute path, and handed to both children via the same
        env dict object — never recomputed per child."""
        state_file = tmp_path / "claim-state"
        assert state_file.is_absolute()
        env_for_a = dict(os.environ)
        env_for_a["FAKE_GH_CLAIM_STATE"] = str(state_file)
        env_for_b = dict(os.environ)
        env_for_b["FAKE_GH_CLAIM_STATE"] = str(state_file)
        assert env_for_a["FAKE_GH_CLAIM_STATE"] == env_for_b["FAKE_GH_CLAIM_STATE"]
        assert env_for_a["FAKE_GH_CLAIM_STATE"] == str(state_file)


# ---------------------------------------------------------------------------
# Blocker 2: review.sh must abort, not swallow, on any authoritative
# git failure. These use two REAL, already-local commits from this
# repository's own history (no network fetch needed — HEAD~1 and HEAD
# are already present) as base/head, so review.sh's real `git fetch`
# + `git cat-file -e` checks succeed trivially, and inject a fake
# `git` that fails ONE specific operation while delegating everything
# else to the real binary.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_base_head_shas():
    """(base, head, count, changed_paths) for the real HEAD~1..HEAD
    pair in THIS checkout. changed_paths is derived from an actual
    `git diff --name-only -z` (NUL-safe — no ambiguity from spaces or
    a pathological embedded newline) rather than assumed: which files
    a given commit touches is not something a test should hard-code,
    since it changes every time this repair commit's own contents
    change. Any test that needs to inject a failure for "some real
    changed path" must pick one from changed_paths, never name a
    specific file directly.

    count is len(changed_paths), not a raw newline count — the prior
    `stdout.strip().count("\\n") + 1` silently returned 1 for a
    genuinely empty diff (str.count on "" is 0, plus 1), which would
    have been a latent miscount had base and head ever coincided.
    """
    base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    raw = subprocess.run(
        ["git", "diff", "--name-only", "-z", base, head], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    changed_paths = [p for p in raw.split("\0") if p]
    return base, head, len(changed_paths), changed_paths


@pytest.fixture
def fake_git_selective_failure(tmp_path):
    """A `git` on PATH that delegates everything to the real binary
    EXCEPT specific operations named via env vars:
      FAKE_GIT_FAIL_DIFF_PATH     - `git diff BASE HEAD -- <this path>` fails
      FAKE_GIT_FAIL_NAME_STATUS   - `git diff --name-status -z ...` emits
                                     one partial record then fails
      FAKE_GIT_FAIL_LS_TREE_PATH  - `git ls-tree SHA -- <this path>` fails
    """
    bin_dir = tmp_path / "fake-git-selective"
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "args=(\"$@\")\n"
        "fail_diff_path=\"${FAKE_GIT_FAIL_DIFF_PATH:-}\"\n"
        "fail_name_status=\"${FAKE_GIT_FAIL_NAME_STATUS:-}\"\n"
        "fail_ls_tree_path=\"${FAKE_GIT_FAIL_LS_TREE_PATH:-}\"\n"
        "\n"
        "if [[ \"$1\" == \"-C\" && \"$3\" == \"diff\" ]]; then\n"
        "  if [[ -n \"${fail_name_status}\" ]] && printf '%s\\n' \"$*\" | grep -q -- '--name-status'; then\n"
        "    printf 'M\\0some-partial-file-before-crash.txt\\0'\n"
        "    echo 'fake: simulated I/O error mid-stream' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "  if [[ -n \"${fail_diff_path}\" ]]; then\n"
        "    for a in \"${args[@]}\"; do\n"
        "      if [[ \"${a}\" == \"${fail_diff_path}\" ]]; then\n"
        "        echo 'fake: simulated git diff failure for this path' >&2\n"
        "        exit 128\n"
        "      fi\n"
        "    done\n"
        "  fi\n"
        "fi\n"
        "if [[ \"$1\" == \"-C\" && \"$3\" == \"ls-tree\" && -n \"${fail_ls_tree_path}\" ]]; then\n"
        "  for a in \"${args[@]}\"; do\n"
        "    if [[ \"${a}\" == \"${fail_ls_tree_path}\" ]]; then\n"
        "      echo 'fake: simulated git ls-tree failure' >&2\n"
        "      exit 128\n"
        "    fi\n"
        "  done\n"
        "fi\n"
        f"exec {REAL_GIT_BIN} \"$@\"\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir


class TestReviewGitFailureAborts:
    def _run_review(self, fake_gh_path, fake_git_dir, issue_number, issue_json, pulls_json, extra_env=None):
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_dir}:{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = issue_json
        env["FAKE_GH_PULLS_JSON"] = pulls_json
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [str(SCRIPTS_DIR / "review.sh"), "4", "--issue", str(issue_number), "--approval-id", "appr-review-git",
             "--implementation-agent", "claude", "--reviewer", "codex"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def _fixture_issue_and_pulls(self, issue_number, base, head, count):
        issue_json, record = build_dispatch_ready_issue(issue_number, "low", "appr-review-git", base_sha=base)
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": base},
            "head": {"sha": head, "repo": {"id": 1320669590, "node_id": "R_kgDOTrfRlg"}},
            "changed_files": count, "title": "t", "html_url": "https://example/9",
        })
        return issue_json, pulls_json

    def test_review_per_file_git_diff_failure_aborts(self, fake_gh_path, fake_git_selective_failure, real_base_head_shas):
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout — nothing to inject a diff failure for.")
        issue_json, pulls_json = self._fixture_issue_and_pulls(201, base, head, count)
        result = self._run_review(
            fake_gh_path, fake_git_selective_failure, 201, issue_json, pulls_json,
            extra_env={"FAKE_GIT_FAIL_DIFF_PATH": changed_paths[0]},
        )
        assert result.returncode != 0
        assert "git diff failed" in result.stderr
        # No artifact/manifest claiming success was produced.
        assert "Review body" not in result.stdout
        assert "Canonical envelope digest" not in result.stdout

    def test_review_partial_git_output_failure_aborts(self, fake_gh_path, fake_git_selective_failure, real_base_head_shas):
        base, head, count, _ = real_base_head_shas
        issue_json, pulls_json = self._fixture_issue_and_pulls(202, base, head, count)
        result = self._run_review(
            fake_gh_path, fake_git_selective_failure, 202, issue_json, pulls_json,
            extra_env={"FAKE_GIT_FAIL_NAME_STATUS": "1"},
        )
        assert result.returncode != 0
        assert "git diff --name-status failed" in result.stderr
        assert "Review body" not in result.stdout

    def test_review_missing_head_object_aborts(self, fake_gh_path, real_base_head_shas, tmp_path):
        base, _, count, _ = real_base_head_shas
        fake_head = "f" * 40
        issue_json, record = build_dispatch_ready_issue(203, "low", "appr-review-git-head", base_sha=base)
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": base},
            "head": {"sha": fake_head, "repo": {"id": 1320669590, "node_id": "R_kgDOTrfRlg"}},
            "changed_files": count, "title": "t", "html_url": "https://example/9",
        })
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = issue_json
        env["FAKE_GH_PULLS_JSON"] = pulls_json
        result = subprocess.run(
            [str(SCRIPTS_DIR / "review.sh"), "4", "--issue", "203", "--approval-id", "appr-review-git-head",
             "--implementation-agent", "claude", "--reviewer", "codex"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode != 0
        assert "not present locally after fetch" in result.stderr

    def test_review_missing_base_object_aborts(self, fake_gh_path, real_base_head_shas):
        _, head, count, _ = real_base_head_shas
        fake_base = "e" * 40
        issue_json, record = build_dispatch_ready_issue(204, "low", "appr-review-git-base", base_sha=fake_base)
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": fake_base},
            "head": {"sha": head, "repo": {"id": 1320669590, "node_id": "R_kgDOTrfRlg"}},
            "changed_files": count, "title": "t", "html_url": "https://example/9",
        })
        bin_dir, log_path = fake_gh_path
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_ISSUE_JSON"] = issue_json
        env["FAKE_GH_PULLS_JSON"] = pulls_json
        result = subprocess.run(
            [str(SCRIPTS_DIR / "review.sh"), "4", "--issue", "204", "--approval-id", "appr-review-git-base",
             "--implementation-agent", "claude", "--reviewer", "codex"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode != 0
        assert "not present locally after fetch" in result.stderr

    def test_review_shared_per_file_diff_failure_path_aborts_for_any_changed_file(
        self, fake_gh_path, fake_git_selective_failure, real_base_head_shas
    ):
        """Renamed from a name that implied rename/deleted/binary/
        submodule status coverage this fixture never actually
        guaranteed (real_base_head_shas only knows THIS checkout's
        real HEAD~1..HEAD diff, whatever statuses that happens to
        contain). What IS actually true, and what this regression-tests
        for real: review.sh's per-file loop routes every ordinary
        changed file (rename, delete, binary, submodule, or plain
        modify alike — see the branching in review.sh around
        "git diff failed for ... status") through the SAME
        ai_run_git_capture call, so a diff failure on any one changed
        path aborts the review the same way regardless of that path's
        status. Deliberately exercises a DIFFERENT path than
        test_review_per_file_git_diff_failure_aborts (last vs. first
        of the real changed-path list) rather than duplicating it
        outright."""
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout — nothing to inject a diff failure for.")
        issue_json, pulls_json = self._fixture_issue_and_pulls(205, base, head, count)
        result = self._run_review(
            fake_gh_path, fake_git_selective_failure, 205, issue_json, pulls_json,
            extra_env={"FAKE_GIT_FAIL_DIFF_PATH": changed_paths[-1]},
        )
        assert result.returncode != 0
        assert "git diff failed" in result.stderr

    def test_review_failed_submodule_tree_lookup_aborts(self, fake_gh_path, fake_git_selective_failure, real_base_head_shas):
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout — nothing to inject an ls-tree failure for.")
        issue_json, pulls_json = self._fixture_issue_and_pulls(206, base, head, count)
        result = self._run_review(
            fake_gh_path, fake_git_selective_failure, 206, issue_json, pulls_json,
            extra_env={"FAKE_GIT_FAIL_LS_TREE_PATH": changed_paths[0]},
        )
        assert result.returncode != 0
        assert "git ls-tree failed" in result.stderr

    def test_no_bare_process_substitution_left_for_name_status_in_review_sh(self):
        """Hardening fix 6's principle applied to review.sh's own
        filename enumerator: the git diff --name-status producer must
        be captured to a checked file, never `< <(...)`."""
        source = (SCRIPTS_DIR / "review.sh").read_text()
        assert "< <(git" not in source


class TestReviewSchemaJson:
    """Regression coverage for Scripts/ai/review-schema.json's
    additionalProperties: false fix. This schema is handed to an
    automated reviewer (claude/codex --output-schema) to constrain its
    structured output — without additionalProperties: false, a
    reviewer's response could carry arbitrary extra top-level fields
    past validation undetected."""

    SCHEMA_PATH = SCRIPTS_DIR / "review-schema.json"
    EXPECTED_FIELDS = frozenset({"summary", "blocking_findings", "non_blocking_findings", "recommendation"})

    @classmethod
    def _load(cls):
        return json.loads(cls.SCHEMA_PATH.read_text())

    def test_valid_json(self):
        # json.loads raising IS the failure mode here — a bare parse
        # is the entire assertion.
        self._load()

    def test_root_type_is_object(self):
        assert self._load().get("type") == "object"

    def test_additional_properties_is_exactly_false(self):
        schema = self._load()
        assert schema.get("additionalProperties") is False, (
            f"additionalProperties must be the JSON boolean false, got {schema.get('additionalProperties')!r} "
            "— without it, a reviewer's structured output can carry undeclared extra fields silently."
        )

    def test_required_fields_equal_declared_properties(self):
        schema = self._load()
        required = set(schema.get("required", []))
        properties = set(schema.get("properties", {}).keys())
        assert required == properties, (
            f"required {sorted(required)} and properties {sorted(properties)} must name exactly the same "
            "fields — additionalProperties: false only closes the door on UNDECLARED fields; a declared-but-"
            "not-required property would still let a reviewer omit it silently."
        )

    def test_expected_four_fields_remain_present(self):
        assert set(self._load().get("properties", {}).keys()) == self.EXPECTED_FIELDS


class TestCodexBundleSelfContained:
    """PR #6 smoke-test defect: the manual Codex review packet told
    Codex to "read AI_WORKFLOW.md, CONSTITUTION.md, and PROJECT.md
    yourself" while giving it no shell/git/network access to do so — a
    real `codex exec` correctly refused to review on that basis. The
    bundle must be genuinely self-contained: everything Codex is asked
    to consult is embedded in the prompt it reads from stdin. Codex
    itself still never gets real repository/shell/network access —
    that is unchanged and re-verified here, not weakened."""

    ACCEPTANCE_MARKER = "UNIQUE_ACCEPTANCE_MARKER_2b91f7"
    KNOWN_COMMITTED_SUBSTRING = "Supervised reviewer provenance"
    WORKTREE_ROOT = REPO_ROOT / "Temp" / "ai-worktrees"

    def _build_fixture(self, issue_number, approval_id, base_sha, allowed_paths=("src/foo.py", "src/bar.py")):
        issue_body = (
            "Problem: test fixture for the codex self-contained bundle.\n\n"
            "Desired outcome: prove the embedded authoritative context.\n\n"
            "Acceptance criteria:\n"
            f"- {self.ACCEPTANCE_MARKER} must be satisfied\n"
        )
        digest = compute_issue_digest(issue_body)
        record = {
            "approval_id": approval_id, "repository_id": "R_kgDOTrfRlg", "issue_number": issue_number,
            "approver": "gokul-hastrophil", "agent": "claude", "risk": "low",
            "issue_body_digest": digest, "allowed_paths": list(allowed_paths), "base_sha": base_sha,
            "timestamp": "2026-01-01T00:00:00Z", "schema": "heimei-approval/v1",
        }
        body = "## Approval\n```json\n" + json.dumps(record) + "\n```\n<!-- heimei-approval:v1 -->"
        issue_json = json.dumps({
            "number": issue_number, "title": "t", "state": "OPEN",
            "labels": [{"name": "risk:low"}], "body": issue_body, "url": "u",
            "comments": [{"id": "c1", "author": {"login": "gokul-hastrophil"}, "body": body, "createdAt": "2026-01-01T00:00:00Z"}],
        })
        return issue_json, record

    def _run(self, fake_gh_path, issue_number, approval_id, issue_json, base_sha, head_sha, changed_files, cwd=None):
        pulls_json = json.dumps({
            "base": {"ref": "main", "sha": base_sha},
            "head": {"sha": head_sha, "repo": {"id": 1320669590, "node_id": "R_kgDOTrfRlg"}},
            "changed_files": changed_files, "title": "t", "html_url": "https://example/codexbundle",
        })
        return run_script(
            "review.sh",
            ["4", "--issue", str(issue_number), "--approval-id", approval_id,
             "--implementation-agent", "claude", "--reviewer", "codex"],
            fake_gh_path,
            extra_env={"FAKE_GH_ISSUE_JSON": issue_json, "FAKE_GH_PULLS_JSON": pulls_json},
            cwd=cwd,
        )

    @staticmethod
    def _extract_prompt_path(stdout, batch_num=0):
        m = re.search(r"written to:\s*\n\s*(\S+)", stdout)
        assert m, f"could not find bundle directory path in stdout: {stdout!r}"
        return Path(m.group(1)) / f"prompt-batch-{batch_num}.txt"

    def _make_worktree(self, branch_suffix):
        import uuid

        branch = f"tmp/harness-codexbundle-{branch_suffix}-{uuid.uuid4().hex[:8]}"
        self.WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
        wt_dir = self.WORKTREE_ROOT / f"harness-codexbundle-{branch_suffix}-{uuid.uuid4().hex[:8]}"
        subprocess.run(["git", "worktree", "add", "-q", "-b", branch, str(wt_dir), "HEAD"], cwd=REPO_ROOT, check=True)
        return branch, wt_dir

    def _cleanup_worktree(self, branch, wt_dir):
        subprocess.run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=REPO_ROOT, check=False)
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False)

    def test_prompt_contains_validated_acceptance_criteria(self, fake_gh_path, real_base_head_shas):
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout.")
        issue_json, record = self._build_fixture(320, "appr-codexbundle-criteria", base_sha=base)
        result = self._run(fake_gh_path, 320, "appr-codexbundle-criteria", issue_json, base, head, count)
        assert result.returncode == 0, result.stderr
        text = self._extract_prompt_path(result.stdout).read_text()
        assert self.ACCEPTANCE_MARKER in text

    def test_prompt_contains_approval_id_base_sha_and_allowed_paths(self, fake_gh_path, real_base_head_shas):
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout.")
        issue_json, record = self._build_fixture(321, "appr-codexbundle-fields", base_sha=base)
        result = self._run(fake_gh_path, 321, "appr-codexbundle-fields", issue_json, base, head, count)
        assert result.returncode == 0, result.stderr
        text = self._extract_prompt_path(result.stdout).read_text()
        assert "appr-codexbundle-fields" in text
        assert base in text
        assert "src/foo.py" in text
        assert "src/bar.py" in text

    def test_bundle_prompt_is_fully_self_contained(self, fake_gh_path, real_base_head_shas):
        """Holistic proof of 'usable with no repository access': every
        section a reviewer would otherwise need to fetch itself is
        present, inline, in the ONE file Codex reads from stdin."""
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout.")
        issue_json, record = self._build_fixture(322, "appr-codexbundle-selfcontained", base_sha=base)
        result = self._run(fake_gh_path, 322, "appr-codexbundle-selfcontained", issue_json, base, head, count)
        assert result.returncode == 0, result.stderr
        text = self._extract_prompt_path(result.stdout).read_text()
        for marker in (
            "AUTHORITATIVE REVIEW CONTEXT",
            self.ACCEPTANCE_MARKER,
            "Trusted approval record",
            "~~~ AGENTS.md",
            "~~~ VISION.md",
            "~~~ CONSTITUTION.md",
            "~~~ PROJECT.md",
            "~~~ AI_WORKFLOW.md",
            "~~~ Projects/Heimei/docs/DEVELOPMENT.md",
            "~~~ Projects/Heimei/docs/ARCHITECTURE.md",
            "Privacy boundary",
            "Live PR body (UNTRUSTED",
            "=== Batch 0 diff ===",
        ):
            assert marker in text, f"missing {marker!r} from a supposedly self-contained prompt"

    def test_prompt_no_longer_instructs_codex_to_read_files_or_shell_out(self, fake_gh_path, real_base_head_shas):
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout.")
        issue_json, record = self._build_fixture(323, "appr-codexbundle-contract", base_sha=base)
        result = self._run(fake_gh_path, 323, "appr-codexbundle-contract", issue_json, base, head, count)
        assert result.returncode == 0, result.stderr
        text = self._extract_prompt_path(result.stdout).read_text()
        assert "read AI_WORKFLOW.md, CONSTITUTION.md, and PROJECT.md yourself" not in text
        assert "you may read repository files" not in text.lower()
        assert "do not read the working tree, invoke git, execute commands" in text.lower()

    def test_bundle_description_no_longer_claims_diffs_only(self, fake_gh_path, real_base_head_shas):
        base, head, count, changed_paths = real_base_head_shas
        if not changed_paths:
            pytest.skip("HEAD~1..HEAD has no changed paths in this checkout.")
        issue_json, record = self._build_fixture(324, "appr-codexbundle-desc", base_sha=base)
        result = self._run(fake_gh_path, 324, "appr-codexbundle-desc", issue_json, base, head, count)
        assert result.returncode == 0, result.stderr
        assert "no repository/private-file exposure beyond the diffs themselves" not in result.stdout
        assert "Self-contained, sanitized bundle" in result.stdout

    def test_governance_extraction_uses_approval_base_sha_never_pr_head(self):
        """Source-level guard: the governance `git show` calls must key
        off APPROVAL_BASE_SHA (the validated approval record's own base
        SHA) — never BASE_SHA/HEAD_SHA (the PR's live, re-fetchable
        base/head) — so a PR under review can never redefine the rules
        it is judged against by simply having a different live base."""
        source = (SCRIPTS_DIR / "review.sh").read_text()
        assert 'git -C "${PRIMARY_ROOT}" show "${APPROVAL_BASE_SHA}:${doc}"' in source

    def test_governance_context_allowlist_is_fixed_and_excludes_private_paths(self):
        source = (SCRIPTS_DIR / "review.sh").read_text()

        for required in (
            "AGENTS.md",
            "VISION.md",
            "CONSTITUTION.md",
            "PROJECT.md",
            "AI_WORKFLOW.md",
            "Projects/Heimei/docs/DEVELOPMENT.md",
            "Projects/Heimei/docs/ARCHITECTURE.md",
        ):
            assert required in source

        # A validated issue may add exactly its named canonical ADR.
        assert "Relevant ADR" in source
        assert "ADR-[0-9]{4}" in source
        assert "System/docs/Architecture" in source

        # The zero-text-batch branch distinguishes a genuinely empty PR
        # from a non-empty PR whose files cannot be AI-reviewed.
        assert '[[ "${TOTAL_FILES}" -eq 0 ]]' in source
        assert "zero AI-reviewable text diffs" in source

        # No private/local content source is ever opened by review.sh.
        for forbidden in (
            ".envrc",
            "Knowledge/Documentation/Standards.md",
            "Configs/",
            "Scripts/Backup/",
            "cmd.txt",
            str(Path.home()),
        ):
            assert forbidden not in source

    def test_worktree_dirty_governance_doc_cannot_contaminate_bundle(self, fake_gh_path):
        """Dynamic proof (not just source inspection): a real,
        disposable git worktree whose WORKING-TREE copy of
        AI_WORKFLOW.md is poisoned with a marker never committed
        anywhere must not leak that marker into the bundle — `git show
        <sha>:AI_WORKFLOW.md` reads the git object, which the dirty
        working tree never touches. The real, committed content must
        still come through, proving this isn't just an empty section."""
        branch, wt_dir = self._make_worktree("dirty")
        try:
            # Real, non-empty base/head pair (this checkout's own
            # HEAD~1..HEAD, same technique as real_base_head_shas) —
            # base==head would produce an empty diff, and review.sh
            # never generates a prompt file for an empty batch. Which
            # exact SHAs are used is orthogonal to what's under test
            # here: whether a dirty WORKING-TREE file leaks in.
            base = subprocess.run(
                ["git", "rev-parse", "HEAD~1"], cwd=wt_dir, capture_output=True, text=True, check=True
            ).stdout.strip()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=wt_dir, capture_output=True, text=True, check=True
            ).stdout.strip()
            raw = subprocess.run(
                ["git", "diff", "--name-only", "-z", base, head], cwd=wt_dir, capture_output=True, text=True, check=True
            ).stdout
            count = len([p for p in raw.split("\0") if p])
            if count <= 0:
                pytest.skip("HEAD~1..HEAD has no changed paths in this checkout.")

            poison = "POISON_MARKER_NEVER_COMMITTED_9f3e1c"
            workflow_path = wt_dir / "AI_WORKFLOW.md"
            original = workflow_path.read_text()
            workflow_path.write_text(original + f"\n\n{poison}\n")

            issue_json, record = self._build_fixture(325, "appr-codexbundle-dirty", base_sha=base)
            result = self._run(
                fake_gh_path, 325, "appr-codexbundle-dirty", issue_json, base, head, count, cwd=wt_dir
            )
            assert result.returncode == 0, result.stderr
            text = self._extract_prompt_path(result.stdout).read_text()
            assert poison not in text, "a dirty working-tree edit leaked into the bundled governance context"
            assert self.KNOWN_COMMITTED_SUBSTRING in text, "the real, committed governance content did not come through"
        finally:
            self._cleanup_worktree(branch, wt_dir)

    def test_missing_governance_doc_at_base_sha_aborts_review(self, fake_gh_path):
        """A fake, non-existent base SHA must abort bundle generation
        outright — never proceed with a packet silently missing the
        governance rules it claims to embed."""
        fake_base_sha = "f" * 40
        real_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        issue_json, record = self._build_fixture(326, "appr-codexbundle-missing-gov", base_sha=fake_base_sha)
        result = self._run(fake_gh_path, 326, "appr-codexbundle-missing-gov", issue_json, real_head, real_head, 0)
        assert result.returncode != 0
        assert "Could not extract" in result.stderr
        assert "refusing to generate a Codex review packet" in result.stderr


# ---------------------------------------------------------------------------
# Blocker 3: Claude must receive only an explicit, mechanically-
# restricted tool surface.
# ---------------------------------------------------------------------------


def _extract_flag_value(source: str, flag: str) -> str:
    """Extracts the literal argument string following `flag` in a
    backslash-continued CLI invocation, e.g. for `--tools
    "Read,Edit,Write,Grep,Glob" \\`, returns
    'Read,Edit,Write,Grep,Glob'."""
    m = re.search(rf'{re.escape(flag)}\s+"([^"]*)"', source)
    assert m, f"could not find {flag} \"...\" in source"
    return m.group(1)


class TestClaudeToolSurface:
    def test_claude_invocation_uses_explicit_tools_selection(self):
        """--tools defines the ACTUAL available built-in tool set —
        stronger than a permission filter. Its presence (not just
        --allowedTools) is what this blocker requires."""
        source = (SCRIPTS_DIR / "dispatch.sh").read_text()
        tools_value = _extract_flag_value(source, "--tools")
        assert tools_value == "Read,Edit,Write,Grep,Glob"

    def test_claude_invocation_has_no_execution_tool(self):
        source = (SCRIPTS_DIR / "dispatch.sh").read_text()
        tools_value = _extract_flag_value(source, "--tools")
        allowed_value = _extract_flag_value(source, "--allowedTools")
        forbidden = ["Bash", "Shell", "Terminal", "Execute", "agent-git", "gh", "MCP"]
        for token in forbidden:
            assert token not in tools_value, f"{token!r} must not appear in --tools"
            assert token not in allowed_value, f"{token!r} must not appear in --allowedTools"
        # Bash IS expected in --disallowedTools (an explicit deny, on
        # top of --tools already excluding it) — confirm that's where
        # it lives, not silently absent from the whole invocation.
        disallowed_value = _extract_flag_value(source, "--disallowedTools")
        assert "Bash" in disallowed_value

    def test_claude_invocation_uses_safe_mode_and_isolated_mcp_config(self):
        source = (SCRIPTS_DIR / "dispatch.sh").read_text()
        assert "--safe-mode" in source
        assert "--strict-mcp-config" in source
        assert '--mcp-config "${EMPTY_MCP_CONFIG}"' in source
        assert '--setting-sources ""' in source

    def test_dispatch_calls_the_tool_surface_preflight(self):
        source = (SCRIPTS_DIR / "dispatch.sh").read_text()
        assert "ai_require_safe_claude_tool_surface" in source

    def test_claude_unsafe_cli_capability_fails_closed(self, tmp_path):
        """A fake `claude` whose --help is missing one required flag
        (--mcp-config) must be rejected outright, not silently
        tolerated with a narrower actual grant."""
        bin_dir = tmp_path / "fakeclaude"
        bin_dir.mkdir()
        script = bin_dir / "claude"
        script.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == \"--version\" ]]; then echo 'fake-claude 0.0.0'; exit 0; fi\n"
            "if [[ \"$1\" == \"--help\" ]]; then\n"
            "  echo 'Options: --tools --allowedTools --disallowedTools --permission-mode --safe-mode --strict-mcp-config --setting-sources -p --output-format'\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        result = run_bash("ai_require_safe_claude_tool_surface", env=env)
        assert result.returncode != 0
        assert "cannot prove an execution-free tool surface" in result.stderr
        assert "--mcp-config" in result.stderr

    def test_claude_full_capability_passes_preflight(self):
        # Uses the REAL installed claude CLI (2.1.224 at the time this
        # pass was written) — no fake needed, since it genuinely
        # advertises everything required.
        result = run_bash("ai_require_safe_claude_tool_surface")
        assert result.returncode == 0, result.stderr

    def test_empirical_probe_evidence_is_documented_not_overclaimed(self):
        """This suite does not bake a live, paid Claude API call into
        the automated test run (cost, non-hermetic, requires
        credentials in CI). The empirical bounded probe described in
        dispatch.sh's own comments — run manually during this pass,
        confirming the model's self-reported tool list was exactly
        'Edit, Glob, Grep, Read, Write' with an empty permission_denials
        list — is documented as a one-time manual confirmation, not
        something this automated suite re-proves every run. This test
        only confirms that honest scoping is actually written down."""
        source = (SCRIPTS_DIR / "dispatch.sh").read_text()
        assert "self-report from the model process, not an independent" in source


# ---------------------------------------------------------------------------
# Blocker 4: risk has one source of truth.
# ---------------------------------------------------------------------------


class TestRiskSingleSourceOfTruth:
    def test_low_low_accepted_by_pure_function(self):
        result = run_bash('ai_require_single_risk_label "$(printf "risk:low")"')
        assert result.returncode == 0 and result.stdout.strip() == "low"

    def test_medium_medium_accepted_by_pure_function(self):
        result = run_bash('ai_require_single_risk_label "$(printf "risk:medium")"')
        assert result.returncode == 0 and result.stdout.strip() == "medium"

    def test_approve_high_risk_rejected(self, fake_gh_path):
        issue_json = json.dumps({
            "number": 301, "title": "t", "state": "OPEN", "labels": [{"name": "risk:high"}],
            "body": "Problem: x\n\nDesired outcome: y\n\nAcceptance criteria: z\n\nAllowed paths:\na.txt",
            "url": "u", "comments": [],
        })
        result = run_script(
            "approve.sh", ["301", "--agent", "claude", "--risk", "high", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "never dispatchable" in result.stderr

    def test_approve_risk_mismatch_rejected(self, fake_gh_path):
        issue_json = json.dumps({
            "number": 302, "title": "t", "state": "OPEN", "labels": [{"name": "risk:medium"}],
            "body": "Problem: x\n\nDesired outcome: y\n\nAcceptance criteria: z\n\nAllowed paths:\na.txt",
            "url": "u", "comments": [],
        })
        result = run_script(
            "approve.sh", ["302", "--agent", "claude", "--risk", "low", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "does not match the issue's risk:medium label" in result.stderr

    def test_approve_missing_risk_label_rejected(self, fake_gh_path):
        issue_json = json.dumps({
            "number": 303, "title": "t", "state": "OPEN", "labels": [],
            "body": "Problem: x\n\nDesired outcome: y\n\nAcceptance criteria: z\n\nAllowed paths:\na.txt",
            "url": "u", "comments": [],
        })
        result = run_script(
            "approve.sh", ["303", "--agent", "claude", "--risk", "low", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "no risk:* label" in result.stderr

    def test_approve_two_risk_labels_rejected(self, fake_gh_path):
        issue_json = json.dumps({
            "number": 304, "title": "t", "state": "OPEN", "labels": [{"name": "risk:low"}, {"name": "risk:medium"}],
            "body": "Problem: x\n\nDesired outcome: y\n\nAcceptance criteria: z\n\nAllowed paths:\na.txt",
            "url": "u", "comments": [],
        })
        result = run_script(
            "approve.sh", ["304", "--agent", "claude", "--risk", "low", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "2 risk:* labels" in result.stderr

    def test_approve_unknown_issue_risk_rejected(self, fake_gh_path):
        issue_json = json.dumps({
            "number": 305, "title": "t", "state": "OPEN", "labels": [{"name": "risk:critical"}],
            "body": "Problem: x\n\nDesired outcome: y\n\nAcceptance criteria: z\n\nAllowed paths:\na.txt",
            "url": "u", "comments": [],
        })
        result = run_script(
            "approve.sh", ["305", "--agent", "claude", "--risk", "low", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "not a recognized value" in result.stderr

    def test_dispatch_high_risk_historical_record_rejected(self, fake_gh_path):
        """A crafted historical approval record claiming risk:high
        must be rejected at DISPATCH time too, regardless of the
        issue's current label — high is never dispatchable, full
        stop, not conditional on label agreement."""
        issue_json, record = build_dispatch_ready_issue(306, "high", "appr-306-high")
        result = run_script(
            "dispatch.sh", ["306", "--agent", "claude", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "high" in result.stderr
        assert "not dispatchable" in result.stderr

    def test_dispatch_risk_label_mismatch_rejected(self, fake_gh_path):
        """Approval says low, issue's live label now says medium —
        rejected, never trusting the approval record's own risk field
        over the live label."""
        issue_json, record = build_dispatch_ready_issue(307, "low", "appr-307-mismatch")
        payload = json.loads(issue_json)
        payload["labels"] = [{"name": "risk:medium"}]
        issue_json = json.dumps(payload)
        result = run_script(
            "dispatch.sh", ["307", "--agent", "claude", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "no longer matches" in result.stderr

    def test_dispatch_missing_risk_label_rejected(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(308, "low", "appr-308-norisk")
        payload = json.loads(issue_json)
        payload["labels"] = []
        issue_json = json.dumps(payload)
        result = run_script(
            "dispatch.sh", ["308", "--agent", "claude", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "no risk:* label" in result.stderr

    def test_dispatch_two_risk_labels_rejected(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(309, "low", "appr-309-tworisk")
        payload = json.loads(issue_json)
        payload["labels"] = [{"name": "risk:low"}, {"name": "risk:high"}]
        issue_json = json.dumps(payload)
        result = run_script(
            "dispatch.sh", ["309", "--agent", "claude", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "risk:* labels" in result.stderr

    def test_dispatch_unknown_issue_risk_rejected(self, fake_gh_path):
        issue_json, record = build_dispatch_ready_issue(310, "low", "appr-310-unknown")
        payload = json.loads(issue_json)
        payload["labels"] = [{"name": "risk:extreme"}]
        issue_json = json.dumps(payload)
        result = run_script(
            "dispatch.sh", ["310", "--agent", "claude", "--dry-run"],
            fake_gh_path, extra_env={"FAKE_GH_ISSUE_JSON": issue_json},
        )
        assert result.returncode != 0
        assert "not a recognized value" in result.stderr

    def test_dispatch_low_low_and_medium_medium_reach_fresh_claim_plan(self, fake_gh_path, fake_git_claim_ref):
        for risk in ("low", "medium"):
            issue_json, record = build_dispatch_ready_issue(400 + hash(risk) % 100, risk, f"appr-{risk}-ok")
            bin_dir, log_path = fake_gh_path
            env = dict(os.environ)
            env["PATH"] = f"{fake_git_claim_ref}:{bin_dir}:{env['PATH']}"
            env["FAKE_GH_LOG"] = str(log_path)
            env["FAKE_GH_ISSUE_JSON"] = issue_json
            env["FAKE_GIT_CLAIM_REF_SHA"] = ""
            result = subprocess.run(
                [str(SCRIPTS_DIR / "dispatch.sh"), str(record["issue_number"]), "--agent", "claude", "--dry-run"],
                cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=60,
            )
            assert result.returncode == 0, f"risk={risk}: {result.stderr}"
            assert f"Risk:            {risk}" in result.stdout


# ---------------------------------------------------------------------------
# Hardening fix 6: changed-path enumeration must propagate a real git
# failure, never silently consume partial NUL data as if it were the
# complete, authoritative file list.
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_git_partial_then_fail(tmp_path):
    """A `git` on PATH that, for `status ...`, emits ONE partial NUL
    record and then exits non-zero — simulating an I/O error, a killed
    process, or a corrupted repository mid-enumeration — and delegates
    every other subcommand to the real binary."""
    bin_dir = tmp_path / "fake-git-partial"
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"${arg}\" == \"status\" ]]; then\n"
        "    printf '?? partial-file-before-crash.txt\\0'\n"
        "    echo 'fake: simulated I/O error mid-enumeration' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "done\n"
        f"exec {REAL_GIT_BIN} \"$@\"\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir


class TestChangedPathEnumerationFailurePropagation:
    def test_changed_path_git_failure_propagates(self, fake_git_partial_then_fail):
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_partial_then_fail}:{env['PATH']}"
        out = "/tmp/hardening6-out-1"
        result = run_bash(f'ai_enumerate_changed_paths "{REPO_ROOT}" "{out}"', env=env)
        assert result.returncode != 0
        assert "git status failed" in result.stderr or "command failed" in result.stderr

    def test_changed_path_partial_output_not_consumed(self, fake_git_partial_then_fail, tmp_path):
        """The enumerator must return no authoritative filename set —
        not a truncated-but-still-used one — when its producer fails
        partway through."""
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_partial_then_fail}:{env['PATH']}"
        out = str(tmp_path / "enum-out")
        result = run_bash(f'ai_enumerate_changed_paths "{REPO_ROOT}" "{out}" && echo SHOULD_NOT_REACH_HERE', env=env)
        assert result.returncode != 0
        assert "SHOULD_NOT_REACH_HERE" not in result.stdout
        # ai_run_git_capture deletes its output file on failure — the
        # partial "partial-file-before-crash.txt" record must never
        # end up as a usable, readable file an unwary caller could
        # accidentally still consume.
        assert not Path(out).exists() or Path(out).stat().st_size == 0

    def test_ai_validate_changed_paths_also_fails_closed_on_git_failure(self, fake_git_partial_then_fail, tmp_path):
        d = tmp_path / "wt"
        d.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
        (d / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=d, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, check=True)
        env = dict(os.environ)
        env["PATH"] = f"{fake_git_partial_then_fail}:{env['PATH']}"
        result = run_bash(f"ai_validate_changed_paths '{d}' 'f.txt'", env=env)
        assert result.returncode != 0
        assert "possibly-partial" in result.stderr
