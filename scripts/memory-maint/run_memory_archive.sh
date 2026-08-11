#!/bin/bash
# Daily wrapper the launchd timer runs. Archives superseded memory notes, then prunes
# their lines from MEMORY.md so the index never dangles. Logs what moved.
set -euo pipefail

DIR="/Users/shshgup/code/security-mvp/Sentra/scripts/memory-maint"
MEM="/Users/shshgup/.claude/projects/-Users-shshgup-code-security-mvp-Sentra/memory"
LOG="$DIR/archive.log"

echo "=== $(date) memory-archive run ===" >> "$LOG"
"$DIR/archive_stale_memory.sh" --apply >> "$LOG" 2>&1 || echo "archive script exited $?" >> "$LOG"

# prune any MEMORY.md line linking to a now-archived file
/usr/bin/python3 - "$MEM" >> "$LOG" 2>&1 <<'PYEOF'
import os, sys
mem = sys.argv[1]
adir = os.path.join(mem, "archive")
archived = {f for f in os.listdir(adir) if f.endswith(".md")} if os.path.isdir(adir) else set()
idx = os.path.join(mem, "MEMORY.md")
kept, dropped = [], 0
for line in open(idx):
    if line.lstrip().startswith("- [") and any(f"({fn})" in line for fn in archived):
        dropped += 1
    else:
        kept.append(line)
if dropped:
    open(idx, "w").writelines(kept)
print(f"pruned {dropped} index line(s)")
PYEOF
echo "=== done $(date) ===" >> "$LOG"
