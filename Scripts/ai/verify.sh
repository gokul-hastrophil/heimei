#!/usr/bin/env bash
# Scripts/ai/verify.sh
#
# Runs Heimei's real checks — uv sync --locked, uv run pytest, uv run
# ruff check ., uv run mypy src/heimei — against an EXPLICIT, validated
# repository root, capturing REAL transcripts (never a synthesized
# "PASS"/"FAIL" string) with SHA-256 hashes, exact commands, and
# timestamps. See AI_WORKFLOW.md, "Real verification transcripts" and
# "Registered dispatch worktree verification."
#
# Two explicit, mutually exclusive modes:
#
#   --mode developer --repo-root PATH
#     Ordinary local verification against any recognized checkout
#     (the primary repo, or anything under the configured worktree
#     root). This mode is NEVER accepted by dispatch.sh as proof for
#     push or PR creation — its JSON output is tagged "mode":
#     "developer" specifically so a caller can mechanically refuse it.
#
#   --mode dispatch --run-manifest PATH --repo-root PATH --expected-sha SHA
#     The only mode dispatch.sh trusts. Requires a dispatcher-owned run
#     manifest (see ai_write_run_manifest/ai_read_run_manifest in
#     common.sh) and cross-checks EVERY field: manifest path is inside
#     the configured run-manifest root and not a symlink; --repo-root's
#     realpath exactly equals the manifest's recorded worktree
#     realpath; the worktree is registered in the primary repository's
#     own `git worktree list` (never the primary checkout itself, never
#     an unregistered sibling directory); the worktree's git
#     common-dir resolves to that same primary repository; the
#     manifest's repository_id, branch, and expected_commit_sha all
#     match; and the worktree's actual current HEAD matches
#     --expected-sha, the manifest's expected_commit_sha, AND
#     --expected-sha, three-way.
#
# There is no CWD-inference fallback in either mode: an earlier version
# of this script inferred the repo root from `git rev-parse
# --show-toplevel`, which silently resolved to whatever directory the
# *caller* happened to be sitting in — a caller that forgot to `cd`
# into an agent's worktree first would transparently verify the
# primary checkout (e.g. clean `main`) and report that as if it were
# the agent's actual work. --repo-root is mandatory with no default,
# in both modes.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

RUN_MODE="developer"
TEST_MODE="full"
JSON_OUT=""
REPO_ROOT_ARG=""
RUN_MANIFEST_ARG=""
EXPECTED_SHA_ARG=""

usage() {
  cat <<'EOF'
Usage:
  verify.sh --mode developer --repo-root PATH [--full|--fast] [--json PATH]
  verify.sh --mode dispatch --run-manifest PATH --repo-root PATH --expected-sha SHA [--json PATH]

  --mode developer|dispatch  Required. "dispatch" is the ONLY mode
                              dispatch.sh trusts as proof for push/PR
                              creation; "developer" is for ordinary
                              local verification and is never accepted
                              as dispatch proof (see the JSON output's
                              "mode" field).
  --repo-root PATH           Required in both modes. No default, no
                              CWD inference.
  --run-manifest PATH        Required (dispatch mode only). A
                              dispatcher-owned manifest — see
                              ai_write_run_manifest in common.sh.
  --expected-sha SHA         Required (dispatch mode only). Checked
                              three ways against the manifest and the
                              worktree's actual HEAD.
  --full                     Run pytest, ruff check ., and mypy
                              src/heimei in full. Default. Mandatory
                              before any PR leaves draft state.
  --fast                     Scope ruff/mypy to files changed vs.
                              origin/main only. pytest always runs in
                              full — a fast test subset can silently
                              miss a regression it should have caught.
  --json PATH                Also write a machine-readable JSON summary
                              (with real per-check transcripts, SHA-256
                              hashes, exact commands, and timestamps —
                              never a synthesized PASS/FAIL string) to
                              PATH. Referenced log files are copied
                              next to it and are NOT inside any
                              auto-cleaned temp directory, and never
                              inside the tested checkout itself.

Exit code is a bitmask: bit0=pytest failed, bit1=ruff failed,
bit2=mypy failed, bit3=uv sync failed. 0 means everything passed. The
tested commit SHA (from --repo-root's HEAD) is always printed and
included in the JSON output.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) RUN_MODE="${2:-}"; shift 2 ;;
    --repo-root) REPO_ROOT_ARG="${2:-}"; shift 2 ;;
    --run-manifest) RUN_MANIFEST_ARG="${2:-}"; shift 2 ;;
    --expected-sha) EXPECTED_SHA_ARG="${2:-}"; shift 2 ;;
    --full) TEST_MODE="full"; shift ;;
    --fast) TEST_MODE="fast"; shift ;;
    --json) JSON_OUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) ai_log_error "Unknown argument: $1"; usage; exit 64 ;;
  esac
