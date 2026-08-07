#!/usr/bin/env bash
# Scripts/ai/dispatch.sh
#
# One-command local dispatcher for the Heimei AI development control
# plane — supervised v1. Validates a trusted approval record (not
# labels — see AI_WORKFLOW.md, "labels are state, not authority"),
# fails closed unless branch protection on the target branch is
# actually confirmed, fails closed unless the approval's base SHA
# still exactly equals origin/main's current SHA, atomically claims
# the issue+approval via GitHub's create-reference API (never a plain
# branch push as the claim), runs Claude — with NO Bash tool at all —
# in an isolated, registered worktree, verifies the EXACT committed
# SHA against a dispatcher-owned run manifest, and only then pushes
# that same SHA and opens a draft PR. Failed or unverified work is
# never pushed, never gets a PR, and its worktree is never deleted.
#
# Codex is NOT a supported automated implementation agent in v1 — see
# "Codex implementation is disabled" below.
#
# Usage:
#   ./Scripts/ai/dispatch.sh ISSUE_NUMBER --agent claude --dry-run
#   ./Scripts/ai/dispatch.sh ISSUE_NUMBER --agent claude --execute
#
# Defaults to --dry-run. No branch, commit, push, label change, comment,
# or PR happens without an explicit --execute.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

AI_DISPATCH_TIMEOUT_SECONDS="${AI_DISPATCH_TIMEOUT_SECONDS:-1200}"
AI_DISPATCH_KILL_AFTER_SECONDS="${AI_DISPATCH_KILL_AFTER_SECONDS:-30}"
AI_MAX_CORRECTIONS=2

usage() {
  cat <<'EOF'
Usage: dispatch.sh ISSUE_NUMBER --agent claude [--dry-run|--execute]

  --agent claude          Required, and currently the ONLY supported
                          value for automated dispatch. Codex automated
                          implementation is disabled in v1 (see below).
  --dry-run              Validate everything and print the plan. Default.
  --execute               Actually claim, work, verify, push, and open a
                          draft PR.

Codex implementation is disabled: `--agent codex` fails immediately
with a clear message. There is no override flag — a proven sandbox and
network isolation boundary for Codex does not exist yet (see
AI_WORKFLOW.md, "Codex implementation is disabled").

Claude runs with NO Bash tool at all in this script — Read/Edit/
Write/Grep/Glob only. It does not run tests and does not touch git in
any way; the trusted dispatcher supplies all needed repository context
directly in the prompt and performs the commit, verification, and push
itself, only after Claude's changes pass mechanical scope validation.

There is no database-migration or dependency-change override in v1 —
those, and every frozen-subsystem/control-plane path, are hard-denied
regardless of the issue's own Allowed-paths list or labels.

On any failure (agent error, timeout, scope violation, verification
failure, provenance failure, stale approval, branch-protection check
failure, claim failure, push failure, unexpected file, review
failure): nothing is pushed, no PR is opened, no STOP_REASON.txt or
other artifact is written into the repository, and the worktree is
preserved exactly as it was, never removed.
EOF
}

ISSUE_NUMBER=""
AGENT=""
EXECUTE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="${2:-}"; shift 2 ;;
    --dry-run) EXECUTE=0; shift ;;
    --execute) EXECUTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) ai_log_error "Unknown flag: $1"; usage; exit 64 ;;
    *)
      if [[ -n "${ISSUE_NUMBER}" ]]; then ai_die "Unexpected extra positional argument: $1"; fi
      ISSUE_NUMBER="$1"
      shift
      ;;
  esac
done

[[ -n "${ISSUE_NUMBER}" ]] || { ai_log_error "Missing ISSUE_NUMBER."; usage; exit 64; }
ai_validate_positive_int "${ISSUE_NUMBER}" "issue number"
[[ -n "${AGENT}" ]] || { ai_log_error "Missing --agent."; usage; exit 64; }

# ---------------------------------------------------------------------------
# Codex implementation is disabled in v1 — checked before ANYTHING
# else (no gh call, no policy lookup) so this failure is instant and
# unconditional, never dependent on network/auth state. There is no
# silent fallback to a different agent: this is a hard stop.
# ---------------------------------------------------------------------------

if [[ "${AGENT}" == "codex" ]]; then
  ai_die "Automated Codex implementation is disabled until a proven sandbox and network isolation boundary is available."
fi
[[ "${AGENT}" == "claude" ]] || ai_die "Unsupported --agent '${AGENT}' — only 'claude' is supported for automated implementation in v1."

if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "DRY RUN — validating and printing the plan only. Pass --execute to actually act."
fi

# ---------------------------------------------------------------------------
# Non-mutating validation phase — runs identically in dry-run and execute.
# ---------------------------------------------------------------------------

ai_require_gh_auth
ai_require_cmd git
ai_require_cmd jq
ai_verify_repo_identity
REPO="$(ai_repo_slug)"
REPO_ID="$(ai_policy_get '.repository.id')"

ALLOWED_AGENTS="$(ai_policy_get_array '.agents.allowed[]')"
grep -qxF "${AGENT}" <<<"${ALLOWED_AGENTS}" || ai_die "Agent '${AGENT}' is not in .ai/policy.toml's allowed agents."

REPO_ROOT="$(ai_repo_root)"
cd "${REPO_ROOT}"

# --- Claude tool-surface preflight: fail closed, don't assume ------------
#
# ai_require_safe_claude_tool_surface (common.sh) inspects the
# installed CLI's --help for every flag this design's invocation
# depends on to mechanically restrict the tool surface. If any is
# missing, dispatch refuses outright with a fixed message rather than
# silently falling back to a weaker (unproven) tool grant.
ai_require_safe_claude_tool_surface

# --- Branch protection: fail closed, never a warning ----------------------

PROTECTED_BRANCH="$(ai_policy_get '.branch.protected')"
ai_require_branch_protection "${PROTECTED_BRANCH}"

# --- Base-SHA freshness (check #1 of 3: before any remote mutation) ------
# Performed again immediately after the approval record is parsed,
# below — this early call only establishes that a fresh check is even
# possible (fetch works) before spending time on the rest of
# validation.

ai_require_fresh_base_sha_helper_probe() {
  git fetch origin "${PROTECTED_BRANCH}" --quiet 2>/dev/null \
    || ai_die "Could not fetch origin/${PROTECTED_BRANCH} — failing closed before proceeding further."
}
ai_require_fresh_base_sha_helper_probe

# ---------------------------------------------------------------------------
# Approval + claim validation
# ---------------------------------------------------------------------------

