#!/usr/bin/env python3
"""Render a Markdown file to a print-styled HTML, then to PDF via headless Chrome.

Usage:
    python scripts/md_to_pdf.py pitch/how-it-works.md

Produces <name>.html and <name>.pdf next to the source. Keeps the repo's
existing "styled HTML -> Chrome --print-to-pdf" convention so output matches
one-pager.pdf. Multi-page output is fine for longer briefs.
"""
import subprocess
import sys
from pathlib import Path

import markdown

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

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
"""


def _ensure_blank_line_before_tables(text: str) -> str:
    """Python-Markdown's `tables` extension only recognizes a table when it
    starts its own block. If an author puts a table row directly under a
    non-blank line (e.g. a bold label), the table breaks. Insert a blank line
    in that case so the table always renders.
    """
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/md_to_pdf.py <file.md>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1]).resolve()
    text = src.read_text(encoding="utf-8")
    text = _ensure_blank_line_before_tables(text)
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists", "attr_list"]
    )
    html = (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{src.stem}</title><style>{CSS}</style></head><body>{body}</body></html>"
    )

    html_path = src.with_suffix(".html")
    pdf_path = src.with_suffix(".pdf")
    html_path.write_text(html, encoding="utf-8")

    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", html_path.as_uri()],
        check=True, capture_output=True,
    )
    print(f"wrote {html_path.name} and {pdf_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
