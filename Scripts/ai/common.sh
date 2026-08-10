#!/usr/bin/env bash
# Scripts/ai/common.sh
#
# Shared helpers for the Heimei AI development control plane
# (approve.sh, bootstrap-github.sh, verify.sh, dispatch.sh, review.sh,
# agent-git.sh). See AI_WORKFLOW.md for the policy these implement,
# .ai/policy.toml for the machine-readable facts they validate against,
# and State/Reports/ai-development-control-plane.md for the design.
#
# Meant to be sourced, not executed:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
#
# Security posture, load-bearing across every caller:
#   - Every check here fails closed: on doubt, on a missing tool, on a
#     malformed policy file, on an ambiguous API response, on a
#     mismatched repository identity — die, never proceed with a
#     best-effort guess.
#   - No `eval`. Cleanup is explicit, typed, and never automatic on
#     failure — see "Cleanup" below.
#   - Nothing here ever logs a token, an environment variable dump, or
#     raw agent tool-event output.
#   - Filename/path handling is NUL-safe end to end: every enumeration
#     of changed files uses git's own `-z` output, read one full
#     NUL-terminated record at a time, never re-joined through a
#     newline-based tool (awk/tr/for-in-$()) that would corrupt a
#     filename containing an embedded newline.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "common.sh is a library — source it, don't execute it." >&2
  exit 1
fi

set -uo pipefail

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

ai_log_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

ai_log_info()  { printf '[%s] [INFO]  %s\n'  "$(ai_log_ts)" "$1" >&2; }
ai_log_warn()  { printf '[%s] [WARN]  %s\n'  "$(ai_log_ts)" "$1" >&2; }
ai_log_error() { printf '[%s] [ERROR] %s\n' "$(ai_log_ts)" "$1" >&2; }

ai_die() {
  ai_log_error "$1"
  exit 1
}

# ---------------------------------------------------------------------------
# Redaction — applied before anything is displayed, posted, or written
# into a PR body (review.sh, dispatch.sh's PR-body transcript excerpts,
# and any log line that might echo agent/tool output). Best-effort, not
# a guarantee: see State/Reports/ai-development-control-plane.md,
# "Security risks," for the honest limitation.
# ---------------------------------------------------------------------------

ai_redact() {
  # Reads stdin, writes redacted text to stdout. Implemented in
  # Scripts/ai/redact.py, not sed — correct handling of multi-line
  # patterns (PEM private-key blocks span many lines) is fragile to
  # express as a sed one-liner; see that file for the exact pattern
  # list (Authorization: Bearer, AWS access keys, OPENSSH/PKCS8/RSA/EC
  # private-key blocks, generic TOKEN/SECRET/API_KEY/PASSWORD
  # assignments, home paths) and ordering rationale (multi-line PEM
  # blocks first, then single-line patterns, then paths — always
  # BEFORE any caller bounds/truncates or hashes the result).
  ai_require_cmd python3
  python3 "$(ai_repo_root)/Scripts/ai/redact.py"
}

ai_bounded_output() {
  # Usage: ai_bounded_output <max-bytes> < input
  local max_bytes="$1"
  head -c "${max_bytes}"
}

# ---------------------------------------------------------------------------
# Repository root / project / identity
# ---------------------------------------------------------------------------

ai_repo_root() {
  local root
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || ai_die "Not inside a git repository."
  printf '%s\n' "${root}"
}

ai_project_dir() {
  printf '%s/Projects/Heimei\n' "$(ai_repo_root)"
}

ai_policy_path() {
  printf '%s/.ai/policy.toml\n' "$(ai_repo_root)"
}

_AI_POLICY_JSON=""

# Loads .ai/policy.toml exactly once per process, as JSON, via the
# trusted Scripts/ai/policy.py helper (Python stdlib tomllib — no new
# dependency, and exactly one place that parses TOML). Fails closed.
ai_policy_json() {
  if [[ -z "${_AI_POLICY_JSON}" ]]; then
    ai_require_cmd python3
    local policy_file script_dir
    policy_file="$(ai_policy_path)"
    script_dir="$(ai_repo_root)/Scripts/ai"
    [[ -f "${policy_file}" ]] || ai_die "Policy file missing: ${policy_file} — refusing to proceed without it."
    _AI_POLICY_JSON="$(python3 "${script_dir}/policy.py" "${policy_file}")" \
      || ai_die "Policy file is invalid: ${policy_file}"
  fi
  printf '%s' "${_AI_POLICY_JSON}"
}

# Usage: ai_policy_get '.repository.id'
ai_policy_get() {
  local filter="$1"
  ai_require_cmd jq
  local value
  value="$(ai_policy_json | jq -er "${filter}")" || ai_die "Policy is missing required field: ${filter}"
  printf '%s' "${value}"
}

# Usage: ai_policy_get_array '.paths.frozen_subsystems[]'  -> one per line
ai_policy_get_array() {
  local filter="$1"
  ai_require_cmd jq
  ai_policy_json | jq -er "${filter}" 2>/dev/null || true
}

ai_worktree_root() {
  printf '%s/%s\n' "$(ai_repo_root)" "$(ai_policy_get '.runtime.worktree_root')"
}

ai_run_log_root() {
  printf '%s/%s\n' "$(ai_repo_root)" "$(ai_policy_get '.runtime.run_log_root')"
}

ai_run_manifest_root() {
  printf '%s/%s\n' "$(ai_repo_root)" "$(ai_policy_get '.runtime.run_manifest_root')"
}

# Verifies the live GitHub repository (owner/name/immutable id) matches
# .ai/policy.toml exactly. Fails closed on any mismatch, including a
# `gh` call failure — never assumes "probably fine."
ai_verify_repo_identity() {
  ai_require_gh_auth
  ai_require_cmd jq
  local live_json live_id live_slug expected_id expected_owner expected_name
  live_json="$(gh repo view --json id,nameWithOwner 2>/dev/null)" || ai_die "Could not query repository identity via gh."
  live_id="$(printf '%s' "${live_json}" | jq -r '.id')"
  live_slug="$(printf '%s' "${live_json}" | jq -r '.nameWithOwner')"
  expected_id="$(ai_policy_get '.repository.id')"
  expected_owner="$(ai_policy_get '.repository.owner')"
  expected_name="$(ai_policy_get '.repository.name')"

  [[ "${live_id}" == "${expected_id}" ]] \
    || ai_die "Repository ID mismatch: policy expects '${expected_id}', gh reports '${live_id}'. Refusing — this could mean a wrong checkout, a repo rename, or a compromised remote."
  [[ "${live_slug}" == "${expected_owner}/${expected_name}" ]] \
    || ai_die "Repository owner/name mismatch: policy expects '${expected_owner}/${expected_name}', gh reports '${live_slug}'."
}

# Prints "owner/repo" for the current origin remote — used only for gh
# --repo arguments, never as a substitute for ai_verify_repo_identity's
# immutable-ID check.
ai_repo_slug() {
  ai_policy_get '.repository.owner' | { read -r owner; printf '%s/' "${owner}"; }
  ai_policy_get '.repository.name'
}

ai_current_actor() {
  ai_require_gh_auth
  gh api user --jq '.login' 2>/dev/null || ai_die "Could not determine the authenticated gh actor."
}

# Usage: ai_require_approver "$(ai_current_actor)"
ai_require_approver() {
  local actor="$1"
  local allowed
  allowed="$(ai_policy_get_array '.approval.allowed_approvers[]')"
  grep -qxF "${actor}" <<<"${allowed}" \
    || ai_die "Actor '${actor}' is not in the approver allowlist (.ai/policy.toml, [approval].allowed_approvers)."
}

