#!/usr/bin/env bash
# Scripts/ai/dispatch.sh
#
# One-command local dispatcher for the Heimei AI development control
# plane. Takes an approved GitHub Issue and drives one named agent
# (Claude Code or Codex) through implementation, in an isolated git
# worktree, ending in a draft PR — never a merge, never a push to main.
# See AI_WORKFLOW.md for the policy this mechanically enforces.
#
# Usage:
#   ./Scripts/ai/dispatch.sh ISSUE_NUMBER --agent claude --dry-run
#   ./Scripts/ai/dispatch.sh ISSUE_NUMBER --agent claude --execute
#   ./Scripts/ai/dispatch.sh ISSUE_NUMBER --agent codex --execute
#
# Defaults to --dry-run. Nothing is created, committed, pushed, or
# opened as a PR without an explicit --execute.
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Configuration (overridable via environment for testing/tuning)
# ---------------------------------------------------------------------------

AI_DISPATCH_TIMEOUT_SECONDS="${AI_DISPATCH_TIMEOUT_SECONDS:-1200}"   # 20 min per agent invocation
AI_DISPATCH_MAX_BUDGET_USD="${AI_DISPATCH_MAX_BUDGET_USD:-5}"        # claude-only budget cap per invocation
AI_MAX_CORRECTIONS=2                                                 # +1 initial attempt = 3 max total

usage() {
  cat <<'EOF'
Usage: dispatch.sh ISSUE_NUMBER --agent <claude|codex> [--dry-run|--execute]
                    [--allow-db-migration-override]

  --agent claude|codex             Required. Must match the issue's own
                                    agent: label.
  --dry-run                        Validate everything and print the plan.
                                    Default if no execution flag is given.
  --execute                        Actually create the worktree, run the
                                    agent, verify, commit, push, and open
                                    a draft PR.
  --allow-db-migration-override    Required in addition to --execute if
                                    the issue carries database-migration.
                                    Still refuses on risk:high,
                                    frozen-subsystem, or breaking-change —
                                    those have no override.

Never runs two dispatch tasks at once (a local lock enforces this).
Never pushes to main. Never merges. Never marks a PR ready for review.
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

ISSUE_NUMBER=""
AGENT=""
EXECUTE=0
DB_OVERRIDE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="${2:-}"; shift 2 ;;
    --dry-run) EXECUTE=0; shift ;;
    --execute) EXECUTE=1; shift ;;
    --allow-db-migration-override) DB_OVERRIDE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) ai_log_error "Unknown flag: $1"; usage; exit 64 ;;
    *)
      if [[ -n "${ISSUE_NUMBER}" ]]; then
        ai_die "Unexpected extra positional argument: $1"
      fi
      ISSUE_NUMBER="$1"
      shift
      ;;
  esac
done

[[ -n "${ISSUE_NUMBER}" ]] || { ai_log_error "Missing ISSUE_NUMBER."; usage; exit 64; }
[[ "${AGENT}" == "claude" || "${AGENT}" == "codex" ]] || { ai_log_error "--agent must be 'claude' or 'codex'."; usage; exit 64; }

if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "DRY RUN — validating and printing the plan only. Pass --execute to actually act."
fi

# ---------------------------------------------------------------------------
# Validation phase (runs regardless of --dry-run/--execute)
# ---------------------------------------------------------------------------

ai_require_gh_auth
ai_require_cmd git
ai_require_cmd jq

REPO_ROOT="$(ai_repo_root)"
cd "${REPO_ROOT}"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "${CURRENT_BRANCH}" == "main" ]] || ai_die "Primary checkout is on '${CURRENT_BRANCH}', not main. Refusing — switch back to main first (this script only ever branches FROM main, and never touches your current checkout)."

if [[ -n "$(git status --porcelain)" ]]; then
  ai_die "Primary checkout ('main') has uncommitted changes. Commit or stash them first — dispatch.sh never touches your primary checkout's working tree, but it does read 'main' as the base for the new worktree, and an inconsistent base is a bad sign to proceed past."
