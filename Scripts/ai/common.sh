#!/usr/bin/env bash
# Scripts/ai/common.sh
#
# Shared helpers for the Heimei AI development control plane scripts
# (bootstrap-github.sh, verify.sh, dispatch.sh, review.sh). See
# AI_WORKFLOW.md for the policy these scripts implement mechanically.
#
# Meant to be sourced, not executed:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
#
# Never logs secrets: functions here only ever log names, paths, issue
# numbers, and labels — never environment variables wholesale, tokens,
# or full `gh`/`git` command lines that could carry a credential.

# Guard against being executed directly instead of sourced.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "common.sh is a library — source it, don't execute it." >&2
  exit 1
fi

set -uo pipefail

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

ai_log_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

ai_log_info()  { printf '[%s] [INFO]  %s\n'  "$(ai_log_ts)" "$*" >&2; }
ai_log_warn()  { printf '[%s] [WARN]  %s\n'  "$(ai_log_ts)" "$*" >&2; }
ai_log_error() { printf '[%s] [ERROR] %s\n' "$(ai_log_ts)" "$*" >&2; }

ai_die() {
  ai_log_error "$*"
  exit 1
}

# ---------------------------------------------------------------------------
# Repository root discovery
# ---------------------------------------------------------------------------

# Prints the absolute path to the git repository root (~/Heimei), or dies.
ai_repo_root() {
  local root
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || ai_die "Not inside a git repository."
  printf '%s\n' "${root}"
}

# Prints the path to the one real software project inside the repo.
ai_project_dir() {
  printf '%s/Projects/Heimei\n' "$(ai_repo_root)"
}

# Prints "owner/repo" for the current origin remote.
ai_repo_slug() {
  if command -v gh >/dev/null 2>&1; then
    local slug
    slug="$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null)" || true
    if [[ -n "${slug}" ]]; then
      printf '%s\n' "${slug}"
      return 0
    fi
  fi
  # Fall back to parsing the git remote URL if gh can't resolve it (e.g.
  # not authenticated). Pure bash, deliberately not a single sed regex:
  # GNU sed's ERE has no non-greedy quantifier, so a naive `+?` pattern
  # here silently failed to strip a trailing .git (caught by this
  # script's own smoke test). Handles git@host:owner/repo.git,
  # https://host/owner/repo(.git), and ssh://git@host/owner/repo(.git)
  # by splitting on both '/' and ':' and taking the last two segments.
  local url
  url="$(git -C "$(ai_repo_root)" remote get-url origin 2>/dev/null)" || ai_die "No 'origin' remote configured."
  url="${url%.git}"
  local -a parts
  IFS='/:' read -ra parts <<<"${url}"
  local n="${#parts[@]}"
  [[ "${n}" -ge 2 ]] || ai_die "Could not parse owner/repo from remote URL: ${url}"
  printf '%s/%s\n' "${parts[$((n - 2))]}" "${parts[$((n - 1))]}"
}

# ---------------------------------------------------------------------------
# Command presence checks
# ---------------------------------------------------------------------------

ai_require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || ai_die "Required command not found: ${cmd}"
}

ai_require_gh_auth() {
  ai_require_cmd gh
  gh auth status >/dev/null 2>&1 || ai_die "gh CLI is not authenticated. Run: gh auth login"
}

# ---------------------------------------------------------------------------
# Issue metadata retrieval
# ---------------------------------------------------------------------------

# Prints the full `gh issue view` JSON for the given issue number.
# Fields kept deliberately minimal — labels, state, title, body, url —
# nothing that could contain a secret is ever fetched here.
ai_issue_json() {
  local issue_number="$1"
  ai_require_gh_auth
  gh issue view "${issue_number}" \
    --json number,title,state,labels,body,url \
    2>/dev/null || ai_die "Issue #${issue_number} not found or not readable."
}

ai_issue_state() {
  printf '%s' "$1" | jq -r '.state'
}

ai_issue_label_names() {
  printf '%s' "$1" | jq -r '.labels[].name'
}

# ---------------------------------------------------------------------------
# Label validation — mirrors AI_WORKFLOW.md's "Task-scoped authorization"
# ---------------------------------------------------------------------------

