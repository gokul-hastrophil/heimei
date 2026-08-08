#!/usr/bin/env bash
# Scripts/ai/approve.sh
#
# Creates a trusted approval record for a GitHub issue — the actual
# authorization a dispatch run checks, per AI_WORKFLOW.md's "labels
# are state, not authority" rule. Only an allowlisted approver
# (.ai/policy.toml [approval].allowed_approvers) can create one, and
# it is bound to an exact digest of the issue body at approval time:
# editing the issue afterward invalidates it, since dispatch always
# recomputes and compares the digest.
#
# Usage:
#   ./Scripts/ai/approve.sh ISSUE --agent claude --risk low --dry-run
#   ./Scripts/ai/approve.sh ISSUE --agent claude --risk low --execute
#
# Dry-run is the default. Nothing is posted to GitHub without --execute.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

usage() {
  cat <<'EOF'
Usage: approve.sh ISSUE --agent <claude|codex> --risk <low|medium|high> [--dry-run|--execute]

  --agent claude|codex   Required. Must be in .ai/policy.toml's allowed agents.
  --risk low|medium|high Required. low, medium, and high are the three
                          recognized risk labels an issue may carry
                          (risk:low/risk:medium/risk:high) — but automated
                          approval accepts ONLY low or medium. --risk high
                          is rejected outright, before any mutation:
                          risk:high is never dispatchable in supervised
                          v1, and this script will not create an approval
                          record for it under any circumstance. A
                          risk:high (or unlabeled/frozen-subsystem/etc.)
                          issue requires a dedicated architecture-approval
                          record, not this script.
  --dry-run              Validate everything and print the record. Default.
  --execute              Actually post the approval comment and set
                          status:approved on the issue.

Fails closed on: unauthenticated gh, wrong repository identity, an
actor not in the approver allowlist, a closed issue, an incomplete
issue body, an invalid/vague Allowed-paths section, --risk high, a
--risk value that doesn't exactly match the issue's own risk:* label,
a missing/duplicate/unrecognized risk:* label, more than one agent
value, or a blocking label already present.
EOF
}

ISSUE_NUMBER=""
AGENT=""
RISK=""
EXECUTE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="${2:-}"; shift 2 ;;
    --risk) RISK="${2:-}"; shift 2 ;;
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

[[ -n "${ISSUE_NUMBER}" ]] || { ai_log_error "Missing ISSUE."; usage; exit 64; }
ai_validate_positive_int "${ISSUE_NUMBER}" "issue number"
[[ -n "${AGENT}" ]] || { ai_log_error "Missing --agent."; usage; exit 64; }
[[ -n "${RISK}" ]] || { ai_log_error "Missing --risk."; usage; exit 64; }
[[ "${RISK}" == "low" || "${RISK}" == "medium" || "${RISK}" == "high" ]] || ai_die "--risk must be low, medium, or high."

if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "DRY RUN — validating and printing the approval record only. Nothing will be posted."
fi

# ---------------------------------------------------------------------------
# Identity and authorization
# ---------------------------------------------------------------------------

ai_require_gh_auth
ai_require_cmd jq
ai_verify_repo_identity
REPO="$(ai_repo_slug)"
REPO_ID="$(ai_policy_get '.repository.id')"

ALLOWED_AGENTS="$(ai_policy_get_array '.agents.allowed[]')"
grep -qxF "${AGENT}" <<<"${ALLOWED_AGENTS}" || ai_die "Agent '${AGENT}' is not in .ai/policy.toml's allowed agents."

ACTOR="$(ai_current_actor)"
ai_require_approver "${ACTOR}"
ai_log_info "Authenticated actor: ${ACTOR} (allowlisted approver)"

# ---------------------------------------------------------------------------
# Issue validation
# ---------------------------------------------------------------------------

ISSUE_JSON="$(ai_issue_json "${ISSUE_NUMBER}")"
[[ "$(ai_issue_state "${ISSUE_JSON}")" == "OPEN" ]] || ai_die "Issue #${ISSUE_NUMBER} is not open."