ISSUE_JSON="$(ai_issue_json "${ISSUE_NUMBER}")"
[[ "$(ai_issue_state "${ISSUE_JSON}")" == "OPEN" ]] || ai_die "Issue #${ISSUE_NUMBER} is not open."
ISSUE_TITLE="$(printf '%s' "${ISSUE_JSON}" | jq -r '.title')"
ISSUE_BODY="$(ai_issue_body_from_json "${ISSUE_JSON}")"
ISSUE_URL="$(printf '%s' "${ISSUE_JSON}" | jq -r '.url')"
CURRENT_DIGEST="$(ai_issue_digest_from_json "${ISSUE_JSON}")"

LABELS="$(ai_issue_label_names "${ISSUE_JSON}")"
for blocking in "frozen-subsystem" "breaking-change" "database-migration" "dependency-change"; do
  grep -qxF "${blocking}" <<<"${LABELS}" && ai_die "Issue carries blocking label '${blocking}' — no override exists in v1."
done
# risk:high is rejected below via ai_require_single_risk_label +
# APPROVAL_RISK checks, not this loop — that path also verifies
# exactly one risk:* label exists and that it agrees with the
# approval record, which this loop alone cannot do.

# Find the newest approval-record comment (by the marker), validate it
# strictly, and stop at the first one considered rather than trying
# older ones — an approval either validates or dispatch fails closed.
APPROVAL_COMMENT_JSON="$(printf '%s' "${ISSUE_JSON}" | jq -c '
  [.comments[]? | select(.body | contains("<!-- heimei-approval:v1 -->"))] | sort_by(.createdAt) | last
')"
[[ "${APPROVAL_COMMENT_JSON}" != "null" ]] || ai_die "No approval record found on issue #${ISSUE_NUMBER}. Run Scripts/ai/approve.sh first."

APPROVAL_AUTHOR="$(printf '%s' "${APPROVAL_COMMENT_JSON}" | jq -r '.author.login')"
APPROVAL_COMMENT_BODY="$(printf '%s' "${APPROVAL_COMMENT_JSON}" | jq -r '.body')"
APPROVAL_COMMENT_ID="$(printf '%s' "${APPROVAL_COMMENT_JSON}" | jq -r '.id // empty')"

ai_require_approver "${APPROVAL_AUTHOR}"

RECORD_JSON="$(printf '%s' "${APPROVAL_COMMENT_BODY}" | sed -n '/```json/,/```/p' | sed '1d;$d')"
[[ -n "${RECORD_JSON}" ]] || ai_die "Approval comment did not contain a parseable JSON record."
printf '%s' "${RECORD_JSON}" | jq -e '.schema == "heimei-approval/v1"' >/dev/null 2>&1 \
  || ai_die "Approval record has an unrecognized schema."

APPROVAL_ID="$(printf '%s' "${RECORD_JSON}" | jq -r '.approval_id')"
ai_validate_approval_id "${APPROVAL_ID}"
APPROVAL_REPO_ID="$(printf '%s' "${RECORD_JSON}" | jq -r '.repository_id')"
APPROVAL_ISSUE_NUMBER="$(printf '%s' "${RECORD_JSON}" | jq -r '.issue_number')"
APPROVAL_APPROVER_FIELD="$(printf '%s' "${RECORD_JSON}" | jq -r '.approver')"
APPROVAL_AGENT="$(printf '%s' "${RECORD_JSON}" | jq -r '.agent')"
APPROVAL_RISK="$(printf '%s' "${RECORD_JSON}" | jq -r '.risk')"
APPROVAL_DIGEST="$(printf '%s' "${RECORD_JSON}" | jq -r '.issue_body_digest')"
APPROVAL_BASE_SHA="$(printf '%s' "${RECORD_JSON}" | jq -r '.base_sha')"
ALLOWED_PATHS_NEWLINE="$(printf '%s' "${RECORD_JSON}" | jq -r '.allowed_paths[]')"

# The comment's REAL author (from GitHub's own metadata) must match the
# approver claimed inside the record body — the body text alone is not
# trusted, since anyone could post a comment whose text merely claims
# to be from an allowed approver.
[[ "${APPROVAL_AUTHOR}" == "${APPROVAL_APPROVER_FIELD}" ]] \
  || ai_die "Approval record's claimed approver ('${APPROVAL_APPROVER_FIELD}') does not match the comment's actual GitHub author ('${APPROVAL_AUTHOR}')."
[[ "${APPROVAL_REPO_ID}" == "${REPO_ID}" ]] || ai_die "Approval record's repository_id does not match this repository."
[[ "${APPROVAL_ISSUE_NUMBER}" == "${ISSUE_NUMBER}" ]] || ai_die "Approval record's issue_number does not match #${ISSUE_NUMBER}."
[[ "${APPROVAL_AGENT}" == "${AGENT}" ]] || ai_die "Approval record authorizes agent '${APPROVAL_AGENT}', not requested agent '${AGENT}'."
[[ "${APPROVAL_DIGEST}" == "${CURRENT_DIGEST}" ]] \
  || ai_die "Issue body digest has changed since approval (approved: ${APPROVAL_DIGEST}, current: ${CURRENT_DIGEST}) — the issue was edited after approval. Approval is invalid; re-run approve.sh."

# --- Risk: one source of truth, re-derived from live labels every run ----
# Never trust the approval record's own risk field alone — the issue's
# risk:* label is state that lives outside the issue body (so the
# digest check above can't catch a label change), and it must agree
# with the approval record every single dispatch, not just at
# approval time.
CURRENT_ISSUE_RISK="$(ai_require_single_risk_label "${LABELS}")"
[[ "${APPROVAL_RISK}" == "low" || "${APPROVAL_RISK}" == "medium" ]] \
  || ai_die "Approval record's risk ('${APPROVAL_RISK}') is not dispatchable — only low/medium are ever dispatchable in v1; high is never dispatchable regardless of any other state, including a crafted historical approval record."
[[ "${APPROVAL_RISK}" == "${CURRENT_ISSUE_RISK}" ]] \
  || ai_die "Approval record's risk (${APPROVAL_RISK}) no longer matches the issue's current risk:${CURRENT_ISSUE_RISK} label — the label changed after approval. Refusing."

# Mechanically re-validate that no allowed-path line names a dependency
# manifest, a migration path, or anything else hard-denylisted — an
# approval record predating a policy change, or one whose allowed-paths
# validation had a bug at approval time, is still re-checked here
# independently, every single dispatch.
while IFS= read -r allowed_line; do
  [[ -n "${allowed_line}" ]] || continue
  ai_path_is_denylisted "${allowed_line}" \
    && ai_die "Approval record's allowed_paths includes a hard-denylisted path/pattern ('${allowed_line}') — refusing regardless of when this approval was created."
done <<<"${ALLOWED_PATHS_NEWLINE}"

# --- Base-SHA freshness (check #2 of 3: exact match, not "ancestor") ------