done

[[ "${RUN_MODE}" == "developer" || "${RUN_MODE}" == "dispatch" ]] \
  || { ai_log_error "Invalid --mode '${RUN_MODE}' — must be 'developer' or 'dispatch'."; usage; exit 64; }
[[ -n "${REPO_ROOT_ARG}" ]] || { ai_log_error "Missing required --repo-root PATH."; usage; exit 64; }
if [[ "${RUN_MODE}" == "dispatch" ]]; then
  [[ -n "${RUN_MANIFEST_ARG}" ]] || { ai_log_error "--mode dispatch requires --run-manifest PATH."; usage; exit 64; }
  [[ -n "${EXPECTED_SHA_ARG}" ]] || { ai_log_error "--mode dispatch requires --expected-sha SHA."; usage; exit 64; }
  [[ "${EXPECTED_SHA_ARG}" =~ ^[0-9a-f]{40}$ ]] || ai_die "--expected-sha must be a 40-character lowercase hex SHA."
fi

# ---------------------------------------------------------------------------
# Validate --repo-root: realpath, no symlinks, inside an allowed
# location, and actually a Heimei checkout.
# ---------------------------------------------------------------------------

ai_require_not_symlink "${REPO_ROOT_ARG}"
VALIDATED_ROOT="$(ai_realpath_strict "${REPO_ROOT_ARG}")"
[[ -d "${VALIDATED_ROOT}" ]] || ai_die "--repo-root is not a directory: ${VALIDATED_ROOT}"

PRIMARY_ROOT="$(ai_realpath_strict "$(ai_repo_root)")"
WORKTREE_ROOT="$(ai_policy_get '.runtime.worktree_root')"
WORKTREE_ROOT_ABS="${PRIMARY_ROOT}/${WORKTREE_ROOT}"