fi

ai_log_info "Fetching issue #${ISSUE_NUMBER}..."
ISSUE_JSON="$(ai_issue_json "${ISSUE_NUMBER}")"
ISSUE_TITLE="$(printf '%s' "${ISSUE_JSON}" | jq -r '.title')"
ISSUE_BODY="$(printf '%s' "${ISSUE_JSON}" | jq -r '.body')"
ISSUE_URL="$(printf '%s' "${ISSUE_JSON}" | jq -r '.url')"

[[ "$(ai_issue_state "${ISSUE_JSON}")" == "OPEN" ]] || ai_die "Issue #${ISSUE_NUMBER} is not open."

if [[ "${DB_OVERRIDE}" -eq 1 ]]; then
  export AI_ALLOW_DB_MIGRATION_OVERRIDE=1
fi
ai_validate_issue_labels "${ISSUE_JSON}" "${AGENT}"
ai_log_info "Issue #${ISSUE_NUMBER} authorized for agent:${AGENT} — '${ISSUE_TITLE}'"

# ---------------------------------------------------------------------------
# CLI capability inspection — never assume obsolete syntax (see AI_WORKFLOW.md)
# ---------------------------------------------------------------------------

inspect_claude_cli() {
  ai_require_cmd claude
  local help_text
  help_text="$(claude --help 2>&1)"
  ai_log_info "claude version: $(claude --version 2>&1 | head -1)"
  for flag in "-p" "--output-format" "--permission-mode" "--allowedTools" "--max-budget-usd"; do
    grep -qF -- "${flag}" <<<"${help_text}" \
      || ai_log_warn "claude --help does not advertise '${flag}' in this installed version — invocation below may need adjusting."
  done
  if grep -qF -- "--max-turns" <<<"${help_text}"; then
    ai_log_info "This claude version supports --max-turns; consider adding it to run_claude() below."
  else
    ai_log_info "This claude version has no --max-turns flag — bounding is via 'timeout' (wall clock) and --max-budget-usd only."
  fi
}

inspect_codex_cli() {
  ai_require_cmd codex
  local help_text
  help_text="$(codex exec --help 2>&1)"
  ai_log_info "codex version: $(codex --version 2>&1 | head -1)"
  for flag in "--sandbox" "--json" "--output-last-message" "-C"; do
    grep -qF -- "${flag}" <<<"${help_text}" \
      || ai_log_warn "codex exec --help does not advertise '${flag}' in this installed version — invocation below may need adjusting."
  done
}

if [[ "${AGENT}" == "claude" ]]; then inspect_claude_cli; else inspect_codex_cli; fi

# ---------------------------------------------------------------------------
# Plan (printed in both dry-run and execute modes)
# ---------------------------------------------------------------------------

BRANCH_NAME="$(ai_branch_name "${ISSUE_NUMBER}" "${AGENT}" "${ISSUE_TITLE}")"
WORKTREE_PATH="$(ai_worktree_path "${BRANCH_NAME}")"
RUN_LOG_DIR="$(ai_run_log_dir "${ISSUE_NUMBER}")"
LOCK_PATH="${REPO_ROOT}/Temp/ai-runs/dispatch.lock"

cat <<EOF

================================================================================
Dispatch plan
================================================================================
  Issue:          #${ISSUE_NUMBER} — ${ISSUE_TITLE}
  Issue URL:      ${ISSUE_URL}
  Agent:          ${AGENT}
  Branch:         ${BRANCH_NAME}
  Worktree:       ${WORKTREE_PATH}
  Run log dir:    ${RUN_LOG_DIR}
  Timeout/attempt: ${AI_DISPATCH_TIMEOUT_SECONDS}s
  Max corrections: ${AI_MAX_CORRECTIONS} (${AI_MAX_CORRECTIONS} + 1 initial = $((AI_MAX_CORRECTIONS + 1)) attempts max)
  Mode:           $([[ "${EXECUTE}" -eq 1 ]] && echo EXECUTE || echo DRY-RUN)
