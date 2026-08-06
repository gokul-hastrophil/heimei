#!/usr/bin/env bash
# Scripts/ai/review.sh
#
# Runs the non-implementing agent as an independent reviewer against a
# PR. Read-only by default: fetches PR metadata and diff, identifies
# who implemented it, runs the *other* agent to produce findings, and
# prints them locally. Never pushes, never merges, never modifies the
# PR unless explicitly told to post a review. See AI_WORKFLOW.md,
# "one agent per implementation branch."
#
# Usage:
#   ./Scripts/ai/review.sh PR_NUMBER
#   ./Scripts/ai/review.sh PR_NUMBER --post
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

AI_REVIEW_TIMEOUT_SECONDS="${AI_REVIEW_TIMEOUT_SECONDS:-900}"

usage() {
  cat <<'EOF'
Usage: review.sh PR_NUMBER [--post] [--agent claude|codex]

  PR_NUMBER       Required. The pull request to review.
  --post          Post the review to the PR on GitHub. Default is local
                  output only.
  --agent NAME    Force the reviewer agent instead of auto-detecting
                  the "other" one from the PR body's Implementation
                  agent field.

Never pushes, never merges, never edits code. With --post, posts a
single PR review comment (via `gh pr review --comment`) — never
approves or requests changes automatically; that judgment is left to
the findings themselves and to Gokul.
EOF
}

PR_NUMBER=""
POST=0
FORCE_AGENT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --post) POST=1; shift ;;
    --agent) FORCE_AGENT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) ai_log_error "Unknown flag: $1"; usage; exit 64 ;;
    *)
      if [[ -n "${PR_NUMBER}" ]]; then ai_die "Unexpected extra positional argument: $1"; fi
      PR_NUMBER="$1"
      shift
      ;;
  esac
done

[[ -n "${PR_NUMBER}" ]] || { ai_log_error "Missing PR_NUMBER."; usage; exit 64; }

ai_require_gh_auth
ai_require_cmd jq
REPO="$(ai_repo_slug)"
REPO_ROOT="$(ai_repo_root)"

ai_log_info "Fetching PR #${PR_NUMBER} metadata and diff (read-only)..."
PR_JSON="$(gh pr view "${PR_NUMBER}" --repo "${REPO}" --json number,title,body,url,baseRefName,headRefName,labels,isDraft 2>/dev/null)" \
  || ai_die "PR #${PR_NUMBER} not found or not readable."
PR_TITLE="$(printf '%s' "${PR_JSON}" | jq -r '.title')"
PR_BODY="$(printf '%s' "${PR_JSON}" | jq -r '.body')"
PR_URL="$(printf '%s' "${PR_JSON}" | jq -r '.url')"
PR_HEAD="$(printf '%s' "${PR_JSON}" | jq -r '.headRefName')"

PR_DIFF="$(gh pr diff "${PR_NUMBER}" --repo "${REPO}" 2>/dev/null)" || ai_die "Could not fetch diff for PR #${PR_NUMBER}."

# Identify the implementation agent from the PR body's own
# "Implementation agent" section (see .github/PULL_REQUEST_TEMPLATE.md),
# falling back to the branch name's ai/<agent>/... prefix.
IMPL_AGENT="$(printf '%s' "${PR_BODY}" | awk '/## Implementation agent/{found=1; next} found && NF {print; exit}' | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
if [[ "${IMPL_AGENT}" != "claude" && "${IMPL_AGENT}" != "codex" ]]; then
  IMPL_AGENT="$(printf '%s' "${PR_HEAD}" | sed -n 's#^ai/\(claude\|codex\)/.*#\1#p')"
fi
[[ -n "${IMPL_AGENT}" ]] || ai_log_warn "Could not determine the implementing agent from the PR body or branch name — proceeding without excluding it."

REVIEW_AGENT="${FORCE_AGENT}"
if [[ -z "${REVIEW_AGENT}" ]]; then
  if [[ "${IMPL_AGENT}" == "claude" ]]; then
    REVIEW_AGENT="codex"
  elif [[ "${IMPL_AGENT}" == "codex" ]]; then
    REVIEW_AGENT="claude"
  else
    ai_die "Cannot auto-detect the reviewer agent (implementer unknown) — pass --agent explicitly."
  fi
fi

if [[ "${REVIEW_AGENT}" == "${IMPL_AGENT}" ]]; then
  ai_die "Reviewer agent (${REVIEW_AGENT}) matches the implementer (${IMPL_AGENT}) — refusing. See AI_WORKFLOW.md, 'one agent per implementation branch': an agent never reviews its own work."
fi

ai_log_info "PR #${PR_NUMBER}: '${PR_TITLE}' — implemented by ${IMPL_AGENT:-unknown}, reviewing as ${REVIEW_AGENT}"