# Usage: ai_require_single_risk_label "$LABELS_NEWLINE" -> prints
# "low"/"medium"/"high" on stdout. Risk is state that lives OUTSIDE the
# issue body (a label, not body text), so the issue-body digest check
# can never catch a risk-label change on its own — this function is
# the single source of truth both approve.sh and dispatch.sh call,
# every time, to derive risk from live label state. Distinguishes
# "no risk label," "more than one," and "unrecognized value" with
# separate messages rather than a single generic failure.
ai_require_single_risk_label() {
  local labels="$1"
  local risk_lines
  risk_lines="$(grep -E '^risk:' <<<"${labels}" || true)"
  local count=0
  [[ -n "${risk_lines}" ]] && count="$(printf '%s\n' "${risk_lines}" | grep -c .)"

  [[ "${count}" -ge 1 ]] || ai_die "Issue has no risk:* label — exactly one of risk:low, risk:medium, or risk:high is required."
  [[ "${count}" -eq 1 ]] || ai_die "Issue carries ${count} risk:* labels — exactly one is required, never more (ambiguous risk tier)."

  local only_label value
  only_label="$(printf '%s\n' "${risk_lines}" | head -1)"
  value="${only_label#risk:}"
  case "${value}" in
    low|medium|high) printf '%s\n' "${value}" ;;
    *) ai_die "Issue's risk label '${only_label}' is not a recognized value — must be risk:low, risk:medium, or risk:high." ;;
  esac
}

# ---------------------------------------------------------------------------
# Command presence / auth
# ---------------------------------------------------------------------------

ai_require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || ai_die "Required command not found: ${cmd}"
}

ai_require_gh_auth() {
  ai_require_cmd gh
  gh auth status >/dev/null 2>&1 || ai_die "gh CLI is not authenticated. Run: gh auth login"
}

# Usage: ai_require_safe_claude_tool_surface
# Fails closed unless the installed `claude` CLI advertises EVERY flag
# this design's invocation depends on to mechanically restrict the
# automated implementer's tool surface: --tools (defines the actual
# AVAILABLE built-in tool set, not merely a permission filter — this
# is the flag that matters most; --allowedTools/--disallowedTools
# alone do NOT prove Bash is absent, only that it's "denied" among
# whatever set is otherwise available), --allowedTools,
# --disallowedTools, --permission-mode, --safe-mode (disables
# inherited CLAUDE.md/skills/plugins/hooks/MCP servers/custom
# commands), --strict-mcp-config + --mcp-config (isolates MCP
# entirely to an explicit, empty config this script controls), and
# --setting-sources (so inherited user/project/local settings files —
# which could themselves grant tools or add hooks — are not loaded).
# If ANY of these is missing from `claude --help`, this dies with a
# fixed message telling the operator to implement manually instead of
# silently running with a broader, unproven tool grant — inspected
# fresh every call, never assumed from documentation or memory.
ai_require_safe_claude_tool_surface() {
  ai_require_cmd claude
  local help_text
  help_text="$(claude --help 2>&1)"
  ai_log_info "claude version: $(claude --version 2>&1 | head -1)"
  local required_flags=("--tools" "--allowedTools" "--disallowedTools" "--permission-mode" "--safe-mode" "--strict-mcp-config" "--mcp-config" "--setting-sources" "-p" "--output-format")
  local flag
  for flag in "${required_flags[@]}"; do
    grep -qF -- "${flag}" <<<"${help_text}" \
      || ai_die "Automated Claude implementation is disabled because this Claude CLI version cannot prove an execution-free tool surface (missing '${flag}' in claude --help). Use supervised interactive implementation instead."
  done
  ai_log_info "claude CLI advertises every flag this design requires to mechanically restrict the tool surface (--tools, --allowedTools, --disallowedTools, --permission-mode, --safe-mode, --strict-mcp-config, --mcp-config, --setting-sources)."
}

# ---------------------------------------------------------------------------
# Numeric / identifier input validation
# ---------------------------------------------------------------------------

ai_validate_positive_int() {
  # Usage: ai_validate_positive_int "$value" "issue number"
  local value="$1" what="${2:-value}"
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || ai_die "Invalid ${what}: '${value}' (must match ^[1-9][0-9]*\$)."
}

# Usage: ai_validate_bounded_int "$value" <max> "description"
ai_validate_bounded_int() {
  local value="$1" max="$2" what="${3:-value}"
  ai_validate_positive_int "${value}" "${what}"
  [[ "${value}" -le "${max}" ]] || ai_die "Invalid ${what}: '${value}' exceeds the bound of ${max}."
}

# Usage: ai_validate_approval_id "$id"
# An approval ID is embedded directly into a git ref name (see
# ai_claim_ref_name below), so it is restricted to characters that are
# always safe there — never validated by "does git accept it," always
# validated first, independently, by an explicit allowlist.
ai_validate_approval_id() {
  local id="$1"
  [[ -n "${id}" ]] || ai_die "Approval ID is empty."
  [[ "${id}" =~ ^[A-Za-z0-9._-]+$ ]] || ai_die "Approval ID contains characters unsafe for a ref name: ${id}"
  [[ "${id}" != *".."* ]] || ai_die "Approval ID contains '..': ${id}"
}

# ---------------------------------------------------------------------------
# Issue / PR metadata (read-only)
# ---------------------------------------------------------------------------

ai_issue_json() {
  local issue_number="$1"
  ai_validate_positive_int "${issue_number}" "issue number"
  ai_require_gh_auth
  gh issue view "${issue_number}" --repo "$(ai_repo_slug)" \
    --json number,title,state,labels,body,url,comments \
    2>/dev/null || ai_die "Issue #${issue_number} not found or not readable."
}

ai_issue_state() { printf '%s' "$1" | jq -r '.state'; }
ai_issue_label_names() { printf '%s' "$1" | jq -r '.labels[].name'; }

# Parses a GitHub issue-form body ("### Header\n\ncontent\n\n### ...")
# into {"Header": "content"} JSON, via the trusted Scripts/ai/issue_sections.py
# helper. Pure text parsing of untrusted content — the issue body is
# never sourced, evaled, or otherwise executed, only pattern-matched.
ai_issue_sections_json() {
  local body="$1"
  ai_require_cmd python3
  printf '%s' "${body}" | python3 "$(ai_repo_root)/Scripts/ai/issue_sections.py"
}

# Usage: ai_issue_section "$sections_json" "Allowed paths"
ai_issue_section() {
  local sections_json="$1" header="$2"
  printf '%s' "${sections_json}" | jq -er --arg h "${header}" '.[$h] // ""'
}

# Usage: ai_require_label_exists <repo-slug> <label-name>
# Confirms a label exists in the REPOSITORY (not on any one issue)
# before a caller does anything that depends on being able to land it.
# Fails closed — via ai_die — both when the query itself fails (gh
# error, auth, network, rate limit) and when the query succeeds but
# the label genuinely does not exist: this function cannot and must
# not try to distinguish "doesn't exist" from "transient failure" for
# the caller, since ai_replace_status_label's whole reason for calling
# this first is that either case must block ANY mutation, not just
# one of them. Never auto-creates a label — Scripts/ai/bootstrap-github.sh
# is the sole place canonical labels are provisioned.
ai_require_label_exists() {
  local repo="$1" label_name="$2" existing err_file err_text
  err_file="$(mktemp)"
  if ! existing="$(gh label list --repo "${repo}" --json name --jq '.[].name' --limit 200 2>"${err_file}")"; then
    err_text="$(cat "${err_file}" 2>/dev/null)"
    rm -f "${err_file}"
    ai_die "Could not query labels for ${repo} to confirm '${label_name}' exists (gh label list failed: ${err_text:-no output}) — refusing to proceed."
  fi
  rm -f "${err_file}"
  grep -qxF "${label_name}" <<<"${existing}" \
    || ai_die "Label '${label_name}' does not exist in ${repo} — refusing to proceed. Run Scripts/ai/bootstrap-github.sh --execute to provision canonical labels first."
}