================================================================================
EOF

if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "Dry run complete. Nothing was created. Re-run with --execute to actually dispatch."
  exit 0
fi

# ---------------------------------------------------------------------------
# Execute phase
# ---------------------------------------------------------------------------

mkdir -p "${RUN_LOG_DIR}"
ai_acquire_lock "${LOCK_PATH}"
trap ai_run_cleanup EXIT

ai_log_info "Creating isolated worktree at ${WORKTREE_PATH} (branch ${BRANCH_NAME}, from origin/main)"
git fetch origin main --quiet
git worktree add -b "${BRANCH_NAME}" "${WORKTREE_PATH}" origin/main
ai_register_cleanup "git -C '${REPO_ROOT}' worktree remove --force '${WORKTREE_PATH}' 2>/dev/null || true"

# ---------------------------------------------------------------------------
# Build the agent's briefing — repo docs by reference, issue body in full,
# explicit scope/verification/PR requirements. Never paste secrets here.
# ---------------------------------------------------------------------------

build_prompt() {
  local attempt="$1" prior_failure_log="${2:-}"
  local prompt_file="${RUN_LOG_DIR}/prompt-attempt-${attempt}.txt"
  {
    echo "You are the authorized implementer for Heimei GitHub issue #${ISSUE_NUMBER}, dispatched by Scripts/ai/dispatch.sh (agent: ${AGENT})."
    echo
    echo "Read these repository documents yourself before acting — do not assume you already know their content:"
    echo "  - AI_WORKFLOW.md (this task's authorization model and lifecycle)"
    echo "  - CONSTITUTION.md (how to evaluate any decision)"
    echo "  - PROJECT.md (current frozen-subsystem list)"
    echo "  - AGENTS.md (if you are Codex) or CLAUDE.md (if you are Claude Code)"
    echo "  - The ADR named in the issue body below, under System/docs/Architecture/, if one is named"
    echo "  - .github/PULL_REQUEST_TEMPLATE.md (the exact PR body shape required)"
    echo
    echo "You are working in an isolated git worktree at ${WORKTREE_PATH}, on branch ${BRANCH_NAME}. This is not the primary checkout — you may commit here. You may NOT push to main, merge anything, or mark this PR ready for review; a draft PR is the end of your authorization for this task."
    echo
    echo "=== Issue #${ISSUE_NUMBER}: ${ISSUE_TITLE} ==="
    echo "${ISSUE_BODY}"
    echo "=== end issue body ==="
    echo
    echo "Stay strictly within the Allowed scope and respect the Forbidden scope stated above. If you find you need to do anything on AI_WORKFLOW.md's 'never authorizes' list, or the scope is ambiguous in a way that changes what 'done' means, or you'd need to touch a frozen subsystem's behavior beyond what this issue explicitly approves, or you'd need to add a dependency not already named in scope: STOP. Write a clear one-paragraph explanation to a file named STOP_REASON.txt at the root of ${WORKTREE_PATH} and end your turn without further changes. Do not guess past an ambiguity."
    echo
    echo "Verification requirement: your implementation must pass, from Projects/Heimei: 'uv run pytest', 'uv run ruff check .', and 'uv run mypy src/heimei'. Run these yourself before finishing."
    echo
    echo "When you are done (or when you stop early per the paragraph above), leave the worktree in a state where 'git status' and 'git diff' clearly show only files within the issue's Allowed scope."
    if [[ -n "${prior_failure_log}" && -s "${prior_failure_log}" ]]; then
      echo
      echo "=== Previous attempt's verification failure (correction needed) ==="
      tail -c 8000 "${prior_failure_log}"
      echo "=== end previous failure ==="
    fi
  } >"${prompt_file}"
  printf '%s' "${prompt_file}"
}

# ---------------------------------------------------------------------------
# Agent invocation — kept in separate functions per agent, on purpose.
# Neither ever uses --dangerously-skip-permissions,
# --dangerously-bypass-approvals-and-sandbox, or any unrestricted-shell
# permission mode.
# ---------------------------------------------------------------------------

