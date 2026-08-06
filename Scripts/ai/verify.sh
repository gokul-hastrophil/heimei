#!/usr/bin/env bash
# Scripts/ai/verify.sh
#
# Runs Heimei's real, existing checks from Projects/Heimei:
#   uv run pytest
#   uv run ruff check .
#   uv run mypy src/heimei
#
# This is the same evidence AI_WORKFLOW.md's "Evidence requirements"
# and .github/PULL_REQUEST_TEMPLATE.md ask every PR to paste — this
# script exists so that evidence is always produced the same way,
# not retyped by hand.
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

MODE="full"          # full | fast
JSON_OUT=""          # path to write machine-readable JSON, if requested

usage() {
  cat <<'EOF'
Usage: verify.sh [--full|--fast] [--json <path>]

  --full        Run pytest, ruff check ., and mypy src/heimei in full.
                Default. Mandatory before any PR leaves draft state.
  --fast        Scope ruff/mypy to files changed vs. origin/main only.
                pytest always runs in full - a fast test subset can
                silently miss a regression it should have caught, so
                that shortcut is never taken here.
  --json PATH   Also write a machine-readable JSON summary to PATH.

Exit code is a bitmask: bit0=pytest failed, bit1=ruff failed,
bit2=mypy failed. 0 means everything passed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) MODE="full"; shift ;;
    --fast) MODE="fast"; shift ;;
    --json) JSON_OUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) ai_log_error "Unknown argument: $1"; usage; exit 64 ;;
  esac
done

PROJECT_DIR="$(ai_project_dir)"
[[ -d "${PROJECT_DIR}" ]] || ai_die "Project directory not found: ${PROJECT_DIR}"
ai_require_cmd uv

# Force a deterministic, colorless environment before running anything.
# Discovered empirically: some invoking shells set FORCE_COLOR, which
# makes Rich (used by heimei's CLI) emit ANSI escape codes regardless of
# TTY detection — and several of heimei's own CLI tests assert on plain
# substrings (e.g. "4 managers"), so they fail under FORCE_COLOR even
# though nothing about the code itself is wrong. NO_COLOR is the
# standard override (https://no-color.org/) Rich respects; TERM=dumb is
# a second belt-and-suspenders signal. This changes verify.sh's own
# invocation environment only — it does not touch any file under
# Projects/Heimei.
unset FORCE_COLOR
export NO_COLOR=1
export TERM=dumb

cd "${PROJECT_DIR}"

CHANGED_PY_FILES=""
if [[ "${MODE}" == "fast" ]]; then
  CHANGED_PY_FILES="$(git diff --name-only origin/main...HEAD -- '*.py' 2>/dev/null | sed "s#^Projects/Heimei/##" | grep -E '^(src|tests)/' || true)"
  if [[ -z "${CHANGED_PY_FILES}" ]]; then
    ai_log_warn "No changed .py files detected vs origin/main - falling back to --full for ruff/mypy."
    MODE="full"
  else
    ai_log_info "Fast mode - scoping ruff/mypy to:"
    while IFS= read -r f; do [[ -n "$f" ]] && ai_log_info "  ${f}"; done <<<"${CHANGED_PY_FILES}"
  fi
fi

run_check() {
  # Usage: run_check <name> <log-file> <cmd...>
  local name="$1" log_file="$2"
  shift 2
  local cmd_str
  cmd_str="$(IFS=' '; echo "$*")"  # IFS is $'\n\t' at file scope; "$*" here would otherwise join with newlines
  ai_log_info "Running: ${name} (${cmd_str})"
  if "$@" >"${log_file}" 2>&1; then
    ai_log_info "PASS: ${name}"
    return 0
  else
    local status=$?
    ai_log_error "FAIL: ${name} (exit ${status}) - see ${log_file}"
    return 1
  fi
}

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/heimei-verify.XXXXXX")"
ai_register_cleanup "rm -rf '${WORKDIR}'"
trap ai_run_cleanup EXIT

PYTEST_LOG="${WORKDIR}/pytest.log"
RUFF_LOG="${WORKDIR}/ruff.log"
MYPY_LOG="${WORKDIR}/mypy.log"