ai_require_fresh_base_sha "${APPROVAL_BASE_SHA}"

ai_log_info "Approval ${APPROVAL_ID} valid: approver=${APPROVAL_AUTHOR} agent=${APPROVAL_AGENT} risk=${APPROVAL_RISK} base=${APPROVAL_BASE_SHA:0:12} (exactly matches current origin/${PROTECTED_BRANCH})"

# ---------------------------------------------------------------------------
# Plan (printed in both dry-run and execute modes)
# ---------------------------------------------------------------------------

BRANCH_NAME="$(ai_branch_name "${ISSUE_NUMBER}" "${AGENT}" "${ISSUE_TITLE}")"
ai_validate_branch_name "${BRANCH_NAME}"
CLAIM_REF="$(ai_claim_ref_name "${ISSUE_NUMBER}" "${APPROVAL_ID}")"
WORKTREE_PATH="$(ai_worktree_path "${BRANCH_NAME}")"
RUN_ID="run-${ISSUE_NUMBER}-$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG_DIR="$(ai_run_log_root)/${RUN_ID}"
RUN_MANIFEST_PATH="$(ai_run_manifest_root)/${RUN_ID}.json"
LOCK_PATH="$(ai_run_log_root)/dispatch.lock"

# --- Duplicate-claim / active-PR-collision / prior-attestation check -----
# Approval consumption is judged from the claim ref and PR/attestation
# state — never from a label alone.

# A failed `gh pr list` call must never be silently treated as "no PR
# exists" — that would be a fail-OPEN outcome for a duplicate-claim
# check. Checked explicitly, not `|| true`.
if ! EXISTING_PR_JSON="$(gh pr list --repo "${REPO}" --head "${BRANCH_NAME}" --json number,state 2>/dev/null)"; then
  ai_die "Could not query existing PRs for branch '${BRANCH_NAME}' — failing closed rather than assuming none exist."
fi
EXISTING_PR="$(jq -r '.[0].number // empty' <<<"${EXISTING_PR_JSON}")"
[[ -z "${EXISTING_PR}" ]] \
  || ai_die "An active PR (#${EXISTING_PR}) already references branch '${BRANCH_NAME}' — this approval has already been consumed. Refusing (duplicate claim)."

EXISTING_ATTESTATION="$(printf '%s' "${ISSUE_JSON}" | jq -c --arg id "${APPROVAL_ID}" '
  [.comments[]? | select(.body | contains("<!-- heimei-attestation:v1 -->")) | select(.body | contains($id))] | length
')"
[[ "${EXISTING_ATTESTATION}" == "0" ]] \
  || ai_die "A dispatch attestation for approval ${APPROVAL_ID} already exists on issue #${ISSUE_NUMBER} — this approval has already been consumed. Refusing (duplicate claim)."

# A claim is deliberately non-resumable in supervised v1 (see the
# execute-phase comment below for the full rationale). This dry-run-only
# check exists purely to print an accurate, honest plan — it looks at
# the claim ref's existence to inform the operator, but makes NO
# ownership decision from what it sees and drives no different
# execution-phase behavior: the execute phase always attempts exactly
# one create-reference call regardless of what this printed. A
# pre-existing ref of ANY SHA means dispatch will fail at the claim
# step; there is no "same SHA, so it's still mine" case.
CLAIM_REF_REMOTE_SHA="$(git ls-remote origin "${CLAIM_REF}" 2>/dev/null | cut -f1)"
if [[ -n "${CLAIM_REF_REMOTE_SHA}" ]]; then
  ai_die "Claim ref '${CLAIM_REF}' already exists (at ${CLAIM_REF_REMOTE_SHA:0:12}) — this approval has already been claimed or is already in progress. A claim is deliberately non-resumable in supervised v1: an ambiguous or interrupted claimed run requires owner inspection and a new approval, never an automatic resume. Refusing."
fi

cat <<EOF

================================================================================
Dispatch plan (supervised v1)
================================================================================
  Issue:           #${ISSUE_NUMBER} — ${ISSUE_TITLE}
  Issue URL:       ${ISSUE_URL}
  Approval ID:     ${APPROVAL_ID}
  Approval author: ${APPROVAL_AUTHOR}
  Agent:           ${AGENT} (no Bash tool; read/edit/write/grep/glob only)
  Risk:            ${APPROVAL_RISK}
  Base SHA:        ${APPROVAL_BASE_SHA} (confirmed == current origin/${PROTECTED_BRANCH})
  Claim ref:       ${CLAIM_REF} (single-attempt create-ref, non-resumable)
  Branch:          ${BRANCH_NAME}
  Worktree:        ${WORKTREE_PATH}
  Run ID:          ${RUN_ID}
  Run log dir:     ${RUN_LOG_DIR}
  Run manifest:    ${RUN_MANIFEST_PATH}
  Timeout/attempt: ${AI_DISPATCH_TIMEOUT_SECONDS}s (kill-after ${AI_DISPATCH_KILL_AFTER_SECONDS}s)
  Max corrections: ${AI_MAX_CORRECTIONS} (+1 initial = $((AI_MAX_CORRECTIONS + 1)) attempts max)
  Mode:            $([[ "${EXECUTE}" -eq 1 ]] && echo EXECUTE || echo DRY-RUN)
================================================================================
EOF

if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "Dry run complete. Nothing was created, claimed, or mutated. Re-run with --execute to actually dispatch."
  exit 0
fi

# ---------------------------------------------------------------------------
# Execute phase — lock first, then repeat the validation above's
# GitHub-facing checks one more time (replay-resistance: re-check after
# acquiring the lock, since time has passed and another process could
# have changed remote state).
# ---------------------------------------------------------------------------

mkdir -p "${RUN_LOG_DIR}"
ai_acquire_lock "${LOCK_PATH}"
ai_trap_lock_only

# With `set -e` active (added specifically because a function's `exit`
# inside a `$(...)` command substitution only kills the subshell, not
# this script), any unguarded command failure from here on would
# otherwise abort via bash's own errexit mechanism, bypassing the
# "preserve the worktree and report clearly" promise this script makes
# everywhere else. This ERR trap closes that gap.
fail_and_preserve() {
  local reason="$1"
  ai_report_failure "${WORKTREE_PATH:-<not yet created>}" "${BRANCH_NAME:-<not yet claimed>}" "${reason}"
  exit 1
}
trap 'fail_and_preserve "unexpected command failure — see this run'\''s log directory for partial artifacts: '"${RUN_LOG_DIR}"'"' ERR