case "${VALIDATED_ROOT}" in
  "${PRIMARY_ROOT}")
    [[ "${RUN_MODE}" == "developer" ]] \
      || ai_die "--mode dispatch refuses the primary checkout as a dispatch worktree: ${VALIDATED_ROOT}. Dispatch verification only ever runs against an isolated, registered worktree."
    ai_log_info "--repo-root is the primary checkout: ${VALIDATED_ROOT}"
    ;;
  "${WORKTREE_ROOT_ABS}"/*)
    ai_log_info "--repo-root is inside the configured worktree root: ${VALIDATED_ROOT}"
    ;;
  *)
    ai_die "--repo-root '${VALIDATED_ROOT}' is neither the primary checkout ('${PRIMARY_ROOT}') nor inside the configured worktree root ('${WORKTREE_ROOT_ABS}'). Refusing to verify an unrecognized location."
    ;;
esac

[[ -d "${VALIDATED_ROOT}/.git" || -f "${VALIDATED_ROOT}/.git" ]] || ai_die "--repo-root is not a git checkout (no .git): ${VALIDATED_ROOT}"
PROJECT_DIR="${VALIDATED_ROOT}/Projects/Heimei"
[[ -d "${PROJECT_DIR}" ]] || ai_die "--repo-root is not a valid Heimei checkout — Projects/Heimei is missing under: ${VALIDATED_ROOT}"
ai_require_cmd uv

TESTED_SHA="$(git -C "${VALIDATED_ROOT}" rev-parse HEAD 2>/dev/null)" || ai_die "Could not resolve HEAD SHA in --repo-root."
ai_log_info "Tested repo root: ${VALIDATED_ROOT}"
ai_log_info "Tested commit SHA: ${TESTED_SHA}"

# ---------------------------------------------------------------------------
# Dispatch-mode registered-worktree + manifest verification. Every
# field below is cross-checked independently — never trusted from a
# single source.
# ---------------------------------------------------------------------------

MANIFEST_JSON=""
if [[ "${RUN_MODE}" == "dispatch" ]]; then
  ai_require_not_symlink "${RUN_MANIFEST_ARG}"
  MANIFEST_PATH="$(ai_realpath_strict "$(dirname "${RUN_MANIFEST_ARG}")")/$(basename -- "${RUN_MANIFEST_ARG}")"
  MANIFEST_ROOT="$(ai_realpath_strict "$(ai_run_manifest_root)")"
  case "${MANIFEST_PATH}" in
    "${MANIFEST_ROOT}"/*) ;;
    *) ai_die "--run-manifest '${MANIFEST_PATH}' is outside the configured run-manifest root '${MANIFEST_ROOT}' — refusing." ;;
  esac

  MANIFEST_JSON="$(ai_read_run_manifest "${RUN_MANIFEST_ARG}")"
  MANIFEST_WORKTREE="$(jq -r '.worktree_realpath' <<<"${MANIFEST_JSON}")"
  MANIFEST_REPO_ID="$(jq -r '.repository_id' <<<"${MANIFEST_JSON}")"
  MANIFEST_BRANCH="$(jq -r '.branch' <<<"${MANIFEST_JSON}")"
  MANIFEST_EXPECTED_SHA="$(jq -r '.expected_commit_sha // ""' <<<"${MANIFEST_JSON}")"

  [[ "${VALIDATED_ROOT}" == "${MANIFEST_WORKTREE}" ]] \
    || ai_die "--repo-root (${VALIDATED_ROOT}) does not exactly equal the run manifest's recorded worktree (${MANIFEST_WORKTREE}) — refusing."

  # Registered-worktree check: never the primary checkout (already
  # rejected above), never an unregistered sibling directory.
  REGISTERED_PRIMARY_ROOT="$(ai_require_registered_worktree "${VALIDATED_ROOT}")"
  [[ "${REGISTERED_PRIMARY_ROOT}" == "${PRIMARY_ROOT}" ]] \
    || ai_die "Worktree's primary repository (${REGISTERED_PRIMARY_ROOT}) does not match this script's own primary repository (${PRIMARY_ROOT}) — refusing (sibling-repository worktree)."

  EXPECTED_REPO_ID="$(ai_policy_get '.repository.id')"
  [[ "${MANIFEST_REPO_ID}" == "${EXPECTED_REPO_ID}" ]] \
    || ai_die "Run manifest's repository_id (${MANIFEST_REPO_ID}) does not match this policy's repository id (${EXPECTED_REPO_ID}) — refusing."

  ACTUAL_BRANCH="$(git -C "${VALIDATED_ROOT}" branch --show-current 2>/dev/null || true)"
  [[ "${ACTUAL_BRANCH}" == "${MANIFEST_BRANCH}" ]] \
    || ai_die "Worktree's actual current branch ('${ACTUAL_BRANCH}') does not match the run manifest's recorded branch ('${MANIFEST_BRANCH}') — refusing."

  [[ -n "${MANIFEST_EXPECTED_SHA}" ]] \
    || ai_die "Run manifest has no expected_commit_sha recorded yet — dispatch.sh must update the manifest with the committed SHA before calling verify.sh --mode dispatch."
  [[ "${MANIFEST_EXPECTED_SHA}" == "${EXPECTED_SHA_ARG}" ]] \
    || ai_die "--expected-sha (${EXPECTED_SHA_ARG}) does not match the run manifest's expected_commit_sha (${MANIFEST_EXPECTED_SHA}) — refusing."
  [[ "${TESTED_SHA}" == "${EXPECTED_SHA_ARG}" ]] \
    || ai_die "Worktree's actual HEAD (${TESTED_SHA}) does not match --expected-sha (${EXPECTED_SHA_ARG}) — refusing. The worktree changed after the manifest was written, or the wrong SHA was expected."

  ai_log_info "Dispatch-mode registered-worktree verification passed: worktree, branch, repository ID, and expected SHA all cross-checked against the run manifest three ways."
fi

# Force a deterministic, colorless environment before running anything.
# Discovered empirically: some invoking shells set FORCE_COLOR, which
# makes Rich (used by heimei's CLI) emit ANSI escape codes regardless of
# TTY detection — and several of heimei's own CLI tests assert on plain
# substrings (e.g. "4 managers"), so they fail under FORCE_COLOR even
# though nothing about the code itself is wrong. NO_COLOR is the
# standard override (https://no-color.org/) Rich respects; TERM=dumb is
# a second belt-and-suspenders signal; FORCE_COLOR=0 is set explicitly
# (not merely unset) to match .github/workflows/ci.yml's job-level env
# exactly, so local verification and CI never diverge on this. This
# changes verify.sh's own invocation environment only — it does not
# touch any file under Projects/Heimei.
export FORCE_COLOR=0
export NO_COLOR=1
export TERM=dumb

# HEIMEI_HOME must be the EXPLICIT, validated --repo-root — never
# inferred. heimei.config.settings.ConfigPaths.home defaults to
# Path.home()/"Heimei" (Path.home() reads $HOME), which is only
# correct when the checkout genuinely lives at $HOME/Heimei — true on
# a developer machine, false on a GitHub Actions runner (repo at
# $GITHUB_WORKSPACE, $HOME=/home/runner) and false for an automated
# dispatch worktree (which lives under Temp/ai-worktrees/, never
# $HOME/Heimei either). Without this, the project's real-runtime CLI
# tests silently resolve System/manifest/logging.yaml against the
# wrong root instead of the manifest actually committed in
# VALIDATED_ROOT. This is the one env var change that makes
# verification test the checkout verify.sh was actually told to test.
export HEIMEI_HOME="${VALIDATED_ROOT}"

# Run artifacts go in a stable, non-auto-cleaned directory so a --json
# summary's paths remain valid after this script exits (a prior version
# wrote JSON pointing into a mktemp dir that its own exit trap deleted).
# The parent must exist before mktemp can create inside it — mktemp
# does not mkdir -p for you, and silently falling back to /tmp on a
# missing parent would defeat the point of a stable, gitignored
# location. This directory is ALWAYS under the primary repository's
# Temp/ai-runs, never inside the checkout being tested — asserted
# explicitly below, not just by construction, per AI_WORKFLOW.md's
# "no transcript may be written inside the repository worktree."
#
# Computed HERE, before `cd "${PROJECT_DIR}"` below: ai_run_log_root()
# resolves the primary repository via `git rev-parse --show-toplevel`
# from the current working directory, and a linked worktree has its
# OWN toplevel distinct from the primary checkout's. Calling it after
# the cd would silently resolve "the primary repository" to the
# worktree being tested instead, making the safety check below trip on
# a false positive (a real correctly-placed transcript dir logged as if
# it were nested inside the worktree) for every worktree-based run.
RUN_LOG_PARENT="$(ai_run_log_root)"
mkdir -p "${RUN_LOG_PARENT}"
RUN_DIR="$(mktemp -d "${RUN_LOG_PARENT}/verify.XXXXXX")"

# Only meaningful (and only checked) when the tested checkout is a
# worktree, not the primary checkout — Temp/ai-runs legitimately lives
# inside the primary checkout's own tree (that's where run_log_root is
# defined relative to), so that combination is expected, not a defect.
if [[ "${VALIDATED_ROOT}" != "${PRIMARY_ROOT}" ]]; then
  case "$(ai_realpath_strict "${RUN_DIR}")" in
    "${VALIDATED_ROOT}"/*)
      ai_die "Refusing: transcript directory (${RUN_DIR}) resolved inside the tested worktree (${VALIDATED_ROOT}) — transcripts must never live inside a worktree."
      ;;
  esac
fi

cd "${PROJECT_DIR}"

CHANGED_PY_FILES=""
if [[ "${TEST_MODE}" == "fast" ]]; then
  CHANGED_PY_FILES="$(git -C "${VALIDATED_ROOT}" diff --name-only origin/main...HEAD -- '*.py' 2>/dev/null | sed "s#^Projects/Heimei/##" | grep -E '^(src|tests)/' || true)"
  if [[ -z "${CHANGED_PY_FILES}" ]]; then
    ai_log_warn "No changed .py files detected vs origin/main - falling back to --full for ruff/mypy."
    TEST_MODE="full"
  else
    ai_log_info "Fast mode - scoping ruff/mypy to:"
    while IFS= read -r f; do [[ -n "$f" ]] && ai_log_info "  ${f}"; done <<<"${CHANGED_PY_FILES}"
  fi
fi

SYNC_LOG="${RUN_DIR}/uv-sync.log"
PYTEST_LOG="${RUN_DIR}/pytest.log"
RUFF_LOG="${RUN_DIR}/ruff.log"
MYPY_LOG="${RUN_DIR}/mypy.log"

ai_run_check "uv sync --locked" "${SYNC_LOG}" uv sync --locked || true
SYNC_EXIT="${LAST_CHECK_EXIT}"; SYNC_CMD="${LAST_CHECK_CMD}"; SYNC_START="${LAST_CHECK_START}"; SYNC_END="${LAST_CHECK_END}"; SYNC_SHA256="${LAST_CHECK_SHA256}"; SYNC_EXCERPT="${LAST_CHECK_EXCERPT}"
if [[ "${SYNC_EXIT}" -ne 0 ]]; then
  ai_log_error "uv sync --locked failed — refusing to run tests against a possibly-inconsistent environment. Remaining checks are still recorded below with an explicit 'skipped' status, never a fabricated PASS."
fi

# pytest always runs in full - see usage() rationale above.
ai_run_check "pytest" "${PYTEST_LOG}" uv run pytest -q || true
PYTEST_EXIT="${LAST_CHECK_EXIT}"; PYTEST_CMD="${LAST_CHECK_CMD}"; PYTEST_START="${LAST_CHECK_START}"; PYTEST_END="${LAST_CHECK_END}"; PYTEST_SHA256="${LAST_CHECK_SHA256}"; PYTEST_EXCERPT="${LAST_CHECK_EXCERPT}"

if [[ "${TEST_MODE}" == "fast" ]]; then
  # shellcheck disable=SC2086
  ai_run_check "ruff check (changed files)" "${RUFF_LOG}" uv run ruff check ${CHANGED_PY_FILES} || true
else
  ai_run_check "ruff check ." "${RUFF_LOG}" uv run ruff check . || true
fi
RUFF_EXIT="${LAST_CHECK_EXIT}"; RUFF_CMD="${LAST_CHECK_CMD}"; RUFF_START="${LAST_CHECK_START}"; RUFF_END="${LAST_CHECK_END}"; RUFF_SHA256="${LAST_CHECK_SHA256}"; RUFF_EXCERPT="${LAST_CHECK_EXCERPT}"

if [[ "${TEST_MODE}" == "fast" ]]; then
  # shellcheck disable=SC2086
  ai_run_check "mypy (changed files)" "${MYPY_LOG}" uv run mypy ${CHANGED_PY_FILES} || true
else
  ai_run_check "mypy src/heimei" "${MYPY_LOG}" uv run mypy src/heimei || true
fi
MYPY_EXIT="${LAST_CHECK_EXIT}"; MYPY_CMD="${LAST_CHECK_CMD}"; MYPY_START="${LAST_CHECK_START}"; MYPY_END="${LAST_CHECK_END}"; MYPY_SHA256="${LAST_CHECK_SHA256}"; MYPY_EXCERPT="${LAST_CHECK_EXCERPT}"

EXIT_CODE=$(( (PYTEST_EXIT != 0 ? 1 : 0) | ((RUFF_EXIT != 0 ? 1 : 0) << 1) | ((MYPY_EXIT != 0 ? 1 : 0) << 2) | ((SYNC_EXIT != 0 ? 1 : 0) << 3) ))

echo
echo "================================================================================"
echo "Verification summary (mode: ${RUN_MODE}/${TEST_MODE})"
echo "================================================================================"
echo "  Repo root : ${VALIDATED_ROOT}"
echo "  Tested SHA: ${TESTED_SHA}"
printf '  uv sync   : %s (exit %s)\n' "$([[ ${SYNC_EXIT} -eq 0 ]] && echo PASS || echo FAIL)" "${SYNC_EXIT}"
printf '  pytest    : %s (exit %s)\n' "$([[ ${PYTEST_EXIT} -eq 0 ]] && echo PASS || echo FAIL)" "${PYTEST_EXIT}"
printf '  ruff check: %s (exit %s)\n' "$([[ ${RUFF_EXIT} -eq 0 ]] && echo PASS || echo FAIL)" "${RUFF_EXIT}"
printf '  mypy      : %s (exit %s)\n' "$([[ ${MYPY_EXIT} -eq 0 ]] && echo PASS || echo FAIL)" "${MYPY_EXIT}"
echo "--------------------------------------------------------------------------------"
if [[ "${EXIT_CODE}" -ne 0 ]]; then
  echo "One or more checks failed. Real transcripts under: ${RUN_DIR}"
fi
if [[ "${TEST_MODE}" == "fast" && "${EXIT_CODE}" -eq 0 ]]; then
  echo "NOTE: this was a --fast run. Full verification is still mandatory before PR readiness."
fi
echo "================================================================================"

if [[ -n "${JSON_OUT}" ]]; then
  ai_require_cmd jq
  mkdir -p "$(dirname "${JSON_OUT}")"
  [[ ! -L "${JSON_OUT}" ]] || ai_die "--json destination is a symlink, refusing: ${JSON_OUT}"
  jq -n \
    --arg repo_root "${VALIDATED_ROOT}" \
    --arg tested_sha "${TESTED_SHA}" \
    --arg run_mode "${RUN_MODE}" \
    --arg test_mode "${TEST_MODE}" \
    --argjson exit_code "${EXIT_CODE}" \
    --argjson sync_exit "${SYNC_EXIT}" --arg sync_cmd "${SYNC_CMD}" --arg sync_start "${SYNC_START}" --arg sync_end "${SYNC_END}" --arg sync_sha256 "${SYNC_SHA256}" --arg sync_excerpt "${SYNC_EXCERPT}" --arg sync_log "${SYNC_LOG}" \
    --argjson pytest_exit "${PYTEST_EXIT}" --arg pytest_cmd "${PYTEST_CMD}" --arg pytest_start "${PYTEST_START}" --arg pytest_end "${PYTEST_END}" --arg pytest_sha256 "${PYTEST_SHA256}" --arg pytest_excerpt "${PYTEST_EXCERPT}" --arg pytest_log "${PYTEST_LOG}" \
    --argjson ruff_exit "${RUFF_EXIT}" --arg ruff_cmd "${RUFF_CMD}" --arg ruff_start "${RUFF_START}" --arg ruff_end "${RUFF_END}" --arg ruff_sha256 "${RUFF_SHA256}" --arg ruff_excerpt "${RUFF_EXCERPT}" --arg ruff_log "${RUFF_LOG}" \
    --argjson mypy_exit "${MYPY_EXIT}" --arg mypy_cmd "${MYPY_CMD}" --arg mypy_start "${MYPY_START}" --arg mypy_end "${MYPY_END}" --arg mypy_sha256 "${MYPY_SHA256}" --arg mypy_excerpt "${MYPY_EXCERPT}" --arg mypy_log "${MYPY_LOG}" \
    --arg generated_at "$(ai_log_ts)" \
    '{generated_at: $generated_at, repo_root: $repo_root, tested_sha: $tested_sha,
      mode: $run_mode, test_mode: $test_mode, exit_code: $exit_code,
      checks: {
        uv_sync: {pass: ($sync_exit == 0), exit_code: $sync_exit, command: $sync_cmd, started_at: $sync_start, ended_at: $sync_end, transcript_sha256: $sync_sha256, transcript_excerpt: $sync_excerpt, log: $sync_log},
        pytest:  {pass: ($pytest_exit == 0), exit_code: $pytest_exit, command: $pytest_cmd, started_at: $pytest_start, ended_at: $pytest_end, transcript_sha256: $pytest_sha256, transcript_excerpt: $pytest_excerpt, log: $pytest_log},
        ruff:    {pass: ($ruff_exit == 0), exit_code: $ruff_exit, command: $ruff_cmd, started_at: $ruff_start, ended_at: $ruff_end, transcript_sha256: $ruff_sha256, transcript_excerpt: $ruff_excerpt, log: $ruff_log},
        mypy:    {pass: ($mypy_exit == 0), exit_code: $mypy_exit, command: $mypy_cmd, started_at: $mypy_start, ended_at: $mypy_end, transcript_sha256: $mypy_sha256, transcript_excerpt: $mypy_excerpt, log: $mypy_log}
      }}' \
    >"${JSON_OUT}"
  ai_log_info "Machine-readable summary (real transcripts, not synthetic PASS/FAIL): ${JSON_OUT} (full logs preserved under ${RUN_DIR})"
fi

exit "${EXIT_CODE}"
