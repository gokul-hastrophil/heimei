#!/usr/bin/env bash
# Scripts/ai/agent-git.sh
#
# A narrow, read-only `git` wrapper. NOT currently exposed to the
# automated Claude implementer in v1 (Claude gets no Bash tool at all —
# see AI_WORKFLOW.md, "Claude implementation: no shell or Git
# authority"), and NOT exposed to any automated Codex invocation
# (Codex automated implementation is disabled in v1; Codex automated
# review never auto-invokes Codex either — see "Codex review
# isolation"). This script exists as tooling for any future capability
# that legitimately needs restricted, read-only git access from inside
# a worktree, and is covered by regression tests here specifically
# because a real defect was found in an earlier version of it.
#
# THE REPORTED DEFECT, for the record: the earlier version dispatched
# `status`/`diff`/`show`/`log` as `exec git "${SUBCOMMAND}" -- "$@"` —
# unconditionally inserting `--` before all remaining arguments. For
# `agent-git.sh status --short`, that became `git status -- --short`,
# which git parses as "run status, then treat `--short` as a
# PATHSPEC" (because of the `--`), not as the `--short` OPTION. Since
# no file is named "--short", git silently reported a CLEAN tree
# regardless of the real state of the working tree — a false "clean"
# on every dirty, staged, or untracked-file repository whenever an
# option was passed. This version never does a single "exec git
# $subcommand -- $@" passthrough of unvalidated arguments; every
# invocation below is reconstructed argument-by-argument from an
# explicit, narrow, per-subcommand grammar, so there is no path left
# where an option can be silently reinterpreted as a pathspec (or vice
# versa), and no path where a global option (-C, -c, --git-dir,
# --work-tree, --config-env) can reach git at all — the grammar below
# has no slot for one.
#
# Usage: AI_AGENT_WORKTREE=<realpath> agent-git.sh <subcommand> [args...]
#
# HONEST LIMITATION (do not remove this comment when editing this
# file): this wrapper is a permission boundary only as strong as
# whatever invokes it actually routing every git-shaped call through
# it instead of calling the real `git` binary directly — neither
# Claude Code's `--allowedTools` nor Codex's `--sandbox`, as of the
# CLI versions inspected for this change, can force *all* git
# invocations through a specific wrapper and reject a direct call to
# the real `git` binary outright; both are scoped by command PREFIX
# (e.g. `Bash(agent-git.sh *)`), not by intercepting other Bash calls
# an agent might attempt. See AI_WORKFLOW.md, "CLI tool restrictions
# are not proven enforcement boundaries," for why v1 does not rely on
# this script as the isolation boundary for automated dispatch at all.
set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