run_claude() {
  local prompt_file="$1" out_file="$2"
  (
    cd "${WORKTREE_PATH}"
    timeout "${AI_DISPATCH_TIMEOUT_SECONDS}" claude \
      -p \
      --output-format json \
      --permission-mode acceptEdits \
      --allowedTools "Read Edit Write Grep Glob Bash(git *) Bash(uv run *)" \
      --max-budget-usd "${AI_DISPATCH_MAX_BUDGET_USD}" \
      --add-dir "${WORKTREE_PATH}" \
      < "${prompt_file}" \
      > "${out_file}" 2>&1
  )
}

run_codex() {
  local prompt_file="$1" out_file="$2"
  (
    cd "${WORKTREE_PATH}"
    timeout "${AI_DISPATCH_TIMEOUT_SECONDS}" codex exec \
      --sandbox workspace-write \
      --json \
      -C "${WORKTREE_PATH}" \
      -o "${out_file}.last-message.txt" \
      - < "${prompt_file}" \
      > "${out_file}" 2>&1
  )
}

invoke_agent() {
  local prompt_file="$1" out_file="$2"
  if [[ "${AGENT}" == "claude" ]]; then
    run_claude "${prompt_file}" "${out_file}"
  else
    run_codex "${prompt_file}" "${out_file}"
  fi
}

# ---------------------------------------------------------------------------
# Bounded execution loop: 1 initial attempt + up to AI_MAX_CORRECTIONS
# corrections. Stops immediately (no further attempts) if the agent wrote
# STOP_REASON.txt, or if the timeout/agent process itself failed outright.
# ---------------------------------------------------------------------------

VERIFY_JSON="${RUN_LOG_DIR}/verify-result.json"
FINAL_STATUS="blocked"
STOP_REASON_FILE="${WORKTREE_PATH}/STOP_REASON.txt"

attempt=0
prior_failure_log=""
while [[ "${attempt}" -le "${AI_MAX_CORRECTIONS}" ]]; do
  attempt_label="initial"
  [[ "${attempt}" -gt 0 ]] && attempt_label="correction ${attempt}"
  ai_log_info "--- Attempt ${attempt} (${attempt_label}) ---"

  prompt_file="$(build_prompt "${attempt}" "${prior_failure_log}")"
  agent_out="${RUN_LOG_DIR}/agent-output-attempt-${attempt}.log"

  if ! invoke_agent "${prompt_file}" "${agent_out}"; then
    agent_exit=$?
    ai_log_error "Agent process exited ${agent_exit} (timeout is ${AI_DISPATCH_TIMEOUT_SECONDS}s) — see ${agent_out}"
    FINAL_STATUS="blocked"
    break
  fi

  if [[ -f "${STOP_REASON_FILE}" ]]; then
    ai_log_error "Agent requested a stop — see ${STOP_REASON_FILE}"
    cp "${STOP_REASON_FILE}" "${RUN_LOG_DIR}/STOP_REASON.txt"
    FINAL_STATUS="blocked"
    break
  fi

  ai_log_info "Running verification (Scripts/ai/verify.sh --full)..."
  if "${SCRIPT_DIR}/verify.sh" --full --json "${VERIFY_JSON}"; then
    ai_log_info "Verification passed on attempt ${attempt}."
    FINAL_STATUS="verified"
    break
  else
    ai_log_warn "Verification failed on attempt ${attempt}."
    prior_failure_log="${VERIFY_JSON}.pytest.log"
    FINAL_STATUS="blocked"
  fi

  attempt=$((attempt + 1))
done

if [[ "${FINAL_STATUS}" != "verified" ]]; then
  ai_log_error "Verification did not pass within ${AI_MAX_CORRECTIONS} correction attempt(s). Stopping per AI_WORKFLOW.md's bounded correction loop."
fi

