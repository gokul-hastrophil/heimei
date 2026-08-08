#!/usr/bin/env bash
# Scripts/ai/bootstrap-github.sh
#
# Idempotent GitHub bootstrap for the Heimei AI development control
# plane. Creates any required label that's missing and safely updates
# the color/description of any that already exist. Never deletes a
# label. Never touches branch protection — those settings are printed
# for Gokul to apply by hand. See AI_WORKFLOW.md for the policy this
# implements, and State/Reports/ai-development-control-plane.md for
# "What remains manual."
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

usage() {
  cat <<'EOF'
Usage: bootstrap-github.sh [--dry-run] [--execute]

  --dry-run   Print what would be created/updated. Default if no flag given.
  --execute   Actually create/update labels via gh. Required for any change.

Never deletes an existing label. Never touches branch protection —
prints the manual settings to apply instead.
EOF
}

EXECUTE=0

for arg in "$@"; do
  case "${arg}" in
    --dry-run) EXECUTE=0 ;;
    --execute) EXECUTE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) ai_log_error "Unknown argument: ${arg}"; usage; exit 2 ;;
  esac
done

ai_require_cmd jq
ai_require_gh_auth

REPO="$(ai_repo_slug)"
ai_log_info "Target repository: ${REPO}"
if [[ "${EXECUTE}" -eq 0 ]]; then
  ai_log_info "DRY RUN — no labels will be created or changed. Pass --execute to apply."
fi

# name|color|description  (colors are 6-digit hex, no leading '#')
LABELS=(
  "type:architecture|5319e7|Architecture decision or subsystem-level change - highest scrutiny, see CONSTITUTION.md"
  "type:feature|0e8a16|New, additive capability inside an already-approved design"
  "type:bug|d73a4a|Incorrect behavior relative to its own ADR, docstring, or tests"
  "type:maintenance|fbca04|Non-behavioral upkeep: dependencies, docs, tooling"
  "type:research|1d76db|Investigation only - no implementation authorized yet"
  "status:needs-approval|ededed|Default state - no agent may act on this issue yet"
  "status:approved|0e8a16|Gokul approved scope - authorizes exactly one named agent, see AI_WORKFLOW.md"
  "status:in-progress|fbca04|An agent is actively implementing this issue"
  "status:review|1d76db|Draft PR open and CI triggered - not yet owner review"
  "status:owner-review|5319e7|CI green and independent review available - needs Gokul"
  "status:blocked|d73a4a|Correction loop exhausted or a human decision is required"
  "agent:claude|c5def5|Claude Code is the authorized implementer for this issue"
  "agent:codex|bfd4f2|Codex is the authorized implementer for this issue"
  "risk:low|c2e0c6|Low risk"
  "risk:medium|fef2c0|Medium risk - extra reviewer attention"
  "risk:high|d93f0b|Blocks automated dispatch - requires explicit human handling"
  "frozen-subsystem|b60205|Touches a frozen subsystem's behavior - blocks automated dispatch without a separate approval"
  "breaking-change|e11d21|Changes existing public behavior - blocks automated dispatch"
  "dependency-change|fbca04|Adds or changes a dependency - blocks automated dispatch without review"
  "database-migration|5319e7|Requires a data migration - blocks automated dispatch without an explicit override"
)

existing_labels="$(gh label list --repo "${REPO}" --json name --jq '.[].name' --limit 200 2>/dev/null || true)"

created=0
updated=0

for entry in "${LABELS[@]}"; do
  name="${entry%%|*}"
  rest="${entry#*|}"
  color="${rest%%|*}"
  description="${rest#*|}"

  if grep -qxF "${name}" <<<"${existing_labels}"; then
    ai_log_info "exists -> update color/description: ${name}"
    if [[ "${EXECUTE}" -eq 1 ]]; then
      gh label edit "${name}" --repo "${REPO}" --color "${color}" --description "${description}" >/dev/null
      updated=$((updated + 1))
    fi
  else
    ai_log_info "missing -> create: ${name}"
    if [[ "${EXECUTE}" -eq 1 ]]; then
      gh label create "${name}" --repo "${REPO}" --color "${color}" --description "${description}" >/dev/null
      created=$((created + 1))
    fi
  fi
done

if [[ "${EXECUTE}" -eq 1 ]]; then
  ai_log_info "Done. Created ${created}, updated ${updated}. Zero labels deleted (this script never deletes)."
else
  ai_log_info "Dry run complete — ${#LABELS[@]} labels checked. Re-run with --execute to apply."
fi

cat <<'EOF'

================================================================================
Manual branch-protection settings for "main"
(this script changes NONE of these automatically — apply by hand in
GitHub -> Settings -> Branches -> Branch protection rules):
================================================================================

  - Require a pull request before merging (blocks direct pushes to main)
  - Require approvals: at least 1 (Gokul)
  - Require status checks to pass before merging
      (add your CI workflow's job name(s) here once one exists -
       see AI_WORKFLOW.md, "CI" and its Next Actions)
  - Require branches to be up to date before merging
  - Do NOT enable "Allow auto-merge"
  - Do NOT enable "Allow force pushes"
  - Do NOT enable "Allow deletions"
  - Restrict who can push to matching branches: Gokul only

These are deliberately left manual - branch protection is a
repository-owner decision, not something a bootstrap script should be
able to silently reconfigure. See State/Reports/ai-development-control-plane.md,
"What remains manual."
EOF
