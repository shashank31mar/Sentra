#!/usr/bin/env python3
"""Render a Markdown file to a print-styled HTML, then to PDF via headless Chrome.

Usage:
    python scripts/md_to_pdf.py pitch/how-it-works.md

Produces <name>.pdf next to the source. The transient HTML intermediate Chrome
needs is written to the system temp dir (never next to the source) and deleted
afterward, so no .html ever lands in the repo. Supports ```mermaid```
fenced blocks (rendered to SVG via a locally-bundled mermaid.js + Chrome's
virtual-time budget). Keeps the repo's "styled HTML -> Chrome --print-to-pdf"
convention. Multi-page output is fine for longer docs.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MERMAID_JS = Path(__file__).parent / "assets" / "mermaid.min.js"

CSS = """
  @page { size: Letter; margin: 0.6in 0.7in; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    color: #1c2330; font-size: 11px; line-height: 1.45;
    -webkit-font-smoothing: antialiased;
  }
  h1 { font-size: 20px; font-weight: 800; color: #0f1b2d; margin: 0 0 4px 0; letter-spacing: -0.2px; }
  h2 {
    font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;
    color: #1559c9; margin: 16px 0 6px 0; padding-bottom: 3px; border-bottom: 1px solid #d7deea;
  }
  h3 { font-size: 11.5px; font-weight: 800; color: #0f1b2d; margin: 12px 0 4px 0; }
  h4 { font-size: 11px; font-weight: 800; color: #2a3650; margin: 10px 0 4px 0; }
  p { margin: 0 0 6px 0; }
  ul, ol { margin: 0 0 6px 0; padding-left: 18px; }
  li { margin: 0 0 3px 0; }
  strong { color: #0f1b2d; }
  em { color: #2a3650; }
  a { color: #1559c9; text-decoration: none; }
  hr { border: 0; border-top: 1px solid #d7deea; margin: 12px 0; }
  blockquote {
    margin: 8px 0; padding: 6px 12px; border-left: 3px solid #1559c9;
    background: #f4f7fc; color: #2a3650;
  }
  code {
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 9.5px;
    background: #eef2f8; padding: 1px 4px; border-radius: 3px;
  }
  pre {
    background: #0f1b2d; color: #e6edf6; padding: 10px 12px; border-radius: 5px;
    overflow-x: auto; page-break-inside: avoid;
  }
  pre code { background: none; color: inherit; font-size: 8.6px; line-height: 1.35; padding: 0; }
  table { border-collapse: collapse; width: 100%; margin: 6px 0 10px 0; font-size: 9.6px; page-break-inside: avoid; }
  th, td { border: 1px solid #cfd8e8; padding: 4px 7px; text-align: left; vertical-align: top; }
  th { background: #eef2f8; color: #0f1b2d; font-weight: 700; }
  tr:nth-child(even) td { background: #f7f9fd; }
  /* mermaid diagrams */
  pre.mermaid {
    background: #fbfcfe; color: inherit; border: 1px solid #e2e8f3; border-radius: 6px;
    padding: 12px; text-align: center; page-break-inside: avoid;
  }
  pre.mermaid svg { max-width: 100%; height: auto; }
"""


def _ensure_blank_line_before_tables(text: str) -> str:
    """Python-Markdown's `tables` extension only recognizes a table when it
    starts its own block. Insert a blank line before a table row that follows a
    non-blank, non-table line so the table always renders."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        is_table_row = line.lstrip().startswith("|")
        prev = out[-1] if out else ""
        prev_is_blank_or_table = (prev.strip() == "") or prev.lstrip().startswith("|")
        if is_table_row and not prev_is_blank_or_table:
            out.append("")
        out.append(line)
    return "\n".join(out)


def _extract_mermaid(text: str):
    """Pull ```mermaid``` blocks out before Markdown runs (so the source isn't
    mangled/escaped), leaving a placeholder to swap back post-render."""
    blocks: list[str] = []

    def repl(m: "re.Match") -> str:
        blocks.append(m.group(1).strip("\n"))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}ENDMERMAID\n\n"

    text = re.sub(r"```mermaid\n(.*?)```", repl, text, flags=re.S)
    return text, blocks


def _reinsert_mermaid(html: str, blocks: list[str]) -> str:
    for i, block in enumerate(blocks):
        div = f'<pre class="mermaid">\n{block}\n</pre>'
        for variant in (f"<p>MERMAIDBLOCK{i}ENDMERMAID</p>", f"MERMAIDBLOCK{i}ENDMERMAID"):
            if variant in html:
                html = html.replace(variant, div)
                break
    return html


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/md_to_pdf.py <file.md>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1]).resolve()
    text = src.read_text(encoding="utf-8")
    text, mermaid_blocks = _extract_mermaid(text)
    text = _ensure_blank_line_before_tables(text)
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists", "attr_list"]
    )
    body = _reinsert_mermaid(body, mermaid_blocks)

    mermaid_head = ""
    if mermaid_blocks:
        mermaid_js = MERMAID_JS.read_text(encoding="utf-8")
        mermaid_head = (
            f"<script>{mermaid_js}</script>"
            "<script>mermaid.initialize({startOnLoad:true, theme:'neutral', "
            "securityLevel:'loose', themeVariables:{fontSize:'13px'}, "
            "flowchart:{useMaxWidth:true, htmlLabels:true, curve:'basis', nodeSpacing:34, rankSpacing:34}});</script>"
        )

    html = (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{src.stem}</title><style>{CSS}</style>{mermaid_head}</head><body>{body}</body></html>"
    )

    pdf_path = src.with_suffix(".pdf")
    # The HTML is a throwaway intermediate for Chrome. Write it to the system
    # temp dir (never next to the source) so no .html ever lands in the repo,
    # even if this process is interrupted before cleanup.
    fd, tmp_html = tempfile.mkstemp(suffix=".html", prefix=f"{src.stem}-")
    html_path = Path(tmp_html)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(html)

    cmd = [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer"]
    if mermaid_blocks:
        # let mermaid's JS render to SVG before the PDF snapshot is taken
        cmd.append("--virtual-time-budget=20000")
    cmd += [f"--print-to-pdf={pdf_path}", html_path.as_uri()]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        # the HTML is only an intermediate for Chrome; never leave it behind
        html_path.unlink(missing_ok=True)
    print(f"wrote {pdf_path.name}"
          + (f" ({len(mermaid_blocks)} mermaid diagram(s))" if mermaid_blocks else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
