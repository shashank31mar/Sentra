#!/bin/bash
# Archive stale memory notes → memory/archive/ (reversible; never deletes).
#
# POLICY (founder call 2026-08-03, Option A): archive ONLY notes explicitly flagged
#   status: superseded   (any type, any age).
# The type:project + age rule is DISABLED — the type tags proved unreliable (durable notes
# like gtm-beachhead were mis-tagged type:project), so age/type auto-sweep would wrongly
# archive current knowledge. A note is archived only when something deliberately supersedes it.
# NEVER touches: any note without a superseded flag, MEMORY.md (the index), or anything
#   outside the memory dir (it CANNOT reach repo docs — lld/, tasks/, HLD live in git).
# This operates ONLY on ~/.claude .../memory/*.md — it CANNOT reach repo docs
# (lld/, tasks/, HLD live in the git repo, not here).
#
# Usage:  archive_stale_memory.sh [--apply]      (default = dry-run, prints what WOULD move)

set -euo pipefail

MEM="/Users/shshgup/.claude/projects/-Users-shshgup-code-security-mvp-Sentra/memory"
ARCHIVE="$MEM/archive"
MAX_AGE_DAYS=7
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

now=$(date +%s)
cutoff=$(( now - MAX_AGE_DAYS * 86400 ))
mkdir -p "$ARCHIVE"

moved=0
for f in "$MEM"/*.md; do
  base=$(basename "$f")
  [ "$base" = "MEMORY.md" ] && continue           # never archive the index

  # read type + superseded flag from frontmatter
  type=$(grep -m1 -E '^\s*type:' "$f" | sed 's/.*type:[[:space:]]*//' | tr -d ' \r' || true)
  superseded=$(grep -m1 -iE '^\s*(status|superseded):' "$f" | grep -iq 'superseded' && echo yes || echo no)
  mtime=$(stat -f "%m" "$f")

  reason=""
  if [ "$superseded" = "yes" ]; then
    reason="superseded"
  fi
  # (type:project + >${MAX_AGE_DAYS}d rule intentionally disabled — see POLICY note above)
  : "${type}" "${cutoff}"  # keep vars referenced; harmless no-op

  if [ -n "$reason" ]; then
    if [ "$APPLY" -eq 1 ]; then
      mv "$f" "$ARCHIVE/$base"
      echo "ARCHIVED [$reason]  $base"
    else
      echo "would archive [$reason]  $base"
    fi
    moved=$((moved+1))
  fi
done

if [ "$APPLY" -eq 1 ]; then
  echo "== archived $moved file(s) → $ARCHIVE =="
  echo "NOTE: prune the moved lines from MEMORY.md by hand or re-run the index step."
else
  echo "== DRY RUN: $moved file(s) would move. Re-run with --apply to do it. =="
fi