# Usage: ai_validate_issue_labels "<issue-json>" "<requested-agent>"
# Prints nothing on success; dies with a clear reason on failure.
ai_validate_issue_labels() {
  local issue_json="$1"
  local requested_agent="$2"
  local labels
  labels="$(ai_issue_label_names "${issue_json}")"

  grep -qxF "status:approved" <<<"${labels}" \
    || ai_die "Issue is missing status:approved — not authorized."

  local agent_count
  agent_count="$(grep -cE '^agent:(claude|codex)$' <<<"${labels}" || true)"
  [[ "${agent_count}" -eq 1 ]] \
    || ai_die "Issue must carry exactly one agent: label (found ${agent_count})."

  local issue_agent
  issue_agent="$(grep -E '^agent:(claude|codex)$' <<<"${labels}" | sed 's/^agent://')"
  [[ "${issue_agent}" == "${requested_agent}" ]] \
    || ai_die "Requested agent '${requested_agent}' does not match issue's agent label 'agent:${issue_agent}'."

  for blocking in "risk:high" "frozen-subsystem" "breaking-change" "database-migration"; do
    if grep -qxF "${blocking}" <<<"${labels}"; then
      if [[ "${blocking}" == "database-migration" && "${AI_ALLOW_DB_MIGRATION_OVERRIDE:-0}" == "1" ]]; then
        ai_log_warn "database-migration label present but explicit override supplied — proceeding."
        continue
      fi
      ai_die "Blocking label present: ${blocking}. Requires explicit human handling, not automated dispatch."
    fi
  done
}

# ---------------------------------------------------------------------------
# Branch / worktree naming
# ---------------------------------------------------------------------------

# Usage: ai_branch_name <issue-number> <agent> <title>
ai_branch_name() {
  local issue_number="$1" agent="$2" title="$3"
  local slug
  slug="$(printf '%s' "${title}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//' | cut -c1-40)"
  printf 'ai/%s/issue-%s-%s\n' "${agent}" "${issue_number}" "${slug}"
}

# Usage: ai_worktree_path <branch-name>
# Lives under Temp/, which is already gitignored at the repo root — no
# new .gitignore entry needed.
ai_worktree_path() {
  local branch_name="$1"
  local safe_name="${branch_name//\//-}"
  printf '%s/Temp/ai-worktrees/%s\n' "$(ai_repo_root)" "${safe_name}"
}

# Usage: ai_run_log_dir <issue-number>
# Also under Temp/ — never committed, never needs a new .gitignore rule.
ai_run_log_dir() {
  local issue_number="$1"
  local stamp
  stamp="$(date -u +"%Y%m%dT%H%M%SZ")"
  printf '%s/Temp/ai-runs/issue-%s-%s\n' "$(ai_repo_root)" "${issue_number}" "${stamp}"
}

# ---------------------------------------------------------------------------
# Locking — never run two dispatch tasks simultaneously
# ---------------------------------------------------------------------------

# Usage: ai_acquire_lock <lockfile-path> ; trap ai_release_lock EXIT
# Uses flock on a dedicated fd so the lock is released automatically if
# the process dies, even without an explicit trap running.
_AI_LOCK_FD=""

ai_acquire_lock() {
  local lock_path="$1"
  mkdir -p "$(dirname "${lock_path}")"
  exec {_AI_LOCK_FD}>"${lock_path}"
  if ! flock -n "${_AI_LOCK_FD}"; then
    ai_die "Another AI task appears to be running (lock held: ${lock_path}). Refusing to run concurrently."
  fi
  ai_log_info "Acquired lock: ${lock_path}"
}

ai_release_lock() {
  if [[ -n "${_AI_LOCK_FD}" ]]; then
    flock -u "${_AI_LOCK_FD}" 2>/dev/null || true
    exec {_AI_LOCK_FD}>&- 2>/dev/null || true
    _AI_LOCK_FD=""
  fi
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

# Usage: ai_register_cleanup <command-string>
# Appends to a trap-run cleanup list so multiple callers can each
# register their own teardown without clobbering each other's trap.
_AI_CLEANUP_COMMANDS=()

ai_register_cleanup() {
  _AI_CLEANUP_COMMANDS+=("$1")
}

ai_run_cleanup() {
  local cmd
  for cmd in "${_AI_CLEANUP_COMMANDS[@]:-}"; do
    [[ -n "${cmd}" ]] && eval "${cmd}" || true
  done
  ai_release_lock
}