pytest_ok=1
ruff_ok=1
mypy_ok=1

# pytest always runs in full - see usage() rationale above.
run_check "pytest" "${PYTEST_LOG}" uv run pytest -q && pytest_ok=0 || pytest_ok=1

if [[ "${MODE}" == "fast" ]]; then
  # shellcheck disable=SC2086
  run_check "ruff check (changed files)" "${RUFF_LOG}" uv run ruff check ${CHANGED_PY_FILES} && ruff_ok=0 || ruff_ok=1
  # shellcheck disable=SC2086
  run_check "mypy (changed files)" "${MYPY_LOG}" uv run mypy ${CHANGED_PY_FILES} && mypy_ok=0 || mypy_ok=1
else
  run_check "ruff check ." "${RUFF_LOG}" uv run ruff check . && ruff_ok=0 || ruff_ok=1
  run_check "mypy src/heimei" "${MYPY_LOG}" uv run mypy src/heimei && mypy_ok=0 || mypy_ok=1
fi

EXIT_CODE=$(( pytest_ok | (ruff_ok << 1) | (mypy_ok << 2) ))

echo
echo "================================================================================"
echo "Verification summary (mode: ${MODE})"
echo "================================================================================"
printf '  pytest              : %s\n' "$([[ ${pytest_ok} -eq 0 ]] && echo PASS || echo FAIL)"
printf '  ruff check           : %s\n' "$([[ ${ruff_ok} -eq 0 ]] && echo PASS || echo FAIL)"
printf '  mypy                 : %s\n' "$([[ ${mypy_ok} -eq 0 ]] && echo PASS || echo FAIL)"
echo "--------------------------------------------------------------------------------"
if [[ "${EXIT_CODE}" -ne 0 ]]; then
  echo "One or more checks failed. Logs:"
  [[ "${pytest_ok}" -ne 0 ]] && echo "  pytest: ${PYTEST_LOG}"
  [[ "${ruff_ok}" -ne 0 ]] && echo "  ruff:   ${RUFF_LOG}"
  [[ "${mypy_ok}" -ne 0 ]] && echo "  mypy:   ${MYPY_LOG}"
fi
if [[ "${MODE}" == "fast" && "${EXIT_CODE}" -eq 0 ]]; then
  echo "NOTE: this was a --fast run. Full verification is still mandatory before PR readiness."
fi
echo "================================================================================"

if [[ -n "${JSON_OUT}" ]]; then
  mkdir -p "$(dirname "${JSON_OUT}")"
  jq -n \
    --arg mode "${MODE}" \
    --argjson pytest_pass "$([[ ${pytest_ok} -eq 0 ]] && echo true || echo false)" \
    --argjson ruff_pass "$([[ ${ruff_ok} -eq 0 ]] && echo true || echo false)" \
    --argjson mypy_pass "$([[ ${mypy_ok} -eq 0 ]] && echo true || echo false)" \
    --argjson exit_code "${EXIT_CODE}" \
    --arg pytest_log "${PYTEST_LOG}" \
    --arg ruff_log "${RUFF_LOG}" \
    --arg mypy_log "${MYPY_LOG}" \
    --arg generated_at "$(ai_log_ts)" \
    '{generated_at: $generated_at, mode: $mode, exit_code: $exit_code,
      checks: {pytest: {pass: $pytest_pass, log: $pytest_log},
               ruff: {pass: $ruff_pass, log: $ruff_log},
               mypy: {pass: $mypy_pass, log: $mypy_log}}}' \
    >"${JSON_OUT}"
  # Logs referenced above live under a mktemp dir cleaned up on exit -
  # copy the JSON's own referenced logs alongside it so it stays useful.
  cp "${PYTEST_LOG}" "${JSON_OUT}.pytest.log" 2>/dev/null || true
  cp "${RUFF_LOG}" "${JSON_OUT}.ruff.log" 2>/dev/null || true
  cp "${MYPY_LOG}" "${JSON_OUT}.mypy.log" 2>/dev/null || true
  ai_log_info "Machine-readable summary: ${JSON_OUT}"
fi

exit "${EXIT_CODE}"