# Usage: ai_require_pr_head_repo_node_id <pulls-json> <trusted-repo-node-id>
# Same-repository provenance check, centralized so review.sh's
# generate path and --post path cannot drift apart on this again.
#
# GitHub's REST PR payload carries two distinct repository
# identifiers: .head.repo.id is the numeric REST/database ID (e.g.
# 1320669590), .head.repo.node_id is the GraphQL node ID (e.g.
# "R_kgDOTrfRlg") — the latter is what .ai/policy.toml's repository.id
# actually stores. This function reads ONLY .node_id, never .id.
#
# Uses a checked jq extraction (`select(type == "string" and length >
# 0)`, `-e`) rather than `// ""` mapping-to-empty-then-checking
# -n: a prior version did exactly that, which meant a missing, null,
# empty, numeric, boolean, or array/object node_id all silently
# resolved to "" and then SKIPPED the comparison entirely (the `-n`
# guard only reads as "field not present," not "field is bogus").
# GitHub is not adversarial here, but this check exists precisely to
# prove same-repository provenance — it must fail closed on anything
# that isn't a genuine, exactly-matching, non-empty string, not
# silently pass on absent-or-malformed identity data.
ai_require_pr_head_repo_node_id() {
  local pulls_json="$1" trusted_repo_node_id="$2" head_repo_node_id
  if ! head_repo_node_id="$(jq -er '.head.repo.node_id | select(type == "string" and length > 0)' <<<"${pulls_json}" 2>/dev/null)"; then
    ai_die "PR head repository node ID (.head.repo.node_id) is missing, null, empty, or not a JSON string — refusing (cannot verify same-repository provenance). Never falls back to .head.repo.id, which is a different, numeric identifier."
  fi
  [[ "${head_repo_node_id}" == "${trusted_repo_node_id}" ]] \
    || ai_die "PR head repository node ID (${head_repo_node_id}) does not match this repository's policy node ID (${trusted_repo_node_id}) — refusing (fork or unexpected cross-repo PR)."
}

# Usage: ai_replace_status_label <issue-number> <new-label>
# Removes every existing status:* label and adds exactly the given one
# — labels are visible workflow state, never authorization (see
# AI_WORKFLOW.md), but keeping exactly one status:* label at a time
# keeps that state honest and unambiguous.
#
# The destination label's existence in the repository is confirmed
# (ai_require_label_exists, fail-closed) BEFORE any existing status:*
# label is removed from the issue. Without this ordering, a missing or
# misspelled destination label would fail the final --add-label call
# (set -e-fatal, by design) only AFTER the old status label was already
# stripped — leaving the issue with no status label at all. Checking
# first means a failure here leaves the issue exactly as it was found.
ai_replace_status_label() {
  local issue_number="$1" new_label="$2" repo issue_json existing
  repo="$(ai_repo_slug)"
  ai_require_label_exists "${repo}" "${new_label}"
  issue_json="$(ai_issue_json "${issue_number}")"
  existing="$(ai_issue_label_names "${issue_json}" | grep '^status:' || true)"
  local label
  while IFS= read -r label; do
    [[ -n "${label}" && "${label}" != "${new_label}" ]] && gh issue edit "${issue_number}" --repo "${repo}" --remove-label "${label}" >/dev/null
  done <<<"${existing}"
  gh issue edit "${issue_number}" --repo "${repo}" --add-label "${new_label}" >/dev/null
}

# Extracts the numeric comment ID from a `gh issue comment` URL, e.g.
# https://github.com/o/r/issues/5#issuecomment-1234567890 -> 1234567890
ai_comment_id_from_url() {
  local url="$1"
  printf '%s' "${url}" | sed -n 's/.*#issuecomment-\([0-9]\+\).*/\1/p'
}

# Canonicalizes an issue body for approval-binding digesting. THE ONLY
# semantic-equivalence claim this function makes is CRLF == LF —
# nothing else. An earlier version of this function also stripped
# per-line trailing whitespace and collapsed trailing blank lines;
# that was found (this pass) to be overreach: Markdown gives trailing
# whitespace real meaning (two trailing spaces is a hard line break),
# so an approval-binding digest silently treating it as insignificant
# was wrong, not merely stylistic. Do not add strip()/rstrip()/
# per-line trailing-whitespace normalization/blank-line collapsing/
# Unicode normalization back into this function without a specific,
# written justification — the default is "every byte is significant."
#
# Why CRLF -> LF is kept: GitHub's own REST/GraphQL APIs are expected
# to return LF-terminated bodies; this one normalization exists purely
# for portability with locally-authored test fixtures (some editors/
# OSes write CRLF), not because CRLF-vs-LF is otherwise insignificant.
#
# HONEST LIMITATION: every caller captures the issue body into a shell
# variable via command substitution ($(...)) before piping it to this
# function, and bash's command substitution unconditionally strips
# ALL trailing newline characters when doing so — a mechanic of the
# shell itself, applied identically at approval time and at every
# dispatch/review re-check, not something this function can see or
# control. The exact trailing-newline COUNT at the very end of a body
# is therefore not part of what this digest binds; every other byte —
# including a single trailing space on any line, a blank line
# anywhere in the middle, and every Unicode code point — is.
ai_canonical_issue_body() {
  # stdin -> stdout. CRLF -> LF only. No other transformation.
  sed -e 's/\r$//'
}

ai_sha256_hex() {
  # stdin -> hex digest on stdout, no filename suffix
  ai_require_cmd sha256sum
  sha256sum | awk '{print $1}'
}

# ---------------------------------------------------------------------------
# Issue-body digest — ONE implementation, used everywhere. A prior
# version of this control plane had TWO subtly different extraction
# patterns for "get the issue body out of a `gh issue view --json`
# blob and hash it": one that captured the body into a shell variable
# BEFORE canonicalizing (`body="$(... | jq -r '.body')"`, then
# `printf '%s' "${body}" | ai_canonical_issue_body | ...`), and one
# that ran jq and canonicalization as a single unbroken pipeline
# (`... | jq -r '.body' | ai_canonical_issue_body | ...`). These
# produce DIFFERENT digests for the IDENTICAL logical body: bash's
# command substitution strips every trailing newline when capturing
# into a variable, while `jq -r` always appends exactly one trailing
# newline to whatever it prints — so the single-pipeline form hashes
# one extra trailing newline the two-step form never sees. This was
# found TWICE independently in this control plane's history (once in
# review.sh, once in dispatch.sh's own post-lock recheck disagreeing
# with its own initial-validation check) — both times because a
# caller hand-rolled the extraction instead of calling one shared
# function. ai_issue_body_from_json/ai_issue_digest_from_json below
# are now the ONLY place this extraction is implemented; every caller
# (approve.sh, dispatch.sh's initial AND post-lock checks, review.sh)
# calls one of these two functions instead of reproducing the
# pipeline itself.
# ---------------------------------------------------------------------------

# Usage: ai_issue_body_from_json "$ISSUE_JSON" -> prints the raw body
# on stdout (not yet canonicalized). Callers that also need the body
# text itself for another purpose (approve.sh's section parsing,
# dispatch.sh's agent prompt) call this once and reuse the result;
# they must NOT re-derive it with their own `jq -r '.body'`.
ai_issue_body_from_json() {
  local issue_json="$1"
  printf '%s' "${issue_json}" | jq -r '.body'
}

# Usage: ai_issue_digest_from_json "$ISSUE_JSON" -> prints the hex
# digest on stdout. Internally: capture the body into a local
# variable (via ai_issue_body_from_json, itself a command
# substitution — this is the ONE place that capture happens for
# digest purposes), THEN canonicalize and hash that variable. Every
# caller gets byte-identical treatment because there is exactly one
# code path, not because every caller remembered to match it by hand.
ai_issue_digest_from_json() {
  local issue_json="$1" body
  body="$(ai_issue_body_from_json "${issue_json}")"
  printf '%s' "${body}" | ai_canonical_issue_body | ai_sha256_hex
}

ai_sha256_file() {
  # Usage: ai_sha256_file <path> -> hex digest on stdout
  ai_require_cmd sha256sum
  sha256sum -- "$1" | awk '{print $1}'
}

# ---------------------------------------------------------------------------
# Branch naming — validated, not just constructed
# ---------------------------------------------------------------------------

ai_branch_name() {
  local issue_number="$1" agent="$2" title="$3"
  local prefix
  prefix="$(ai_policy_get '.branch.automation_prefix')"
  local slug
  slug="$(printf '%s' "${title}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//' | cut -c1-40)"
  [[ -n "${slug}" ]] || slug="untitled"
  printf '%s%s/issue-%s-%s\n' "${prefix}" "${agent}" "${issue_number}" "${slug}"
}