ai_log_info "Re-validating after acquiring the lock..."
ISSUE_JSON="$(ai_issue_json "${ISSUE_NUMBER}")"
[[ "$(ai_issue_state "${ISSUE_JSON}")" == "OPEN" ]] || ai_die "Issue #${ISSUE_NUMBER} is no longer open."
RECHECK_DIGEST="$(ai_issue_digest_from_json "${ISSUE_JSON}")"
[[ "${RECHECK_DIGEST}" == "${APPROVAL_DIGEST}" ]] || ai_die "Issue body changed between validation and lock acquisition. Refusing."
RECHECK_LABELS="$(ai_issue_label_names "${ISSUE_JSON}")"
RECHECK_ISSUE_RISK="$(ai_require_single_risk_label "${RECHECK_LABELS}")"
[[ "${APPROVAL_RISK}" == "${RECHECK_ISSUE_RISK}" ]] \
  || ai_die "Issue's risk:${RECHECK_ISSUE_RISK} label no longer matches approval risk (${APPROVAL_RISK}) — changed between validation and lock acquisition. Refusing."
if ! EXISTING_PR_JSON="$(gh pr list --repo "${REPO}" --head "${BRANCH_NAME}" --json number 2>/dev/null)"; then
  ai_die "Could not re-query existing PRs for branch '${BRANCH_NAME}' after acquiring the lock — failing closed rather than assuming none exist."
fi
EXISTING_PR="$(jq -r '.[0].number // empty' <<<"${EXISTING_PR_JSON}")"
[[ -z "${EXISTING_PR}" ]] || ai_die "An active PR (#${EXISTING_PR}) appeared for '${BRANCH_NAME}' between validation and lock acquisition. Refusing."

# --- Base-SHA freshness (check #3 of 3, immediately before the atomic claim)

ai_require_fresh_base_sha "${APPROVAL_BASE_SHA}"

# ---------------------------------------------------------------------------
# Atomic claim — GitHub create-reference API, exactly once, no resume.
#
# A claim is deliberately non-resumable in supervised v1: ANY
# pre-existing claim ref for this issue+approval — whatever its SHA,
# whoever or whatever created it, however recently — means this
# approval has already been consumed or is already being worked on.
# There is no code path here that inspects an existing ref's SHA to
# decide "that's still me, continue" (that was the exact defect fixed
# in this pass: a second machine losing the create-ref race could
# observe the first machine's same-SHA ref and wrongly proceed as if
# it owned the claim). ai_create_claim_ref is called exactly once; its
# only possible outcomes are success (this run now owns the claim) or
# failure (already claimed, or an ambiguous response — network
# timeout, malformed body, unexpected status — which is ALSO treated
# as failure, never as license to retry-as-owner). An ambiguous or
# interrupted claimed run requires owner inspection and a new
# approval — never an automatic resume.
# ---------------------------------------------------------------------------

ai_log_info "Claiming issue #${ISSUE_NUMBER}/approval ${APPROVAL_ID} atomically via the create-reference API (single attempt, no resume)..."
ai_create_claim_ref "${CLAIM_REF}" "${APPROVAL_BASE_SHA}"

ai_replace_status_label "${ISSUE_NUMBER}" "status:in-progress"

CLAIM_COMMENT_FILE="$(mktemp)"
{
  echo "## Heimei Dispatch Claim"
  echo
  echo '```json'
  jq -nc --arg run_id "${RUN_ID}" --arg approval_id "${APPROVAL_ID}" --arg approval_comment_id "${APPROVAL_COMMENT_ID}" \
    --arg repository_id "${REPO_ID}" --arg base_sha "${APPROVAL_BASE_SHA}" --arg branch "${BRANCH_NAME}" \
    --arg claim_ref "${CLAIM_REF}" --arg agent "${AGENT}" --arg timestamp "$(ai_log_ts)" \
    '{run_id: $run_id, approval_id: $approval_id, approval_comment_id: $approval_comment_id,
      repository_id: $repository_id, base_sha: $base_sha, branch: $branch, claim_ref: $claim_ref,
      agent: $agent, timestamp: $timestamp, schema: "heimei-claim/v1"}' | jq .
  echo '```'
  echo "<!-- heimei-claim:v1 -->"
} >"${CLAIM_COMMENT_FILE}"
gh issue comment "${ISSUE_NUMBER}" --repo "${REPO}" --body-file "${CLAIM_COMMENT_FILE}" >/dev/null
rm -f "${CLAIM_COMMENT_FILE}"
ai_log_info "Posted claim comment."

# ---------------------------------------------------------------------------
# Dispatcher-owned run manifest — written before the worktree exists,
# updated with the committed SHA once one exists. verify.sh --mode
# dispatch trusts nothing else.
# ---------------------------------------------------------------------------

ai_write_run_manifest "${RUN_MANIFEST_PATH}" "$(jq -nc \
  --arg run_id "${RUN_ID}" --arg repository_id "${REPO_ID}" --argjson issue_number "${ISSUE_NUMBER}" \
  --arg approval_id "${APPROVAL_ID}" --arg base_sha "${APPROVAL_BASE_SHA}" \
  --arg worktree_realpath "${WORKTREE_PATH}" --arg branch "${BRANCH_NAME}" \
  --arg created_at "$(ai_log_ts)" --argjson dispatcher_pid "$$" --arg dispatcher_host "$(hostname 2>/dev/null || echo unknown)" \
  '{schema: "heimei-run-manifest/v1", run_id: $run_id, repository_id: $repository_id,
    issue_number: $issue_number, approval_id: $approval_id, base_sha: $base_sha,
    worktree_realpath: $worktree_realpath, branch: $branch, expected_commit_sha: null,
    created_at: $created_at, dispatcher_pid: $dispatcher_pid, dispatcher_host: $dispatcher_host}')"

# ---------------------------------------------------------------------------
# Worktree setup — always fresh, never reused. Since claims are
# non-resumable (see above), a worktree directory that already exists
# at this path is not a legitimate "resume" case at all — it means a
# prior run got partway through and stopped, which is exactly the
# "requires owner inspection and a new approval" situation this pass's
# no-resume policy exists to surface, not paper over by silently
# reusing whatever's there.
# ---------------------------------------------------------------------------

if [[ -e "${WORKTREE_PATH}" ]]; then
  ai_report_failure "${WORKTREE_PATH}" "${BRANCH_NAME}" "A worktree directory already exists at ${WORKTREE_PATH} for a claim that was just confirmed fresh (this dispatch's own create-ref call just succeeded, so no prior successful claim should have left this here). This is unexpected and is not treated as resumable — inspect by hand before deciding what to do with it."
  exit 1
fi
mkdir -p "$(dirname "${WORKTREE_PATH}")"
git branch -f "${BRANCH_NAME}" "${APPROVAL_BASE_SHA}"
git worktree add "${WORKTREE_PATH}" "${BRANCH_NAME}" \
  || ai_die "Failed to create worktree at ${WORKTREE_PATH}."