# ---------------------------------------------------------------------------
# Commit — only inside the isolated worktree, never the primary checkout.
# `git add -A` is safe here specifically because this worktree was freshly
# branched from origin/main and contains nothing but this one task's diff
# (unlike the primary checkout, which deliberately holds untracked personal
# content alongside the project — see CLAUDE.md).
# ---------------------------------------------------------------------------

cd "${WORKTREE_PATH}"
ai_log_info "Worktree git status before commit:"
git status --short | tee "${RUN_LOG_DIR}/git-status-before-commit.txt" >&2 || true

HAS_CHANGES=0
if [[ -n "$(git status --porcelain)" ]]; then
  HAS_CHANGES=1
  git add -A
  git commit -m "$(printf 'feat: dispatch for issue #%s via %s\n\nSee %s.\n\nAutomated commit — Scripts/ai/dispatch.sh, agent: %s' "${ISSUE_NUMBER}" "${AGENT}" "${ISSUE_URL}" "${AGENT}")"
else
  ai_log_warn "No changes to commit — the agent made no modifications."
fi

if [[ "${FINAL_STATUS}" != "verified" ]]; then
  if [[ "${HAS_CHANGES}" -eq 1 ]]; then
    ai_log_info "Pushing branch anyway so work isn't lost — no PR will be opened, and status:blocked will be applied."
    git push -u origin "${BRANCH_NAME}"
  fi
  gh issue edit "${ISSUE_NUMBER}" --repo "$(ai_repo_slug)" --add-label "status:blocked" || true
  ai_log_error "Run summary: ${RUN_LOG_DIR}"
  exit 1
fi

ai_log_info "Pushing branch ${BRANCH_NAME}..."
git push -u origin "${BRANCH_NAME}"

PR_BODY_FILE="${RUN_LOG_DIR}/pr-body.md"
{
  echo "## Linked issue"
  echo
  echo "Closes #${ISSUE_NUMBER}"
  echo
  echo "## Architecture summary"
  echo
  echo "See issue #${ISSUE_NUMBER} for the approved scope. Implemented by agent: ${AGENT} via Scripts/ai/dispatch.sh."
  echo
  echo "## Verification commands and output"
  echo
  echo '```'
  jq -r '.checks | to_entries[] | "\(.key): \(if .value.pass then "PASS" else "FAIL" end)"' "${VERIFY_JSON}" 2>/dev/null || echo "see ${VERIFY_JSON}"
  echo '```'
  echo
  echo "Full logs: \`${VERIFY_JSON}\` and sibling \`.log\` files (local run artifacts, not committed)."
  echo
  echo "## Implementation agent"
  echo
  echo "${AGENT}"
  echo
  echo "## Review agent"
  echo
  echo "$([[ "${AGENT}" == "claude" ]] && echo codex || echo claude) — pending, run Scripts/ai/review.sh against this PR."
  echo
  echo "## Merge recommendation"
  echo
  echo "Automated draft — needs independent review and owner review before merge. Never auto-mark ready for review."
} >"${PR_BODY_FILE}"

ai_log_info "Opening draft PR..."
PR_URL="$(gh pr create \
  --repo "$(ai_repo_slug)" \
  --base main \
  --head "${BRANCH_NAME}" \
  --draft \
  --title "$(printf '%s (#%s)' "${ISSUE_TITLE}" "${ISSUE_NUMBER}")" \
  --body-file "${PR_BODY_FILE}")"

ai_log_info "Draft PR: ${PR_URL}"
gh issue edit "${ISSUE_NUMBER}" --repo "$(ai_repo_slug)" --add-label "status:review" || true

cat <<EOF

================================================================================
Run summary
================================================================================
  Issue:      #${ISSUE_NUMBER}
  Agent:      ${AGENT}
  Branch:     ${BRANCH_NAME}
  Attempts:   $((attempt + 1)) (1 initial + up to ${AI_MAX_CORRECTIONS} corrections)
  Result:     verified
  Draft PR:   ${PR_URL}
  Run log:    ${RUN_LOG_DIR}
================================================================================
Never marked ready for review, never merged — that's owner review and
Gokul's action, per AI_WORKFLOW.md.
EOF