usage() {
  cat <<'EOF'
Usage: AI_AGENT_WORKTREE=<realpath> agent-git.sh <subcommand> [args...]

Permitted invocations (exact grammar — nothing else is accepted, and
nothing is ever passed through to git unvalidated):
  status
  status --short
  status --porcelain=v1
  diff
  diff --stat
  diff -- <repo-relative-path>...
  show <validated-commit-ish>
  log --oneline -n <bounded-positive-integer>
  rev-parse HEAD
  rev-parse --show-toplevel
  branch --show-current

AI_AGENT_WORKTREE must name an existing, non-symlink directory that is
registered as a git worktree of a Heimei checkout (verified against
that checkout's own `git worktree list`, not merely "has a .git file
that points somewhere plausible").
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 64
fi

# ---------------------------------------------------------------------------
# Registered-worktree verification — every invocation, no exceptions.
# ---------------------------------------------------------------------------

WORKTREE_RAW="${AI_AGENT_WORKTREE:-}"
[[ -n "${WORKTREE_RAW}" ]] || ai_die "AI_AGENT_WORKTREE is not set — refusing to guess a worktree."
ai_require_not_symlink "${WORKTREE_RAW}"
WT="$(ai_realpath_strict "${WORKTREE_RAW}")"
[[ -d "${WT}/.git" || -f "${WT}/.git" ]] || ai_die "AI_AGENT_WORKTREE is not a git checkout: ${WT}"
ai_require_registered_worktree "${WT}" >/dev/null

# ---------------------------------------------------------------------------
# Argument validators — used only to decide whether a call is allowed,
# never to "sanitize" an argument for reuse. A value that fails
# validation is rejected outright, not modified and retried.
# ---------------------------------------------------------------------------

validate_commit_ish() {
  local c="$1"
  [[ "${c}" != -* ]] || ai_die "agent-git.sh: commit identifier must not start with '-': ${c}"
  [[ "${c}" =~ ^[A-Za-z0-9._/^~]+$ ]] || ai_die "agent-git.sh: commit identifier contains disallowed characters: ${c}"
  [[ "${c}" != *".."* ]] || ai_die "agent-git.sh: commit identifier contains '..': ${c}"
}

validate_bounded_log_count() {
  local n="$1"
  [[ "${n}" =~ ^[1-9][0-9]{0,2}$ ]] || ai_die "agent-git.sh: log -n value must be a bounded positive integer (1-999): ${n}"
}

validate_repo_relative_path() {
  local p="$1"
  [[ "${p}" != -* ]] || ai_die "agent-git.sh: path must not start with '-': ${p}"
  [[ "${p}" != /* ]] || ai_die "agent-git.sh: path must be repository-relative, not absolute: ${p}"
  [[ "${p}" != *".."* ]] || ai_die "agent-git.sh: path must not contain '..': ${p}"
  [[ -n "${p}" ]] || ai_die "agent-git.sh: empty path argument."
  if [[ -e "${WT}/${p}" ]]; then
    ai_require_not_symlink "${WT}/${p}"
    ai_require_under_parent "${WT}/${p}" "${WT}"
  fi
}

# ---------------------------------------------------------------------------
# Explicit, narrow per-subcommand grammar. Every branch below invokes
# git with an argv built entirely from literals and validated values —
# never `"$@"` forwarded wholesale, never a `--` inserted ahead of an
# argument that might actually be an option.
# ---------------------------------------------------------------------------

SUBCOMMAND="$1"
shift

case "${SUBCOMMAND}" in
  status)
    if [[ $# -eq 0 ]]; then
      exec git -C "${WT}" status
    elif [[ $# -eq 1 && "$1" == "--short" ]]; then
      exec git -C "${WT}" status --short
    elif [[ $# -eq 1 && "$1" == "--porcelain=v1" ]]; then
      exec git -C "${WT}" status --porcelain=v1
    else
      ai_die "agent-git.sh: unsupported 'status' invocation: $*"
    fi
    ;;

  diff)
    if [[ $# -eq 0 ]]; then
      exec git -C "${WT}" diff
    elif [[ $# -eq 1 && "$1" == "--stat" ]]; then
      exec git -C "${WT}" diff --stat
    elif [[ $# -ge 2 && "$1" == "--" ]]; then
      shift
      declare -a paths=()
      for p in "$@"; do
        validate_repo_relative_path "${p}"
        paths+=("${p}")
      done
      exec git -C "${WT}" diff -- "${paths[@]}"
    else
      ai_die "agent-git.sh: unsupported 'diff' invocation: $*"
    fi
    ;;

  show)
    [[ $# -eq 1 ]] || ai_die "agent-git.sh: 'show' takes exactly one commit argument, got: $*"
    validate_commit_ish "$1"
    exec git -C "${WT}" show "$1"
    ;;

  log)
    [[ $# -eq 3 && "$1" == "--oneline" && "$2" == "-n" ]] \
      || ai_die "agent-git.sh: 'log' requires exactly '--oneline -n <bounded-number>', got: $*"
    validate_bounded_log_count "$3"
    exec git -C "${WT}" log --oneline -n "$3"
    ;;

  rev-parse)
    [[ $# -eq 1 ]] || ai_die "agent-git.sh: 'rev-parse' takes exactly one argument, got: $*"
    case "$1" in
      HEAD|--show-toplevel) exec git -C "${WT}" rev-parse "$1" ;;
      *) ai_die "agent-git.sh: 'rev-parse' only permits HEAD or --show-toplevel, got: $1" ;;
    esac
    ;;

  branch)
    [[ $# -eq 1 && "$1" == "--show-current" ]] \
      || ai_die "agent-git.sh: 'branch' only permits '--show-current', got: $*"
    exec git -C "${WT}" branch --show-current
    ;;

  *)
    ai_die "agent-git.sh: unrecognized or unsupported subcommand '${SUBCOMMAND}' — not on the read-only allowlist. commit/push/fetch/checkout/reset/clean/merge/rebase/remote/config/worktree and every other mutating subcommand are never permitted through this wrapper; the trusted dispatcher performs all commits, pushes, and ref/config changes."
    ;;
esac