# The worktree path recorded in the manifest must resolve to exactly
# what verify.sh will later see via --repo-root — re-write the
# manifest with the REALPATH now that the directory actually exists
# (WORKTREE_PATH above may not yet have been a real, resolvable path
# before `git worktree add` created it).
WORKTREE_REALPATH="$(ai_realpath_strict "${WORKTREE_PATH}")"
ai_write_run_manifest "${RUN_MANIFEST_PATH}" "$(jq -nc \
  --arg run_id "${RUN_ID}" --arg repository_id "${REPO_ID}" --argjson issue_number "${ISSUE_NUMBER}" \
  --arg approval_id "${APPROVAL_ID}" --arg base_sha "${APPROVAL_BASE_SHA}" \
  --arg worktree_realpath "${WORKTREE_REALPATH}" --arg branch "${BRANCH_NAME}" \
  --arg created_at "$(ai_log_ts)" --argjson dispatcher_pid "$$" --arg dispatcher_host "$(hostname 2>/dev/null || echo unknown)" \
  '{schema: "heimei-run-manifest/v1", run_id: $run_id, repository_id: $repository_id,
    issue_number: $issue_number, approval_id: $approval_id, base_sha: $base_sha,
    worktree_realpath: $worktree_realpath, branch: $branch, expected_commit_sha: null,
    created_at: $created_at, dispatcher_pid: $dispatcher_pid, dispatcher_host: $dispatcher_host}')"

# ---------------------------------------------------------------------------
# Build Claude's briefing — the dispatcher supplies EVERY piece of
# repository context Claude would otherwise have needed a shell for:
# current branch, base SHA, allowed paths, relevant source (Claude
# reads it itself via the Read/Grep/Glob tools it does have), issue
# requirements, and an explicit instruction not to inspect private
# paths.
# ---------------------------------------------------------------------------