# Usage: ai_validate_branch_name "$branch"
# Fails closed if the name doesn't start with the configured automation
# prefix, contains anything but normalized-safe components, or fails
# git's own ref-name validation.
ai_validate_branch_name() {
  local branch="$1"
  local prefix
  prefix="$(ai_policy_get '.branch.automation_prefix')"
  [[ "${branch}" == "${prefix}"* ]] || ai_die "Branch '${branch}' does not start with required prefix '${prefix}'."
  [[ "${branch}" =~ ^[a-z0-9/-]+$ ]] || ai_die "Branch '${branch}' contains characters outside [a-z0-9/-]."
  [[ "${branch}" != *".."* ]] || ai_die "Branch '${branch}' contains '..'."
  git check-ref-format --branch "${branch}" >/dev/null 2>&1 \
    || ai_die "Branch '${branch}' fails git check-ref-format --branch."
}

# Usage: ai_claim_ref_name <issue-number> <approval-id>
# Full ref name ("refs/heads/ai-claims/issue-N-approval-ID") for the
# atomic claim operation — see ai_create_claim_ref. Distinct from the
# eventual ai/* implementation branch: the claim ref is what makes
# "has this approval already been consumed" a single atomic GitHub
# operation, and it is never deleted automatically (see
# AI_WORKFLOW.md, "Atomic claim").
ai_claim_ref_name() {
  local issue_number="$1" approval_id="$2"
  ai_validate_positive_int "${issue_number}" "issue number"
  ai_validate_approval_id "${approval_id}"
  local prefix
  prefix="$(ai_policy_get '.claim.ref_prefix')"
  printf '%sissue-%s-approval-%s\n' "${prefix}" "${issue_number}" "${approval_id}"
}

# ---------------------------------------------------------------------------
# Filesystem safety — realpath, symlink rejection, containment checks
# ---------------------------------------------------------------------------

# Usage: ai_realpath_strict <path>
# Resolves via realpath -e (must exist); dies if it doesn't.
ai_realpath_strict() {
  local path="$1"
  realpath -e -- "${path}" 2>/dev/null || ai_die "Path does not exist or cannot be resolved: ${path}"
}

# Usage: ai_require_under_parent <child> <parent>
# Both must already exist. Resolves both with realpath and requires
# the resolved child to be strictly inside the resolved parent — this
# is what makes a symlink escape (child resolving somewhere else
# entirely) fail rather than silently succeed.
ai_require_under_parent() {
  local child="$1" parent="$2"
  local real_child real_parent
  real_child="$(ai_realpath_strict "${child}")"
  real_parent="$(ai_realpath_strict "${parent}")"
  case "${real_child}" in
    "${real_parent}"/*) ;;
    *) ai_die "Path '${real_child}' is not inside required parent '${real_parent}' (possible symlink escape)." ;;
  esac
}

# Usage: ai_require_not_symlink <path>
ai_require_not_symlink() {
  local path="$1"
  [[ ! -L "${path}" ]] || ai_die "Path is a symlink, refusing: ${path}"
}

# ---------------------------------------------------------------------------
# Worktree registration — shared by agent-git.sh and verify.sh --mode
# dispatch. A "registered" worktree is one `git worktree list` in the
# PRIMARY repository actually knows about — not merely a directory that
# happens to contain a `.git` file pointing somewhere plausible.
# ---------------------------------------------------------------------------

# Usage: ai_worktree_common_dir <worktree-realpath>
# Prints the absolute path of the worktree's *common* git directory
# (the primary repository's real .git, shared by every worktree) — NOT
# the worktree's own private per-worktree git dir.
ai_worktree_common_dir() {
  local wt="$1" common_dir
  common_dir="$(git -C "${wt}" rev-parse --git-common-dir 2>/dev/null)" \
    || ai_die "Could not resolve git-common-dir for ${wt} — not a git checkout, or git itself failed."
  case "${common_dir}" in
    /*) printf '%s\n' "${common_dir}" ;;
    *) printf '%s\n' "${wt}/${common_dir}" ;;
  esac
}

# Usage: ai_worktree_primary_root <worktree-realpath>
# Prints the realpath of the PRIMARY repository root that owns this
# worktree (derived from its common git dir, not from policy/cwd) —
# works correctly even when called from inside the worktree itself.
ai_worktree_primary_root() {
  local wt="$1" common_dir
  common_dir="$(ai_worktree_common_dir "${wt}")"
  ai_realpath_strict "$(dirname "${common_dir}")"
}

# Usage: ai_require_registered_worktree <worktree-realpath>
# Fails closed unless:
#   - the worktree's primary repository looks like a Heimei checkout
#     (has Projects/Heimei)
#   - that primary repository's OWN `git worktree list` actually lists
#     this exact realpath as a registered worktree
# Prints the primary repository's realpath on success (callers use
# this for further checks, e.g. repository-identity comparison).
ai_require_registered_worktree() {
  local wt="$1" primary_root
  primary_root="$(ai_worktree_primary_root "${wt}")"
  [[ -d "${primary_root}/Projects/Heimei" ]] \
    || ai_die "Worktree's primary repository does not look like a Heimei checkout: ${primary_root}"
  git -C "${primary_root}" worktree list --porcelain 2>/dev/null | grep -qxF "worktree ${wt}" \
    || ai_die "Worktree '${wt}' is not registered in '${primary_root}'s git worktree list — refusing (unregistered checkout, sibling repository, or stale/removed worktree)."
  printf '%s\n' "${primary_root}"
}

# ---------------------------------------------------------------------------
# Path allowlist / denylist enforcement (see AI_WORKFLOW.md, "Mechanical
# scope enforcement"). Every check here is fail-closed: an unmatched
# path is rejected, never silently allowed through.
# ---------------------------------------------------------------------------

# Usage: ai_validate_allowed_path_spec <line>
# Validates ONE line of an issue's "Allowed paths" section. Rejects
# vague/unsafe values per AI_WORKFLOW.md and the issue forms.
ai_validate_allowed_path_spec() {
  local raw="$1"
  local line="${raw%$'\r'}"
  [[ -n "${line}" ]] || ai_die "Empty allowed-path line is not permitted."
  # Reject control characters (anything below 0x20 except none allowed here).
  if printf '%s' "${line}" | LC_ALL=C grep -qP '[\x00-\x1f]'; then
    ai_die "Allowed-path line contains control characters: ${line}"
  fi
  [[ "${line}" != /* ]] || ai_die "Allowed-path line is an absolute path, rejected: ${line}"
  [[ "${line}" != *".."* ]] || ai_die "Allowed-path line contains '..', rejected: ${line}"
  [[ "${line}" != "*" ]] || ai_die "Allowed-path line is the bare wildcard '*', rejected."
  [[ "${line}" != "/**" ]] || ai_die "Allowed-path line is '/**' (entire repository), rejected."
  [[ "${line}" != "**" ]] || ai_die "Allowed-path line is '**' (entire repository), rejected."
  case "$(printf '%s' "${line}" | tr '[:upper:]' '[:lower:]')" in
    "as needed"|"relevant files"|"entire repository"|"tbd"|"n/a"|"none")
      ai_die "Allowed-path line is a vague placeholder, rejected: ${line}" ;;
  esac
}

# Usage: ai_glob_match <path> <pattern>
# Pattern may end in /* (direct children only) or /** (anything under
# it, including nested), or be an exact file path. No shell expansion
# is ever performed on the pattern — it's matched with bash's own
# extglob-free [[ == ]] pattern matching against a literal string.
ai_glob_match() {
  local path="$1" pattern="$2"
  case "${pattern}" in
    */\*\*)
      local prefix="${pattern%\*\*}"
      [[ "${path}" == "${prefix}"* ]]
      ;;
    */\*)
      local prefix="${pattern%\*}"
      [[ "${path}" == "${prefix}"* && "${path#"${prefix}"}" != */* ]]
      ;;
    */)
      [[ "${path}" == "${pattern}"* ]]
      ;;
    *)
      [[ "${path}" == "${pattern}" ]]
      ;;
  esac
}

