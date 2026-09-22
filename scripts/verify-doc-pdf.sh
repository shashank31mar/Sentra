#!/usr/bin/env bash
# Verify a rendered doc PDF: valid file, and every mermaid diagram actually drawn.
#
# Why this exists: a broken diagram does NOT leak its source into the PDF. mermaid
# catches the parse error and draws a "Syntax error in text" graphic instead, so
# grepping for `flowchart TD` finds nothing and the doc looks clean while a page
# carries an error box. Both failure modes are checked here.
#
# Usage:  bash scripts/verify-doc-pdf.sh path/to/doc.pdf [path/to/doc.md]
#
# Exit codes
#   0  valid PDF, no mermaid failures
#   2  a mermaid diagram failed to render (error graphic in the PDF)
#   3  raw mermaid source leaked into the PDF (renderer never ran)
#   4  invalid or empty PDF
#   5  poppler missing (pdftotext / pdfinfo not installed)
#   6  source .md contains characters that break the render pipeline
set -uo pipefail

PDF="${1:-}"
SRC="${2:-}"

if [[ -z "$PDF" ]]; then
  echo "usage: bash scripts/verify-doc-pdf.sh <doc.pdf> [doc.md]" >&2
  exit 1
fi

command -v pdftotext >/dev/null 2>&1 || { echo "FAIL: pdftotext not found (brew install poppler)" >&2; exit 5; }
command -v pdfinfo   >/dev/null 2>&1 || { echo "FAIL: pdfinfo not found (brew install poppler)" >&2; exit 5; }

# --- 1. the PDF is real
if [[ ! -s "$PDF" ]]; then
  echo "FAIL: $PDF is missing or empty" >&2
  exit 4
fi
PAGES=$(pdfinfo "$PDF" 2>/dev/null | awk '/^Pages:/ {print $2}')
if [[ -z "${PAGES:-}" || "$PAGES" -lt 1 ]]; then
  echo "FAIL: $PDF is not a readable PDF" >&2
  exit 4
fi

TEXT=$(pdftotext "$PDF" - 2>/dev/null)

# --- 2. a diagram failed to parse: mermaid drew its error graphic
if grep -qiE 'syntax error in text|mermaid version' <<<"$TEXT"; then
  echo "FAIL: a mermaid diagram failed to render — the PDF contains an error graphic." >&2
  echo "      mermaid rendered 'Syntax error in text' in place of a diagram." >&2
  echo "      Fix the diagram source; re-rendering the same source will not help." >&2
  exit 2
fi

# --- 3. the renderer never ran at all: raw source is sitting in the text layer
if grep -qE '^\s*(flowchart|sequenceDiagram|stateDiagram|graph (TD|LR|TB))\b|classDef ' <<<"$TEXT"; then
  echo "FAIL: raw mermaid source leaked into $PDF — the renderer did not run." >&2
  grep -nE '^\s*(flowchart|sequenceDiagram|stateDiagram|graph (TD|LR|TB))\b' <<<"$TEXT" | head -5 >&2
  exit 3
fi

# --- 4. pre-flight on the source, if given: characters that silently break things
if [[ -n "$SRC" && -f "$SRC" ]]; then
  BAD=$(python3 - "$SRC" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
problems = []
# Inside a mermaid fence, ';' is a statement separator and '<' starts a tag.
for block in re.findall(r"```mermaid\n(.*?)```", src, re.S):
    for line in block.splitlines():
        if ";" in line:
            problems.append(f"mermaid: ';' is a statement separator -> {line.strip()[:70]}")
        if "<" in line and "<br/>" not in line:
            problems.append(f"mermaid: '<' is read as HTML -> {line.strip()[:70]}")
# In a table cell, '<word ...>' is eaten by the markdown-to-HTML step.
for line in src.splitlines():
    if line.startswith("|") and re.search(r"<[A-Za-z][^>]*>", line):
        problems.append(f"table: angle brackets are stripped -> {line.strip()[:70]}")
print("\n".join(problems))
PY
)
  if [[ -n "$BAD" ]]; then
    echo "FAIL: $SRC has constructs that break the render pipeline:" >&2
    echo "$BAD" >&2
    exit 6
  fi
fi

echo "OK: $PDF — $PAGES page(s), all diagrams rendered"
exit 0