build_prompt() {
  local attempt="$1" prior_failure_log="${2:-}"
  local prompt_file="${RUN_LOG_DIR}/prompt-attempt-${attempt}.txt"
  {
    echo "You are the authorized implementer for Heimei issue #${ISSUE_NUMBER}, dispatched by Scripts/ai/dispatch.sh (agent: claude, run ${RUN_ID})."
    echo
    echo "Read AI_WORKFLOW.md, CONSTITUTION.md, PROJECT.md, and Knowledge/Documentation/Standards.md yourself before acting (using the Read/Grep/Glob tools you have)."
    echo
    echo "You have NO shell access and NO git access of any kind in this session — no Bash tool is available to you at all, not even a restricted one. You cannot run tests, cannot inspect git status/diff/log, and cannot commit or push. This is deliberate (see AI_WORKFLOW.md, 'Claude implementation: no shell or Git authority') — CLI sandbox flags are not treated as a proven isolation boundary in this design, so the boundary here is simply not granting the tool at all."
    echo
    echo "Repository context, supplied directly since you cannot look it up yourself:"
    echo "  Current branch: ${BRANCH_NAME}"
    echo "  Base SHA (this branch's starting point): ${APPROVAL_BASE_SHA}"
    echo "  Worktree path: ${WORKTREE_PATH} (isolated — not the primary checkout)"
    echo
    echo "You are working inside that isolated git worktree. This is not the primary checkout. The trusted dispatcher performs the commit, all tests (pytest/ruff/mypy), and the push after you finish — you do not and cannot run tests yourself; the dispatcher runs them all after you finish, against the exact commit it creates from your changes."
    echo
    echo "Allowed paths (edit ONLY within these — anything else will be rejected mechanically, not by your own judgment):"
    printf '%s\n' "${ALLOWED_PATHS_NEWLINE}"
    echo
    echo "Do NOT inspect, read, or reference anything outside the worktree above, and do not attempt to read repository-external private paths (.envrc, Configs/, Knowledge/, Scripts/Backup/, cmd.txt, or anything else outside this worktree) — you have no tool that could reach them anyway, but do not attempt to."
    echo
    echo "=== Issue #${ISSUE_NUMBER}: ${ISSUE_TITLE} ==="
    echo "${ISSUE_BODY}"
    echo "=== end issue body ==="
    echo
    echo "If you believe you cannot complete this within the allowed paths, or the scope is ambiguous, or it would require touching a frozen subsystem, a dependency manifest, or a migration path: make NO changes and end your turn explaining why in your final response. Do not create any file to signal this — your final text response is read directly."
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
# Agent invocation — Claude only, with a mechanically-restricted tool
# surface. Never uses --dangerously-skip-permissions or any equivalent
# broadening flag.
#
# This invocation combines every flag ai_require_safe_claude_tool_surface
# just confirmed the installed CLI advertises, so the restriction is
# layered, not reliant on any single flag:
#   --tools               defines the ACTUAL AVAILABLE built-in tool set
#                          (stronger than a permission filter — Bash is
#                          not merely denied, it is not present at all)
#   --allowedTools         explicit allowlist, defense in depth on top
#                          of --tools
#   --disallowedTools       explicit Bash denial, defense in depth
#   --safe-mode             disables inherited CLAUDE.md, skills,
#                          plugins, hooks, MCP servers, custom
#                          commands/agents from user/project config
#   --strict-mcp-config     only the --mcp-config file below is used,
#                          ignoring any other MCP configuration source
#   --mcp-config            a dedicated, empty ({"mcpServers":{}})
#                          config — no MCP servers, no MCP tools
#   --setting-sources ""    loads no user/project/local settings files
#                          (which could otherwise add tools/hooks)
#
# Empirically probed live during this pass (bounded, harmless,
# non-mutating): with exactly this flag combination, the model's own
# self-report of its available tools was "Edit, Glob, Grep, Read,
# Write" (no Bash), and a direct request to run a shell command
# produced an empty permission_denials list with a plain "I don't have
# a shell/bash execution tool available" response — meaning Bash was
# never offered to the model at all, not merely denied after being
# offered. This is real evidence for THIS CLI version and THIS flag
# combination, not a config-flag assumption — but it is still a
# self-report from the model process, not an independent, cryptographic
# proof; see AI_WORKFLOW.md, "Claude tool-surface boundary," for the
# honest scope of this claim.
EMPTY_MCP_CONFIG="${RUN_LOG_DIR}/empty-mcp-config.json"
printf '{"mcpServers": {}}\n' >"${EMPTY_MCP_CONFIG}"

run_claude() {
  local prompt_file="$1" out_file="$2"
  (
    cd "${WORKTREE_PATH}"
    timeout --kill-after="${AI_DISPATCH_KILL_AFTER_SECONDS}" "${AI_DISPATCH_TIMEOUT_SECONDS}" claude \
      -p \
      --output-format json \
      --permission-mode acceptEdits \
      --tools "Read,Edit,Write,Grep,Glob" \
      --allowedTools "Read Edit Write Grep Glob" \
      --disallowedTools "Bash" \
      --safe-mode \
      --strict-mcp-config \
      --mcp-config "${EMPTY_MCP_CONFIG}" \
      --setting-sources "" \
      --max-budget-usd "${AI_DISPATCH_MAX_BUDGET_USD:-5}" \
      --add-dir "${WORKTREE_PATH}" \
      < "${prompt_file}" \
      > "${out_file}" 2>&1
  )
}

# ---------------------------------------------------------------------------
# Bounded execution + exact-commit lifecycle
# ---------------------------------------------------------------------------

# fail_and_preserve() is defined earlier, right after the lock is
# acquired — see the ERR trap registered there for why.

attempt=0
prior_failure_log=""
COMMITTED_SHA=""
VERIFY_JSON="${RUN_LOG_DIR}/verify-result.json"

while [[ "${attempt}" -le "${AI_MAX_CORRECTIONS}" ]]; do
  attempt_label="initial"
  [[ "${attempt}" -gt 0 ]] && attempt_label="correction ${attempt}"
  ai_log_info "--- Attempt ${attempt} (${attempt_label}) ---"

  prompt_file="$(build_prompt "${attempt}" "${prior_failure_log}")"
  agent_out="${RUN_LOG_DIR}/agent-output-attempt-${attempt}.log"

  agent_exit=0
  run_claude "${prompt_file}" "${agent_out}" || agent_exit=$?
  if [[ "${agent_exit}" -ne 0 ]]; then
    ai_log_error "Agent process exited ${agent_exit} — see ${agent_out}"
    fail_and_preserve "agent failure or timeout (exit ${agent_exit}) on attempt ${attempt}"
  fi

  # Validate changed paths BEFORE staging/committing anything.
  if ! ai_validate_changed_paths "${WORKTREE_PATH}" "${ALLOWED_PATHS_NEWLINE}" 2>"${RUN_LOG_DIR}/path-violation-attempt-${attempt}.log"; then
    cat "${RUN_LOG_DIR}/path-violation-attempt-${attempt}.log" >&2
    fail_and_preserve "scope violation: a changed path was outside the approved allowlist or hit the hard denylist on attempt ${attempt}"
  fi

  if [[ -z "$(git -C "${WORKTREE_PATH}" status --porcelain)" ]]; then
    ai_log_warn "No changes on attempt ${attempt} — agent made no modifications."
    prior_failure_log="${agent_out}"
    attempt=$((attempt + 1))
    continue
  fi

  # Stage only validated, NUL-safe-enumerated paths (never git add -A / git add .).
  # Enumerated via a checked temp file, not `< <(...)` — see
  # ai_enumerate_changed_paths in common.sh: a git failure here must
  # abort dispatch, not silently stage whatever partial list a failed
  # producer happened to write before failing.
  STAGE_ENUM_FILE="$(mktemp "$(ai_run_log_root)/stage-enum.XXXXXX")"
  if ! ai_enumerate_changed_paths "${WORKTREE_PATH}" "${STAGE_ENUM_FILE}"; then
    rm -f "${STAGE_ENUM_FILE}"
    fail_and_preserve "could not enumerate changed paths before staging on attempt ${attempt} (git failed)"
  fi
  declare -a STAGE_PATHS=()
  while IFS= read -r -d '' entry; do
    STAGE_PATHS+=("${entry}")
  done <"${STAGE_ENUM_FILE}"
  rm -f "${STAGE_ENUM_FILE}"
  git -C "${WORKTREE_PATH}" add -- "${STAGE_PATHS[@]}"

  # Commit through the dispatcher, with repository hooks disabled via
  # an empty, dedicated hooksPath (defense in depth against a
  # tampered local hook — not about developer convenience).
  EMPTY_HOOKS_DIR="$(mktemp -d)"
  git -C "${WORKTREE_PATH}" -c core.hooksPath="${EMPTY_HOOKS_DIR}" -c user.name="heimei-dispatch" -c user.email="heimei-dispatch@localhost" \
    commit --no-gpg-sign -m "$(printf 'feat: dispatch for issue #%s via %s\n\nRun: %s\nApproval: %s\n\nAutomated commit — Scripts/ai/dispatch.sh.' "${ISSUE_NUMBER}" "${AGENT}" "${RUN_ID}" "${APPROVAL_ID}")" \
    || { rm -rf "${EMPTY_HOOKS_DIR}"; fail_and_preserve "dispatcher commit failed on attempt ${attempt}"; }
  rm -rf "${EMPTY_HOOKS_DIR}"

  # Confirm clean, record HEAD SHA, update the run manifest with it.
  [[ -z "$(git -C "${WORKTREE_PATH}" status --porcelain)" ]] || fail_and_preserve "worktree not clean immediately after commit on attempt ${attempt}"
  COMMITTED_SHA="$(git -C "${WORKTREE_PATH}" rev-parse HEAD)"
  ai_log_info "Local commit created: ${COMMITTED_SHA}"

  MANIFEST_NOW="$(ai_read_run_manifest "${RUN_MANIFEST_PATH}")"
  ai_write_run_manifest "${RUN_MANIFEST_PATH}" "$(jq -c --arg sha "${COMMITTED_SHA}" '.expected_commit_sha = $sha' <<<"${MANIFEST_NOW}")"

  # Verify against that exact committed checkout, in --mode dispatch —
  # the ONLY mode this script trusts as proof.
  if "${SCRIPT_DIR}/verify.sh" --mode dispatch --run-manifest "${RUN_MANIFEST_PATH}" --repo-root "${WORKTREE_PATH}" --expected-sha "${COMMITTED_SHA}" --full --json "${VERIFY_JSON}"; then
    TESTED_SHA="$(jq -r '.tested_sha' "${VERIFY_JSON}")"
    VERIFIED_MODE="$(jq -r '.mode' "${VERIFY_JSON}")"
    [[ "${VERIFIED_MODE}" == "dispatch" ]] || fail_and_preserve "verify.sh reported mode '${VERIFIED_MODE}', not 'dispatch' — refusing to trust non-dispatch-mode output as proof."
    [[ "${TESTED_SHA}" == "${COMMITTED_SHA}" ]] || fail_and_preserve "verify.sh tested SHA (${TESTED_SHA}) does not match the committed SHA (${COMMITTED_SHA}) — refusing."
    ai_log_info "Verification passed (mode: dispatch) against exact committed SHA ${TESTED_SHA}."
    break
  else
    ai_log_warn "Verification failed on attempt ${attempt} for commit ${COMMITTED_SHA}."
    # Preserve worktree+commit locally; do not push; do not create PR.
    if [[ "${attempt}" -ge "${AI_MAX_CORRECTIONS}" ]]; then
      fail_and_preserve "verification failed after $((attempt + 1)) attempt(s); last tested commit ${COMMITTED_SHA} preserved locally, never pushed"
    fi
    prior_failure_log="${VERIFY_JSON}"
    attempt=$((attempt + 1))
  fi
done

if [[ -z "${COMMITTED_SHA}" ]]; then
  fail_and_preserve "no commit was ever produced across $((AI_MAX_CORRECTIONS + 1)) attempts"
fi

# ---------------------------------------------------------------------------
# Revalidate paths and cleanliness once more before push (no file may
# change between verification and push), plus a THIRD base-SHA
# freshness check immediately before push/PR creation.
# ---------------------------------------------------------------------------

[[ -z "$(git -C "${WORKTREE_PATH}" status --porcelain)" ]] || fail_and_preserve "worktree became dirty between verification and push"
HEAD_BEFORE_PUSH="$(git -C "${WORKTREE_PATH}" rev-parse HEAD)"
[[ "${HEAD_BEFORE_PUSH}" == "${COMMITTED_SHA}" ]] || fail_and_preserve "HEAD moved between verification and push (${COMMITTED_SHA} -> ${HEAD_BEFORE_PUSH})"
ai_validate_changed_paths "${WORKTREE_PATH}" "${ALLOWED_PATHS_NEWLINE}" 2>&1 | tee -a "${RUN_LOG_DIR}/final-path-revalidation.log" \
  || fail_and_preserve "path revalidation failed immediately before push"

CURRENT_MAIN_SHA_BEFORE_PUSH="$(ai_current_main_sha)"
[[ "${CURRENT_MAIN_SHA_BEFORE_PUSH}" == "${APPROVAL_BASE_SHA}" ]] \
  || fail_and_preserve "origin/${PROTECTED_BRANCH} advanced (now ${CURRENT_MAIN_SHA_BEFORE_PUSH}, approved base was ${APPROVAL_BASE_SHA}) between verification and push — preserving the local worktree and stopping without pushing. A fresh approval against the new base is required."

# ---------------------------------------------------------------------------
# Push the exact tested SHA to the claimed ai/* branch, fetch, verify
# remote SHA matches.
# ---------------------------------------------------------------------------

ai_log_info "Pushing exact tested SHA ${COMMITTED_SHA} to ${BRANCH_NAME}..."
git -C "${WORKTREE_PATH}" push origin "${BRANCH_NAME}" \
  || fail_and_preserve "push failed for commit ${COMMITTED_SHA} — worktree and commit preserved locally"

git fetch origin "${BRANCH_NAME}" --quiet
REMOTE_SHA_AFTER_PUSH="$(git ls-remote origin "refs/heads/${BRANCH_NAME}" | cut -f1)"
[[ "${REMOTE_SHA_AFTER_PUSH}" == "${COMMITTED_SHA}" ]] \
  || fail_and_preserve "remote branch SHA (${REMOTE_SHA_AFTER_PUSH}) does not match the pushed/tested SHA (${COMMITTED_SHA}) after push"
ai_log_info "Remote branch confirmed at exact tested SHA."

# ---------------------------------------------------------------------------
# Draft PR (status:draft-pr, never status:review at this point), with
# REAL verification transcripts (never a synthesized PASS/FAIL string),
# verify PR head SHA.
# ---------------------------------------------------------------------------

render_check_section() {
  local key="$1" label="$2"
  local pass cmd started ended sha256 excerpt
  pass="$(jq -r --arg k "${key}" '.checks[$k].pass' "${VERIFY_JSON}")"
  cmd="$(jq -r --arg k "${key}" '.checks[$k].command' "${VERIFY_JSON}")"
  started="$(jq -r --arg k "${key}" '.checks[$k].started_at' "${VERIFY_JSON}")"
  ended="$(jq -r --arg k "${key}" '.checks[$k].ended_at' "${VERIFY_JSON}")"
  sha256="$(jq -r --arg k "${key}" '.checks[$k].transcript_sha256' "${VERIFY_JSON}")"
  excerpt="$(jq -r --arg k "${key}" '.checks[$k].transcript_excerpt' "${VERIFY_JSON}")"
  echo "### ${label}: $([[ "${pass}" == "true" ]] && echo PASS || echo FAIL)"
  echo
  echo "Command: \`${cmd}\` (${started} → ${ended})"
  echo "Transcript SHA-256: \`${sha256}\`"
  echo
  echo '```'
  printf '%s\n' "${excerpt}" | ai_bounded_output 4000
  echo '```'
  echo
}

PR_BODY_FILE="${RUN_LOG_DIR}/pr-body.md"
{
  echo "## Linked issue"
  echo
  echo "Closes #${ISSUE_NUMBER}"
  echo
  echo "## Provenance"
  echo
  echo "| Field | Value |"
  echo "|---|---|"
  echo "| Approval ID | \`${APPROVAL_ID}\` |"
  echo "| Approval comment | ${ISSUE_URL}#issuecomment-${APPROVAL_COMMENT_ID} |"
  echo "| Claim ref | \`${CLAIM_REF}\` |"
  echo "| Run ID | \`${RUN_ID}\` |"
  echo "| Repository ID | \`${REPO_ID}\` |"
  echo "| Implementation agent | \`${AGENT}\` (no Bash tool) |"
  echo "| Base SHA | \`${APPROVAL_BASE_SHA}\` |"
  echo "| Tested commit SHA | \`${COMMITTED_SHA}\` |"
  echo "| Remote branch SHA | \`${REMOTE_SHA_AFTER_PUSH}\` |"
  echo
  echo "Review is a separate, explicit, owner-supplied-argument step —"
  echo "see \`Scripts/ai/review.sh\`'s \`--issue\`/\`--approval-id\`/"
  echo "\`--implementation-agent\`/\`--reviewer\` flags. Nothing here"
  echo "auto-selects a reviewer."
  echo
  echo "## Architecture summary"
  echo
  echo "See issue #${ISSUE_NUMBER} for approved scope. Implemented per the allowed-paths list in approval ${APPROVAL_ID}."
  echo
  echo "## Files changed"
  echo
  echo '```'
  git -C "${WORKTREE_PATH}" diff --name-status "${APPROVAL_BASE_SHA}" "${COMMITTED_SHA}"
  echo '```'
  echo
  echo "## Behavior changed"
  echo
  echo "See files changed above and the issue's own Desired outcome section."
  echo
  echo "## Tests added"
  echo
  git -C "${WORKTREE_PATH}" diff --name-only "${APPROVAL_BASE_SHA}" "${COMMITTED_SHA}" -- '*test*' || true
  echo
  echo "## Exact verification commands and real output"
  echo
  echo "Every section below is a REAL captured transcript (redacted,"
  echo "bounded) from \`Scripts/ai/verify.sh --mode dispatch\`, run"
  echo "against exactly commit \`${COMMITTED_SHA}\` — never a"
  echo "self-reported or synthesized PASS/FAIL string."
  echo
  render_check_section "uv_sync" "uv sync --locked"
  render_check_section "pytest" "pytest"
  render_check_section "ruff" "ruff check"
  render_check_section "mypy" "mypy"
  echo "Tested SHA: \`$(jq -r '.tested_sha' "${VERIFY_JSON}")\` — matches the committed, pushed, and remote-branch SHA above."
  echo
  echo "## Frozen subsystem touches"
  echo
  echo "None expected — mechanically enforced by the approved allowlist and the hard denylist in .ai/policy.toml; any touch would have failed dispatch before this PR could exist."
  echo
  echo "## Dependency changes"
  echo
  echo "None — dependency manifests (pyproject.toml, uv.lock, requirements*.txt, etc.) are hard-denylisted for ordinary automated dispatch in v1; any such touch would have failed dispatch before this PR could exist."
  echo
  echo "## Security / privacy implications"
  echo
  echo "None — see approval ${APPROVAL_ID} for the reviewed scope."
  echo
  echo "## Migration impact"
  echo
  echo "None — migration paths are hard-denylisted for ordinary automated dispatch in v1."
  echo
  echo "## Deferred work"
  echo
  echo "Anything outside this issue's declared acceptance criteria."
  echo
  echo "## Known limitations"
  echo
  echo "Automated draft — has not yet had CI or independent review. Implemented by Claude with no shell/Git access; the dispatcher performed all git operations and verification."
  echo
  echo "## Recommendation"
  echo
  echo "Automated draft, unreviewed. Needs CI green and an explicit \`Scripts/ai/review.sh\` invocation (owner-supplied \`--issue\`/\`--approval-id\`/\`--implementation-agent\`/\`--reviewer\`) before owner review."
} >"${PR_BODY_FILE}"

ai_log_info "Opening draft PR (status:draft-pr, not status:review)..."
PR_URL="$(gh pr create \
  --repo "${REPO}" \
  --base "${PROTECTED_BRANCH}" \
  --head "${BRANCH_NAME}" \
  --draft \
  --title "$(printf '%s (#%s)' "${ISSUE_TITLE}" "${ISSUE_NUMBER}")" \
  --body-file "${PR_BODY_FILE}")"
PR_NUMBER="$(printf '%s' "${PR_URL}" | grep -oE '[0-9]+$')"

PR_HEAD_SHA="$(gh pr view "${PR_NUMBER}" --repo "${REPO}" --json headRefOid --jq '.headRefOid')"
[[ "${PR_HEAD_SHA}" == "${COMMITTED_SHA}" ]] \
  || fail_and_preserve "PR head SHA (${PR_HEAD_SHA}) does not match the tested/pushed SHA (${COMMITTED_SHA}) — PR was created but do not trust it without investigating."

ai_replace_status_label "${ISSUE_NUMBER}" "status:draft-pr"

# ---------------------------------------------------------------------------
# Dispatch attestation — informational corroboration only in v1.
# review.sh's supervised design derives implementer identity from an
# OWNER-SUPPLIED --implementation-agent argument, cross-checked against
# the approval record — never from this comment alone, and never
# auto-selected from it. This comment remains useful as an independent
# corroboration signal a human can compare by eye.
# ---------------------------------------------------------------------------

ATTESTATION_FILE="$(mktemp)"
{
  echo "## Heimei Dispatch Attestation"
  echo
  echo "Informational corroboration only — see AI_WORKFLOW.md, 'Supervised"
  echo "reviewer provenance': review.sh requires the owner to pass"
  echo "--implementation-agent explicitly and cross-checks it against the"
  echo "approval record, never trusting this comment alone as proof."
  echo
  echo '```json'
  jq -nc \
    --arg repository_id "${REPO_ID}" \
    --argjson issue_number "${ISSUE_NUMBER}" \
    --arg approval_id "${APPROVAL_ID}" \
    --arg approval_comment_id "${APPROVAL_COMMENT_ID}" \
    --arg run_id "${RUN_ID}" \
    --arg agent "${AGENT}" \
    --arg base_sha "${APPROVAL_BASE_SHA}" \
    --arg head_sha "${COMMITTED_SHA}" \
    --arg branch "${BRANCH_NAME}" \
    --arg pr_number "${PR_NUMBER}" \
    --arg timestamp "$(ai_log_ts)" \
    '{repository_id: $repository_id, issue_number: $issue_number, approval_id: $approval_id,
      approval_comment_id: $approval_comment_id, run_id: $run_id, implementation_agent: $agent,
      base_sha: $base_sha, head_sha: $head_sha, branch: $branch, pr_number: $pr_number,
      timestamp: $timestamp, schema: "heimei-attestation/v1"}' | jq .
  echo '```'
  echo "<!-- heimei-attestation:v1 -->"
} >"${ATTESTATION_FILE}"
gh issue comment "${ISSUE_NUMBER}" --repo "${REPO}" --body-file "${ATTESTATION_FILE}" >/dev/null
rm -f "${ATTESTATION_FILE}"

# ---------------------------------------------------------------------------
# Cleanup — only reachable here, i.e. only after every success
# condition above (exact-SHA verification, confirmed push, confirmed PR,
# confirmed PR head SHA, clean worktree) has already held.
# ---------------------------------------------------------------------------

if ! ai_safe_remove_worktree "${REPO_ROOT}" "${WORKTREE_PATH}"; then
  ai_log_warn "Cleanup failed — worktree preserved (this is not itself a failure of the dispatch, which already succeeded)."
fi

cat <<EOF

================================================================================
Run summary
================================================================================
  Issue:       #${ISSUE_NUMBER}
  Agent:       ${AGENT} (no Bash tool)
  Claim ref:   ${CLAIM_REF}
  Branch:      ${BRANCH_NAME}
  Base SHA:    ${APPROVAL_BASE_SHA}
  Tested SHA:  ${COMMITTED_SHA}
  Remote SHA:  ${REMOTE_SHA_AFTER_PUSH}
  PR:          ${PR_URL}
  PR head SHA: ${PR_HEAD_SHA}
  Run log:     ${RUN_LOG_DIR}
  Run manifest: ${RUN_MANIFEST_PATH}
================================================================================
Labeled status:draft-pr, NOT status:review — that transition happens
only after CI is confirmed green, as a separate trusted operation.
Review requires an explicit, owner-invoked Scripts/ai/review.sh with
--issue/--approval-id/--implementation-agent/--reviewer — nothing
auto-selects a reviewer. See AI_WORKFLOW.md.
EOF