# Usage: ai_path_is_dependency_manifest <path>
# Structural check (not a policy-array pattern list — glob patterns
# can't cleanly express "any requirements*.txt at any depth"). A
# dependency manifest is hard-denied for ordinary automated dispatch
# in v1 regardless of an issue's own Allowed-paths list; see
# AI_WORKFLOW.md, "Risk and dependency enforcement."
ai_path_is_dependency_manifest() {
  local path="$1"
  case "${path}" in
    pyproject.toml|*/pyproject.toml) return 0 ;;
    uv.lock|*/uv.lock) return 0 ;;
    requirements.txt|*/requirements.txt) return 0 ;;
    requirements-*.txt|*/requirements-*.txt) return 0 ;;
    poetry.lock|*/poetry.lock) return 0 ;;
    Pipfile|*/Pipfile|Pipfile.lock|*/Pipfile.lock) return 0 ;;
    package.json|*/package.json|package-lock.json|*/package-lock.json) return 0 ;;
    yarn.lock|*/yarn.lock|pnpm-lock.yaml|*/pnpm-lock.yaml) return 0 ;;
    Cargo.toml|*/Cargo.toml|Cargo.lock|*/Cargo.lock) return 0 ;;
    go.mod|*/go.mod|go.sum|*/go.sum) return 0 ;;
    *) return 1 ;;
  esac
}