LABELS="$(ai_issue_label_names "${ISSUE_JSON}")"
for blocking in "frozen-subsystem" "breaking-change" "database-migration" "dependency-change"; do
  grep -qxF "${blocking}" <<<"${LABELS}" && ai_die "Issue carries blocking label '${blocking}' — no override exists in v1. Requires a dedicated architecture-approval record, not this script."
done

# --- Risk: one source of truth — the issue's risk:* label, not just
# the --risk CLI argument. See AI_WORKFLOW.md, "Risk is one source of
# truth." ---------------------------------------------------------
ISSUE_RISK_LABEL="$(ai_require_single_risk_label "${LABELS}")"
[[ "${RISK}" == "${ISSUE_RISK_LABEL}" ]] \
  || ai_die "--risk '${RISK}' does not match the issue's risk:${ISSUE_RISK_LABEL} label — they must agree exactly. Update the label or the flag, then re-run."
[[ "${RISK}" != "high" ]] \
  || ai_die "risk:high is never dispatchable in v1 — rejected at approval, before any mutation. Requires a dedicated architecture-approval record, not this script."

ISSUE_TITLE="$(printf '%s' "${ISSUE_JSON}" | jq -r '.title')"
ISSUE_BODY="$(ai_issue_body_from_json "${ISSUE_JSON}")"
[[ -n "${ISSUE_BODY}" && "${ISSUE_BODY}" != "null" ]] || ai_die "Issue #${ISSUE_NUMBER} has an empty body."

SECTIONS_JSON="$(ai_issue_sections_json "${ISSUE_BODY}")"

require_nonempty_section() {
  local header="$1" value
  value="$(ai_issue_section "${SECTIONS_JSON}" "${header}")"
  case "$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" in
    ""|"_noresponse_"|"n/a"|"tbd"|"none")
      ai_die "Issue section '${header}' is empty or a placeholder — issue body is incomplete." ;;
  esac
  printf '%s' "${value}"
}

for header in "Problem" "Desired outcome" "Acceptance criteria"; do
  require_nonempty_section "${header}" >/dev/null
done
ALLOWED_PATHS_RAW="$(require_nonempty_section "Allowed paths")"

# ---------------------------------------------------------------------------
# Allowed-paths validation — machine-readable, mechanically enforced
# ---------------------------------------------------------------------------

declare -a NORMALIZED_PATHS=()
while IFS= read -r line; do
  line="$(printf '%s' "${line}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [[ -z "${line}" ]] && continue
  ai_validate_allowed_path_spec "${line}"
  # ai_path_is_denylisted also checks dependency manifests
  # (pyproject.toml, uv.lock, requirements*.txt, ...) and migration
  # paths — a dependency bump or migration always needs a dedicated,
  # separately-approved change, never bundled into an ordinary
  # feature/bug approval, regardless of what the issue's prose claims.
  ai_path_is_denylisted "${line}" && ai_die "Allowed-path line is hard-denylisted by policy (protected document/control-plane path, frozen subsystem, dependency manifest, or migration path) and can never be approved via an ordinary issue: ${line}"
  NORMALIZED_PATHS+=("${line}")
done <<<"${ALLOWED_PATHS_RAW}"

[[ "${#NORMALIZED_PATHS[@]}" -gt 0 ]] || ai_die "Allowed paths section produced zero valid path entries."

# Deduplicate and sort for a stable, canonical record.
ALLOWED_PATHS_CANONICAL="$(printf '%s\n' "${NORMALIZED_PATHS[@]}" | sort -u)"
ai_log_info "Validated $(printf '%s\n' "${ALLOWED_PATHS_CANONICAL}" | grep -c .) allowed-path pattern(s)."

# ---------------------------------------------------------------------------
# Digest, base SHA, approval ID
# ---------------------------------------------------------------------------