RUN_LOG_DIR="${REPO_ROOT}/Temp/ai-runs/review-pr-${PR_NUMBER}-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${RUN_LOG_DIR}"

PROMPT_FILE="${RUN_LOG_DIR}/review-prompt.txt"
{
  echo "You are ${REVIEW_AGENT}, acting as the independent reviewer for Heimei PR #${PR_NUMBER} — implemented by ${IMPL_AGENT:-an unknown agent}, never by you (see AI_WORKFLOW.md, 'one agent per implementation branch')."
  echo
  echo "Read AI_WORKFLOW.md, CONSTITUTION.md, and PROJECT.md yourself before judging anything below."
  echo
  echo "You are READ-ONLY: do not edit any file, do not run git commands that change state, do not push, do not merge. Your only output is a structured review."
  echo
  echo "Check, specifically:"
  echo "  1. Architecture fit — does this match the linked issue's approved scope and the relevant ADR, if any?"
  echo "  2. Acceptance criteria — does the diff actually satisfy what the issue's Acceptance criteria section states?"
  echo "  3. Tests — are they present, meaningful, and do they actually exercise the new/changed behavior?"
  echo "  4. Security — any credential exposure, unsafe shell construction, or unvalidated input?"
  echo "  5. Frozen-subsystem boundaries — does the diff touch Configuration, Core Runtime, Logging, Inventory, Doctor, or Status (see PROJECT.md) without a separately-approved reason?"
  echo "  6. Migrations — any data/schema change needing a migration note?"
  echo "  7. Documentation — does the PR update whatever doc AI_WORKFLOW.md's 'Context update rules' says this change should update?"
  echo
  echo "Produce your findings as two lists: BLOCKING (must be fixed before merge) and NON-BLOCKING (worth noting, not required). If there are none of one kind, say so explicitly rather than omitting the section."
  echo
  echo "=== PR #${PR_NUMBER}: ${PR_TITLE} (${PR_URL}) ==="
  echo "${PR_BODY}"
  echo "=== end PR body ==="
  echo
  echo "=== Diff ==="
  printf '%s' "${PR_DIFF}" | head -c 60000
  echo
  echo "=== end diff (truncated at 60000 chars if longer) ==="
} >"${PROMPT_FILE}"

OUT_FILE="${RUN_LOG_DIR}/review-output.log"

run_claude_reviewer() {
  timeout "${AI_REVIEW_TIMEOUT_SECONDS}" claude \
    -p \
    --output-format json \
    --permission-mode acceptEdits \
    --allowedTools "Read Grep Glob" \
    --max-budget-usd "${AI_DISPATCH_MAX_BUDGET_USD:-3}" \
    < "${PROMPT_FILE}" \
    > "${OUT_FILE}" 2>&1
}

run_codex_reviewer() {
  timeout "${AI_REVIEW_TIMEOUT_SECONDS}" codex exec \
    --sandbox read-only \
    --json \
    -C "${REPO_ROOT}" \
    -o "${OUT_FILE}.last-message.txt" \
    - < "${PROMPT_FILE}" \
    > "${OUT_FILE}" 2>&1
}

ai_log_info "Running ${REVIEW_AGENT} as reviewer (read-only sandbox, ${AI_REVIEW_TIMEOUT_SECONDS}s timeout)..."
if [[ "${REVIEW_AGENT}" == "claude" ]]; then
  ai_require_cmd claude
  run_claude_reviewer || ai_log_warn "Reviewer process exited non-zero — see ${OUT_FILE}"
else
  ai_require_cmd codex
  run_codex_reviewer || ai_log_warn "Reviewer process exited non-zero — see ${OUT_FILE}"
fi

echo
echo "================================================================================"
echo "Review output — PR #${PR_NUMBER}, reviewer: ${REVIEW_AGENT}"
echo "================================================================================"
cat "${OUT_FILE}"
echo "================================================================================"
ai_log_info "Full run artifacts: ${RUN_LOG_DIR}"

if [[ "${POST}" -eq 1 ]]; then
  ai_log_info "Posting review comment to PR #${PR_NUMBER} (--post given)..."
  {
    echo "Independent review by ${REVIEW_AGENT} (via Scripts/ai/review.sh) — implemented by ${IMPL_AGENT:-unknown}, reviewed by a different agent per AI_WORKFLOW.md."
    echo
    cat "${OUT_FILE}"
  } | gh pr review "${PR_NUMBER}" --repo "${REPO}" --comment --body-file -
  ai_log_info "Posted as a plain comment review — never an automatic approve/request-changes. Owner review and merge remain Gokul's action."
else
  ai_log_info "Local output only (default). Pass --post to publish this as a PR comment."
fi