# Usage: ai_path_is_migration <path>
# Same rationale as ai_path_is_dependency_manifest above.
ai_path_is_migration() {
  local path="$1"
  case "${path}" in
    migrations/*|*/migrations/*) return 0 ;;
    migration/*|*/migration/*) return 0 ;;
    *.migration.*) return 0 ;;
    alembic/*|*/alembic/*) return 0 ;;
    *) return 1 ;;
  esac
}

# Usage: ai_path_is_denylisted <path>
# Checks dependency manifests, migration paths, and policy's
# protected_documents / protected_control_plane / frozen_subsystems.
# Returns 0 (true) if denylisted.
ai_path_is_denylisted() {
  local path="$1" pattern
  ai_path_is_dependency_manifest "${path}" && return 0
  ai_path_is_migration "${path}" && return 0
  while IFS= read -r pattern; do
    [[ -n "${pattern}" ]] && ai_glob_match "${path}" "${pattern}" && return 0
  done <<<"$(ai_policy_get_array '.paths.protected_documents[]')"
  while IFS= read -r pattern; do
    [[ -n "${pattern}" ]] && ai_glob_match "${path}" "${pattern}" && return 0
  done <<<"$(ai_policy_get_array '.paths.protected_control_plane[]')"
  while IFS= read -r pattern; do
    [[ -n "${pattern}" ]] && ai_glob_match "${path}" "${pattern}" && return 0
  done <<<"$(ai_policy_get_array '.paths.frozen_subsystems[]')"
  return 1
}

# Usage: ai_path_is_allowed <path> <newline-separated-allowed-patterns>
ai_path_is_allowed() {
  local path="$1" allowed_patterns="$2" pattern
  while IFS= read -r pattern; do
    [[ -n "${pattern}" ]] && ai_glob_match "${path}" "${pattern}" && return 0
  done <<<"${allowed_patterns}"
  return 1
}

# ---------------------------------------------------------------------------
# Checked git output capture — never `< <(git ...)` for a security
# boundary. Process substitution runs the producer in a SUBSHELL; a
# failure inside that subshell (a non-zero git exit, or even an
# internal `ai_die`/`exit`) is invisible to the consuming loop and to
# the parent script — the exact class of bug this section closes.
# ---------------------------------------------------------------------------

# Usage: ai_run_git_capture OUTPUT_FILE -- git args...
# Runs the given git command as a plain FOREGROUND command (no
# subshell, no process substitution) so its real exit status is
# directly checkable by the caller via `if ! ai_run_git_capture ...`.
#   - stdout goes to OUTPUT_FILE, which the caller must place outside
#     any git worktree being operated on (the trusted run directory —
#     see ai_run_log_root — not inside the checkout under test/review).
#   - stderr is captured SEPARATELY (a sibling ".stderr" file next to
#     OUTPUT_FILE) for diagnostics, never mixed into OUTPUT_FILE.
#   - on non-zero exit, OUTPUT_FILE is deleted (never left behind as a
#     partial/misleading artifact) and this function returns non-zero.
#   - no caller may append `|| true`/`|| :` to a call to this function
#     for a security-relevant operation — that would defeat the entire
#     point of capturing the real exit status.
ai_run_git_capture() {
  local output_file="$1"; shift
  [[ "${1:-}" == "--" ]] || ai_die "ai_run_git_capture: expected '--' before the git command, got '${1:-<nothing>}'."
  shift
  [[ "$1" == "git" ]] || ai_die "ai_run_git_capture: command must start with 'git', got '${1}'."

  [[ ! -e "${output_file}" || ! -L "${output_file}" ]] || ai_die "ai_run_git_capture: refusing to write through a symlink: ${output_file}"
  local stderr_file="${output_file}.stderr"

  # `rc` is captured via `|| rc=$?` attached DIRECTLY to the command —
  # deliberately not via a separate `local rc=$?` line placed after an
  # `if cmd; then ...; fi` with no `else`. Found live, empirically,
  # during this pass's own testing: when that `if`'s condition is
  # false and its then-branch never runs, bash gives the WHOLE if
  # statement an exit status of 0 (no branch executed = success, per
  # POSIX) — so a `$?` read after `fi` silently reports 0 even though
  # the guarded command genuinely failed. That bug would have made
  # this exact function — the one this pass added specifically to stop
  # git failures from being swallowed — swallow them itself.
  local rc=0
  "$@" >"${output_file}" 2>"${stderr_file}" || rc=$?

  if [[ "${rc}" -eq 0 ]]; then
    rm -f "${stderr_file}"
    return 0
  fi

  local stderr_excerpt
  stderr_excerpt="$(ai_redact <"${stderr_file}" 2>/dev/null | ai_bounded_output 500)"
  ai_log_error "ai_run_git_capture: command failed (exit ${rc}): $* — stderr: ${stderr_excerpt}"
  rm -f "${output_file}" "${stderr_file}"
  return "${rc}"
}

# Usage: ai_enumerate_changed_paths <worktree> <output-file>
# Writes each changed path (staged, unstaged, AND untracked; run with
# --no-renames so every record is exactly "XY PATH", never a
# two-path rename record), NUL-terminated with the 3-character status
# prefix already stripped, to <output-file> — created via
# ai_run_git_capture, so a git failure deletes any partial output and
# this function returns non-zero rather than silently handing back a
# possibly-partial file list. Callers MUST check this function's
# return status (never invoke it inside `< <(...)`) and MUST read
# <output-file> back via plain redirection (`< file`, not `<(...)`)
# so THAT read, too, runs in the caller's own shell, not a subshell.
#
# Nothing here touches embedded newlines: git's own -z stream is read
# one full NUL-terminated record at a time from a real file, never
# re-joined through a newline-based tool (awk/tr) — a prior version's
# `awk 'BEGIN{RS="\0"}' | tr '\n' '\0'` pipeline corrupted any filename
# containing an embedded newline by rewriting it into a NUL and
# silently splitting one filename into two entries.
ai_enumerate_changed_paths() {
  local worktree="$1" output_file="$2"
  local raw_tmp
  mkdir -p "$(ai_run_log_root)"
  raw_tmp="$(mktemp "$(ai_run_log_root)/enum-raw.XXXXXX")" || { ai_log_error "Could not create a temp file for changed-path enumeration."; return 1; }

  if ! ai_run_git_capture "${raw_tmp}" -- git -C "${worktree}" status --porcelain=v1 -z --no-renames -- .; then
    ai_log_error "git status failed while enumerating changed paths in ${worktree} — refusing to produce a possibly-partial authoritative file list."
    return 1
  fi
  ai_require_not_symlink "${raw_tmp}"

  : >"${output_file}"
  local entry
  while IFS= read -r -d '' entry; do
    printf '%s\0' "${entry:3}" >>"${output_file}"
  done <"${raw_tmp}"
  rm -f "${raw_tmp}"
}

# Usage: ai_validate_changed_paths <worktree> <allowed-patterns-newline-separated>
# Enumerates changed paths (NUL-delimited, via ai_enumerate_changed_paths
# above — a checked temp file, never a process substitution) relative
# to HEAD in the given worktree — covers staged, unstaged, AND
# untracked files, so it is safe to call both before and after a
# commit. Dies on the first path that is denylisted (including
# dependency manifests and migration paths), unmatched by the
# allowlist, is a symlink escape, or is one of the explicitly-forbidden
# artifact names. Also dies (rather than silently validating an empty
# list) if the underlying enumeration itself failed.
ai_validate_changed_paths() {
  local worktree="$1" allowed_patterns="$2"
  local forbidden_names=("STOP_REASON.txt" ".env" ".env.local")
  local path name forbidden
  local enum_file
  mkdir -p "$(ai_run_log_root)"
  enum_file="$(mktemp "$(ai_run_log_root)/enum-changed.XXXXXX")" || ai_die "Could not create a temp file for changed-path validation."

  if ! ai_enumerate_changed_paths "${worktree}" "${enum_file}"; then
    rm -f "${enum_file}"
    ai_die "Could not enumerate changed paths in ${worktree} (git failed) — refusing to validate a possibly-partial file list."
  fi

  while IFS= read -r -d '' path; do
    [[ -n "${path}" ]] || continue

    name="$(basename -- "${path}")"
    for forbidden in "${forbidden_names[@]}"; do
      [[ "${name}" == "${forbidden}" ]] && { rm -f "${enum_file}"; ai_die "Changed path uses a forbidden artifact name: ${path}"; }
    done
    case "${path}" in
      *.log|*credential*|*secret*|Temp/ai-runs/*|Temp/ai-worktrees/*)
        rm -f "${enum_file}"; ai_die "Changed path looks like run metadata/logs/credentials, rejected: ${path}" ;;
    esac

    if [[ -e "${worktree}/${path}" ]]; then
      ai_require_not_symlink "${worktree}/${path}"
      ai_require_under_parent "${worktree}/${path}" "${worktree}"
    fi

    ai_path_is_denylisted "${path}" && { rm -f "${enum_file}"; ai_die "Changed path is hard-denylisted by policy: ${path}"; }
    ai_path_is_allowed "${path}" "${allowed_patterns}" \
      || { rm -f "${enum_file}"; ai_die "Changed path is not covered by the approved allowlist: ${path}"; }
  done <"${enum_file}"
  rm -f "${enum_file}"
}

# ---------------------------------------------------------------------------
# Branch protection — fail closed on every unknown/malformed/absent/
# unsafe state. See AI_WORKFLOW.md, "Branch protection is fail-closed."
# ---------------------------------------------------------------------------

# Usage: ai_require_branch_protection <branch>
# Dies (does not warn) when: the API call fails for any reason
# (network, auth, 403, 404 — all indistinguishable in their effect on
# this function: none of them proves protection exists), the response
# is missing a required field, PR-review enforcement can't be
# confirmed, force-push prevention can't be confirmed, deletion
# prevention can't be confirmed, required status checks can't be
# confirmed, or admin/bypass enforcement can't be confirmed. This is
# read-only — it never modifies branch protection, only inspects it —
# so it runs identically in dry-run and execute modes.
#
# HONEST LIMITATION: this does not, and cannot, prove that the specific
# credential `gh` is authenticated as is incapable of bypassing
# protection — GitHub does not expose "is actor X exempt from rule Y"
# as a queryable boolean for classic branch protection. What it DOES
# confirm mechanically: `enforce_admins.enabled == true` (protection
# applies even to admin-capable roles, which is the closest classic
# branch protection gets to "no one bypasses this"), and that no
# active repository ruleset declares ANY bypass actor at all — checked
# conservatively for every active ruleset repository-wide, not scoped
# to rulesets whose target we can independently confirm covers this
# branch, specifically because a false "this ruleset doesn't apply
# here" is exactly the kind of assumption this function exists to
# never make.
ai_require_branch_protection() {
  local branch="$1"
  ai_require_gh_auth
  ai_require_cmd jq
  local repo
  repo="$(ai_repo_slug)"

  local err_file body
  err_file="$(mktemp)"
  if ! body="$(gh api "repos/${repo}/branches/${branch}/protection" -H "Accept: application/vnd.github+json" 2>"${err_file}")"; then
    local err_text
    err_text="$(cat "${err_file}" 2>/dev/null)"
    rm -f "${err_file}"
    ai_die "Branch protection check FAILED CLOSED for '${branch}': the GitHub API call did not succeed (${err_text:-no output}). This could mean no protection is configured, insufficient permission to inspect it, or a transient failure — this function cannot distinguish those cases and must not proceed in any of them. Configure branch protection and/or grant read access, then retry. Never treat this as a warning."
  fi
  rm -f "${err_file}"

  jq -e 'type == "object"' >/dev/null 2>&1 <<<"${body}" \
    || ai_die "Branch protection response for '${branch}' is not a JSON object — malformed response, failing closed."

  local pr_required review_count enforce_admins force_push_allowed deletion_allowed checks_configured
  pr_required="$(jq -r 'if (.required_pull_request_reviews == null) then "false" elif (.required_pull_request_reviews == false) then "error" else "true" end' <<<"${body}" 2>/dev/null)" || pr_required="error"
  review_count="$(jq -r '.required_pull_request_reviews.required_approving_review_count // -1' <<<"${body}" 2>/dev/null)" || review_count="-1"
  enforce_admins="$(jq -r '.enforce_admins.enabled' <<<"${body}" 2>/dev/null)"
  force_push_allowed="$(jq -r '.allow_force_pushes.enabled' <<<"${body}" 2>/dev/null)"
  deletion_allowed="$(jq -r '.allow_deletions.enabled' <<<"${body}" 2>/dev/null)"
  checks_configured="$(jq -r '(.required_status_checks != null) and (((.required_status_checks.contexts // []) | length) > 0 or ((.required_status_checks.checks // []) | length) > 0)' <<<"${body}" 2>/dev/null)"

  for pair in "pr_required:${pr_required}" "enforce_admins:${enforce_admins:-}" "force_push_allowed:${force_push_allowed:-}" "deletion_allowed:${deletion_allowed:-}" "checks_configured:${checks_configured:-}"; do
    local field_name="${pair%%:*}" field_value="${pair#*:}"
    case "${field_value}" in
      ""|null|error) ai_die "Branch protection field '${field_name}' for '${branch}' is missing, null, or unreadable — failing closed." ;;
    esac
  done

  [[ "${pr_required}" == "true" && "${review_count}" -ge 1 ]] \
    || ai_die "Branch protection for '${branch}' does not confirm pull-request review enforcement (required_pull_request_reviews with >=1 required approval) — failing closed."
  [[ "${force_push_allowed}" == "false" ]] \
    || ai_die "Branch protection for '${branch}' allows force pushes (or this cannot be confirmed) — failing closed."
  [[ "${deletion_allowed}" == "false" ]] \
    || ai_die "Branch protection for '${branch}' allows branch deletion (or this cannot be confirmed) — failing closed."
  [[ "${checks_configured}" == "true" ]] \
    || ai_die "Branch protection for '${branch}' has no required status checks configured — failing closed."
  [[ "${enforce_admins}" == "true" ]] \
    || ai_die "Branch protection for '${branch}' does not enforce rules for admin/bypass-capable roles (enforce_admins is not true) — the automation credential's ability to bypass protection cannot be ruled out. Failing closed."

  # Bypass-actor check via the repository-wide rulesets API — see the
  # HONEST LIMITATION note above for why this is deliberately
  # conservative (every active ruleset, not just ones we can prove
  # target this branch).
  local rulesets_body
  if ! rulesets_body="$(gh api "repos/${repo}/rulesets" -H "Accept: application/vnd.github+json" 2>/dev/null)"; then
    ai_die "Could not enumerate repository rulesets while checking for bypass actors on '${branch}' — failing closed (cannot confirm the current credential is unable to bypass protection)."
  fi
  jq -e 'type == "array"' >/dev/null 2>&1 <<<"${rulesets_body}" \
    || ai_die "Rulesets response was not a JSON array — malformed, failing closed."

  # Extracting active-ruleset IDs is done via a checked variable, not
  # `< <(... || true)` — a jq failure here must not silently become
  # "zero rulesets to check" (a fail-OPEN outcome for a security
  # check), even though the input was already validated as a JSON
  # array above and a real jq failure at this specific step is
  # unlikely. Checked anyway, on principle: a security check's
  # producer failing is never treated as "nothing to check."
  local active_ruleset_ids
  if ! active_ruleset_ids="$(jq -r '[.[] | select(.enforcement=="active")] | .[].id' <<<"${rulesets_body}" 2>/dev/null)"; then
    ai_die "Could not extract active ruleset IDs from the rulesets response while checking for bypass actors — failing closed."
  fi

  local ruleset_id
  while IFS= read -r ruleset_id; do
    [[ -n "${ruleset_id}" ]] || continue
    local ruleset_detail bypass_actor_count
    if ! ruleset_detail="$(gh api "repos/${repo}/rulesets/${ruleset_id}" -H "Accept: application/vnd.github+json" 2>/dev/null)"; then
      ai_die "Could not fetch ruleset ${ruleset_id} detail while checking for bypass actors — failing closed."
    fi
    bypass_actor_count="$(jq -r '(.bypass_actors // []) | length' <<<"${ruleset_detail}" 2>/dev/null)" \
      || ai_die "Malformed ruleset ${ruleset_id} detail — failing closed."
    [[ "${bypass_actor_count}" -eq 0 ]] \
      || ai_die "Repository ruleset ${ruleset_id} declares ${bypass_actor_count} bypass actor(s) — cannot confirm the current automation credential is excluded from bypassing protection. Failing closed."
  done <<<"${active_ruleset_ids}"

  ai_log_info "Branch protection for '${branch}' confirmed: PR review required (>=${review_count}), force-push disallowed, deletion disallowed, required checks configured, enforced for admins, no active-ruleset bypass actors."
}

# ---------------------------------------------------------------------------
# Base-SHA freshness — an approval is bound to an EXACT base SHA, not
# "an ancestor of current main." See AI_WORKFLOW.md, "Base SHA
# freshness."
# ---------------------------------------------------------------------------

ai_current_main_sha() {
  local branch
  branch="$(ai_policy_get '.branch.protected')"
  git fetch origin "${branch}" --quiet 2>/dev/null \
    || ai_die "Could not fetch origin/${branch} to check base-SHA freshness — failing closed."
  git rev-parse "origin/${branch}" 2>/dev/null \
    || ai_die "Could not resolve origin/${branch}'s SHA after fetch — failing closed."
}

# Usage: ai_require_fresh_base_sha <approved-base-sha>
ai_require_fresh_base_sha() {
  local approved_base_sha="$1" current
  current="$(ai_current_main_sha)"
  [[ "${current}" == "${approved_base_sha}" ]] \
    || ai_die "Approval's base SHA (${approved_base_sha}) no longer equals the current origin/main SHA (${current}) — main has advanced since approval. v1 requires an EXACT match, not 'ancestor of main' — a fresh approval is required."
}

# ---------------------------------------------------------------------------
# Atomic claim — GitHub's create-reference API, not a branch push. A
# push of an identical SHA to an existing ref can report success
# without being a reliable compare-and-set; POST /git/refs either
# creates a brand-new ref (success) or fails (already exists / any
# other non-success), and this function treats anything other than a
# response that explicitly confirms the ref+sha it asked for as an
# ambiguous failure — never as a successful claim.
# ---------------------------------------------------------------------------

# Usage: ai_create_claim_ref <full-ref-e.g.-refs/heads/ai-claims/...> <sha>
ai_create_claim_ref() {
  local ref="$1" sha="$2" repo
  repo="$(ai_repo_slug)"
  git check-ref-format --branch "${ref#refs/heads/}" >/dev/null 2>&1 \
    || ai_die "Claim ref '${ref}' fails git check-ref-format --branch — refusing to attempt an invalid ref."
  [[ "${sha}" =~ ^[0-9a-f]{40}$ ]] || ai_die "Claim SHA '${sha}' is not a 40-character lowercase hex SHA — refusing."

  local err_file response
  err_file="$(mktemp)"
  if response="$(gh api "repos/${repo}/git/refs" --method POST \
        -H "Accept: application/vnd.github+json" \
        -f "ref=${ref}" -f "sha=${sha}" 2>"${err_file}")"; then
    rm -f "${err_file}"
    # Never trust a zero exit code alone as proof of a NEW ref at the
    # SHA we asked for — the response body must actually confirm both.
    jq -e --arg ref "${ref}" --arg sha "${sha}" \
      '.ref == $ref and .object.sha == $sha' >/dev/null 2>&1 <<<"${response}" \
      || ai_die "Claim ref creation for '${ref}' returned a response that does not confirm ref='${ref}' sha='${sha}' — treating as ambiguous, failing closed. Response (redacted, truncated): $(printf '%s' "${response}" | ai_redact | head -c 500)"
    ai_log_info "Claim ref created atomically: ${ref} @ ${sha:0:12}"
    return 0
  fi

  local err_text
  err_text="$(cat "${err_file}" 2>/dev/null)"
  rm -f "${err_file}"
  if grep -qiE 'HTTP 422|Reference already exists' <<<"${err_text}"; then
    ai_die "Claim ref '${ref}' already exists (HTTP 422 — already claimed, by this run or another). Refusing (replay or duplicate claim)."
  fi
  ai_die "Claim ref creation for '${ref}' failed ambiguously (neither a clean success nor a clear 'already exists'): ${err_text}. Failing closed — an ambiguous response, including a network failure after the request was sent, is NEVER treated as a successful claim."
}

# ---------------------------------------------------------------------------
# Isolation — empirically tested, not assumed. See AI_WORKFLOW.md,
# "Codex review isolation."
# ---------------------------------------------------------------------------

ai_bwrap_available() { command -v bwrap >/dev/null 2>&1; }

# Empirically confirms bubblewrap's --unshare-net actually blocks
# outbound network access from inside the sandbox, rather than
# assuming the flag works because the binary exists and accepted the
# flag. Makes a REAL connection attempt from inside a live sandbox and
# requires it to fail. Returns 0 only when that real attempt failed
# (i.e. network genuinely is isolated); returns 1 on any other outcome
# (bwrap missing, or the connection attempt unexpectedly succeeded).
ai_verify_network_isolation() {
  ai_bwrap_available || return 1
  timeout 5 bwrap \
    --unshare-net \
    --ro-bind /usr /usr --ro-bind /bin /bin --dev /dev --proc /proc --tmpfs /tmp \
    -- timeout 3 bash -c 'exec 3<>/dev/tcp/1.1.1.1/80' >/dev/null 2>&1
  local rc=$?
  [[ "${rc}" -ne 0 ]]
}

# ---------------------------------------------------------------------------
# Run manifests — dispatcher-owned, outside git, under the configured
# run-manifest root. See AI_WORKFLOW.md, "Registered dispatch worktree
# verification."
# ---------------------------------------------------------------------------

# Usage: ai_write_run_manifest <path> <json>
# Writes the manifest and a sidecar SHA-256 of its exact bytes. The
# sidecar is what ai_read_run_manifest checks on read — this is local
# tamper detection (defense against a stray edit or a stale copy), not
# a cryptographic identity guarantee; see AI_WORKFLOW.md for the honest
# scope of that claim.
ai_write_run_manifest() {
  local path="$1" json="$2"
  mkdir -p "$(dirname "${path}")"
  printf '%s' "${json}" | jq . >"${path}"
  ai_sha256_file "${path}" >"${path}.sha256"
}

# Usage: ai_read_run_manifest <path> -> prints the manifest JSON on
# stdout. Dies on: missing manifest, missing sidecar hash, hash
# mismatch, a symlink, or an unrecognized schema.
ai_read_run_manifest() {
  local path="$1"
  ai_require_not_symlink "${path}"
  [[ -f "${path}" ]] || ai_die "Run manifest missing: ${path}"
  [[ -f "${path}.sha256" ]] || ai_die "Run manifest hash sidecar missing: ${path}.sha256"
  local expected actual
  expected="$(cat "${path}.sha256")"
  actual="$(ai_sha256_file "${path}")"
  [[ "${expected}" == "${actual}" ]] \
    || ai_die "Run manifest hash mismatch for ${path} (expected ${expected}, got ${actual}) — possibly tampered or corrupted. Failing closed."
  jq -e 'type == "object" and .schema == "heimei-run-manifest/v1"' <"${path}" >/dev/null 2>&1 \
    || ai_die "Run manifest ${path} is malformed or has an unrecognized schema."
  cat "${path}"
}

# ---------------------------------------------------------------------------
# Locking — never run two control-plane tasks simultaneously. This is
# a LOCAL flock only — see AI_WORKFLOW.md: it prevents two concurrent
# runs on ONE machine, and must never be described as distributed
# locking or as a substitute for the atomic claim-ref operation above.
# ---------------------------------------------------------------------------

_AI_LOCK_FD=""

ai_acquire_lock() {
  local lock_path="$1"
  mkdir -p "$(dirname "${lock_path}")"
  exec {_AI_LOCK_FD}>"${lock_path}"
  if ! flock -n "${_AI_LOCK_FD}"; then
    ai_die "Another AI control-plane task appears to be running on this machine (lock held: ${lock_path}). Refusing to run concurrently. This local lock does not, and is not claimed to, prevent a second run on a DIFFERENT machine — see the atomic claim-ref operation for that."
  fi
  ai_log_info "Acquired local lock: ${lock_path}"
}

ai_release_lock() {
  if [[ -n "${_AI_LOCK_FD}" ]]; then
    flock -u "${_AI_LOCK_FD}" 2>/dev/null || true
    exec {_AI_LOCK_FD}>&- 2>/dev/null || true
    _AI_LOCK_FD=""
  fi
}

# Only the lock is released automatically on exit. Nothing else —
# worktree removal is never automatic; see dispatch.sh for the
# explicit, success-only cleanup call.
ai_trap_lock_only() {
  trap ai_release_lock EXIT
}

# ---------------------------------------------------------------------------
# Worktree safety — no eval, explicit validation before any removal
# ---------------------------------------------------------------------------

# Usage: ai_worktree_path <branch-name>
ai_worktree_path() {
  local branch_name="$1"
  local safe_name="${branch_name//\//-}"
  printf '%s/%s\n' "$(ai_worktree_root)" "${safe_name}"
}

# Usage: ai_run_log_dir <issue-number>
ai_run_log_dir() {
  local issue_number="$1"
  local stamp
  stamp="$(date -u +"%Y%m%dT%H%M%SZ")"
  printf '%s/issue-%s-%s\n' "$(ai_run_log_root)" "${issue_number}" "${stamp}"
}

# Usage: ai_safe_remove_worktree <repo-root> <worktree-path>
# Only ever called explicitly, only after every success condition in
# AI_WORKFLOW.md's cleanup rules has already been confirmed by the
# caller. Re-validates independently anyway — defense in depth, not
# trust in the caller:
#   - worktree path resolves via realpath and is NOT a symlink
#   - resolved path is directly under the configured worktree root
#   - resolved path is not the primary checkout
#   - the worktree's own git status is clean
# On any doubt: refuses and leaves the worktree in place.
ai_safe_remove_worktree() {
  local repo_root="$1" worktree="$2"
  local real_root real_worktree real_repo_root
  real_repo_root="$(ai_realpath_strict "${repo_root}")"

  if [[ ! -e "${worktree}" ]]; then
    ai_log_warn "Worktree already absent, nothing to remove: ${worktree}"
    return 0
  fi
  ai_require_not_symlink "${worktree}"
  real_worktree="$(ai_realpath_strict "${worktree}")"
  real_root="$(ai_realpath_strict "$(ai_worktree_root)")"

  case "${real_worktree}" in
    "${real_root}"/*) ;;
    *) ai_log_error "Refusing to remove worktree outside configured root: ${real_worktree}"; return 1 ;;
  esac
  [[ "${real_worktree}" != "${real_repo_root}" ]] \
    || { ai_log_error "Refusing to remove the primary checkout."; return 1; }

  if [[ -n "$(git -C "${real_worktree}" status --porcelain 2>&1)" ]]; then
    ai_log_error "Refusing to remove a dirty worktree: ${real_worktree}"
    return 1
  fi

  ai_log_info "Removing clean, validated worktree: ${real_worktree}"
  git -C "${real_repo_root}" worktree remove -- "${real_worktree}"
}

# ---------------------------------------------------------------------------
# Real verification transcripts — actual captured stdout/stderr, never
# a synthetic "PASS"/"FAIL" string invented after the fact. See
# AI_WORKFLOW.md, "Real verification transcripts."
# ---------------------------------------------------------------------------

# Usage: ai_run_check <name> <log-file> <cmd...>
# Runs <cmd...>, capturing its REAL combined stdout+stderr to
# <log-file> (never synthesized). Sets these globals for the caller to
# read immediately afterward (they are overwritten by the next call):
#   LAST_CHECK_CMD       exact command string actually run
#   LAST_CHECK_START     UTC timestamp before running
#   LAST_CHECK_END       UTC timestamp after running
#   LAST_CHECK_EXIT      real exit code
#   LAST_CHECK_SHA256    SHA-256 of the exact transcript file
#   LAST_CHECK_EXCERPT   redacted, size-bounded excerpt of the transcript
# Returns the command's real exit code. If AI_RUN_CHECK_TIMEOUT_SECONDS
# is set to a positive integer, the command is wrapped in `timeout` —
# a bounded run that times out reports the real `timeout`-assigned
# exit code (124), not a fabricated one.
LAST_CHECK_CMD=""
LAST_CHECK_START=""
LAST_CHECK_END=""
LAST_CHECK_EXIT=""
LAST_CHECK_SHA256=""
LAST_CHECK_EXCERPT=""

ai_run_check() {
  local name="$1" log_file="$2"
  shift 2
  LAST_CHECK_CMD="$(IFS=' '; echo "$*")"
  LAST_CHECK_START="$(ai_log_ts)"
  ai_log_info "Running: ${name} (${LAST_CHECK_CMD})"

  local timeout_s="${AI_RUN_CHECK_TIMEOUT_SECONDS:-0}"
  if [[ "${timeout_s}" =~ ^[1-9][0-9]*$ ]]; then
    if timeout "${timeout_s}" "$@" >"${log_file}" 2>&1; then
      LAST_CHECK_EXIT=0
    else
      LAST_CHECK_EXIT=$?
    fi
  else
    if "$@" >"${log_file}" 2>&1; then
      LAST_CHECK_EXIT=0
    else
      LAST_CHECK_EXIT=$?
    fi
  fi

  LAST_CHECK_END="$(ai_log_ts)"
  LAST_CHECK_SHA256="$(ai_sha256_file "${log_file}")"
  LAST_CHECK_EXCERPT="$(ai_redact <"${log_file}" | ai_bounded_output "${AI_RUN_CHECK_EXCERPT_BYTES:-4000}")"

  if [[ "${LAST_CHECK_EXIT}" -eq 0 ]]; then
    ai_log_info "PASS: ${name}"
  else
    ai_log_error "FAIL: ${name} (exit ${LAST_CHECK_EXIT}) — see ${log_file}"
  fi
  return "${LAST_CHECK_EXIT}"
}

# ---------------------------------------------------------------------------
# Failure reporting — used on every non-success exit path
# ---------------------------------------------------------------------------

# Usage: ai_report_failure <worktree> <branch> <reason>
# Prints exactly what AI_WORKFLOW.md promises on failure: worktree
# path, branch, local commit SHA if one exists, the reason, and safe
# recovery commands. Never touches the worktree.
ai_report_failure() {
  local worktree="$1" branch="$2" reason="$3"
  local local_sha="none"
  if [[ -d "${worktree}/.git" || -f "${worktree}/.git" ]]; then
    local_sha="$(git -C "${worktree}" rev-parse HEAD 2>/dev/null || echo none)"
  fi
  cat >&2 <<EOF

================================================================================
FAILURE — work preserved locally, nothing was pushed or posted
================================================================================
  Worktree:        ${worktree}
  Branch:          ${branch}
  Local commit SHA: ${local_sha}
  Reason:          ${reason}

Safe recovery commands:
  cd '${worktree}' && git status
  cd '${worktree}' && git diff
  cd '${worktree}' && git log --oneline -5

Nothing here was cleaned up automatically. Inspect, fix by hand, or
discard the worktree yourself once you've looked at it:
  git -C '$(ai_repo_root)' worktree remove --force '${worktree}'   # only once YOU decide it's safe
================================================================================
EOF
}