ISSUE_DIGEST="$(ai_issue_digest_from_json "${ISSUE_JSON}")"
BASE_SHA="$(git ls-remote origin refs/heads/main 2>/dev/null | cut -f1)"
[[ -n "${BASE_SHA}" ]] || ai_die "Could not resolve origin/main's current SHA via git ls-remote."

TIMESTAMP="$(ai_log_ts)"
APPROVAL_ID="appr-${ISSUE_NUMBER}-${ISSUE_DIGEST:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"

FORBIDDEN_PATHS_SUMMARY="$(cat <<EOF
$(ai_policy_get_array '.paths.protected_documents[]')
$(ai_policy_get_array '.paths.protected_control_plane[]')
$(ai_policy_get_array '.paths.frozen_subsystems[]')
EOF
)"

RECORD_JSON="$(jq -nc \
  --arg approval_id "${APPROVAL_ID}" \
  --arg repository_id "${REPO_ID}" \
  --argjson issue_number "${ISSUE_NUMBER}" \
  --arg approver "${ACTOR}" \
  --arg agent "${AGENT}" \
  --arg risk "${RISK}" \
  --arg issue_body_digest "${ISSUE_DIGEST}" \
  --arg allowed_paths "${ALLOWED_PATHS_CANONICAL}" \
  --arg forbidden_paths "${FORBIDDEN_PATHS_SUMMARY}" \
  --arg base_sha "${BASE_SHA}" \
  --arg timestamp "${TIMESTAMP}" \
  '{approval_id: $approval_id, repository_id: $repository_id, issue_number: $issue_number,
    approver: $approver, agent: $agent, risk: $risk, issue_body_digest: $issue_body_digest,
    allowed_paths: ($allowed_paths | split("\n") | map(select(length > 0))),
    forbidden_paths: ($forbidden_paths | split("\n") | map(select(length > 0))),
    base_sha: $base_sha, timestamp: $timestamp, schema: "heimei-approval/v1"}')"

COMMENT_BODY_FILE="$(mktemp)"
trap 'rm -f "${COMMENT_BODY_FILE}"' EXIT
{
  echo "## Heimei Approval Record"
  echo
  echo "Approval ID: \`${APPROVAL_ID}\`"
  echo "Approver: @${ACTOR}"
  echo "Agent: \`${AGENT}\` — Risk: \`${RISK}\`"
  echo "Base SHA: \`${BASE_SHA}\`"
  echo "Issue-body digest: \`${ISSUE_DIGEST}\`"
  echo
  echo "This record is single-use and replay-resistant: editing this issue"
  echo "changes its digest and invalidates this record. A dispatch run"
  echo "revalidates everything below against live state before acting on it."
  echo
  echo '```json'
  printf '%s\n' "${RECORD_JSON}" | jq .
  echo '```'
  echo
  echo "<!-- heimei-approval:v1 -->"
} >"${COMMENT_BODY_FILE}"

echo
echo "================================================================================"
echo "Approval record (issue #${ISSUE_NUMBER}, agent: ${AGENT}, risk: ${RISK})"
echo "================================================================================"
cat "${COMMENT_BODY_FILE}"
echo "================================================================================"

if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "Dry run complete. Nothing was posted. Re-run with --execute to create this record."
  exit 0
fi

ai_log_info "Posting approval comment to issue #${ISSUE_NUMBER}..."
COMMENT_URL="$(gh issue comment "${ISSUE_NUMBER}" --repo "${REPO}" --body-file "${COMMENT_BODY_FILE}")"
COMMENT_ID="$(ai_comment_id_from_url "${COMMENT_URL}")"
ai_log_info "Posted: ${COMMENT_URL} (comment id: ${COMMENT_ID:-unknown})"

ai_replace_status_label "${ISSUE_NUMBER}" "status:approved"
ai_log_info "Labeled status:approved (visible state only — this comment is the actual authorization)."

cat <<EOF

================================================================================
Approval created
================================================================================
  Approval ID:  ${APPROVAL_ID}
  Comment:      ${COMMENT_URL}
  Comment ID:   ${COMMENT_ID:-unknown}
================================================================================
EOF
