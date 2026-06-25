#!/usr/bin/env python3
"""Generate the Design Partner LOI as a .docx for legal review.
Source of truth is letter-of-intent-template.md; this mirrors its content."""

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = "letter-of-intent-template.docx"

doc = Document()

# Base style
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(11)


def para(text="", bold=False, italic=False, size=None, align=None, space_after=6):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    if size:
        run.font.size = Pt(size)
    p.paragraph_format.space_after = Pt(space_after)
    return p


def rich(segments, align=None, space_after=6):
    """segments: list of (text, bold, italic)."""
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    for text, bold, italic in segments:
        r = p.add_run(text)
        r.bold = bold
        r.italic = italic
    p.paragraph_format.space_after = Pt(space_after)
    return p


def heading(text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(13)
    r.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    return p


# ---- Title ----
para("LETTER OF INTENT", bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
para("AI-Agent Safety Design Partnership", italic=True, size=12,
     align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)

# ---- Letterhead ----
para("AegionAI, LLC", bold=True, space_after=0)
para("[Street Address] · [City, State ZIP]", space_after=12)
para("[Month DD, YYYY]", space_after=12)

# ---- Recipient ----
para("To: [Recipient Name], [Title]", space_after=0)
para("[Company Legal Name]", bold=True, space_after=0)
para("[Address]", space_after=12)

rich([("Re: Letter of Intent — AegionAI AI-Agent Safety Design Partnership", True, False)],
     space_after=12)

para("Dear [Name],", space_after=8)

rich([
    ("This letter sets out the mutual intent of ", False, False),
    ("AegionAI, LLC", True, False),
    (" (“AegionAI”) and ", False, False),
    ("[Company Legal Name]", True, False),
    (" (“[Company]”) to enter a design partnership under which AegionAI’s "
     "runtime safety layer for AI agents will be deployed and evaluated in [Company]’s "
     "environment. Except where expressly stated in Sections 7, 8, and 10, ", False, False),
    ("this letter is non-binding", True, False),
    (" and reflects intent only.", False, False),
], space_after=8)

# ---- 1 ----
heading("1. Purpose")
para("The parties intend to collaborate as design partners to deploy, evaluate, and shape "
     "AegionAI’s enforcement platform around [Company]’s production AI-agent "
     "infrastructure, with the goal of converting to a commercial agreement at the end of the "
     "partnership term.")

# ---- 2 ----
heading("2. Background")
para("[Company] runs AI agents that [take real actions — e.g. issue refunds / move funds / "
     "update customer records] across [AWS and Azure / clouds]. Today these agents can act "
     "wrongly with real access, and [Company] requires (a) the ability to stop a harmful action "
     "before it executes, and (b) an exportable audit trail sufficient for "
     "[PCI-DSS / RBI / EU AI Act / SOC 2] obligations. AegionAI provides this enforcement layer "
     "across every cloud from one control plane.")

# ---- 3 (table) ----
heading("3. Scope of the Pilot")
rows = [
    ("Deployment model",
     "[Multi-tenant cloud service / single-tenant in [Company]’s VPC / on-prem air-gapped]"),
    ("Agents & tools in scope",
     "[e.g. refund agent + payments API; transfer agent + ledger writes]"),
    ("Environment",
     "[Company] staging environment; no production traffic touched without written approval"),
    ("Integration", "One-line SDK wrapper per tool, instrumented jointly"),
    ("Success criteria",
     "The measurable outcomes [Company] cares about, agreed in writing at kickoff — e.g. "
     "[block ≥1 unauthorized action in staging; produce an exportable audit trail for a "
     "sample refund flow; <[X]ms added latency]"),
    ("Term & duration",
     "A [6-week] evaluation followed by a [6-month] design-partner period — approximately "
     "[7 months] total from the Effective Date — unless extended or ended earlier by mutual "
     "written agreement (see Section 7)"),
]
table = doc.add_table(rows=len(rows), cols=2)
table.style = "Light Grid Accent 1"
for i, (k, v) in enumerate(rows):
    c0, c1 = table.rows[i].cells
    c0.paragraphs[0].add_run(k).bold = True
    c1.paragraphs[0].add_run(v)
doc.add_paragraph().paragraph_format.space_after = Pt(2)

# ---- 4 ----
heading("4. Indicative Terms (non-binding — for planning only)")
for t in [
    ("No license cost", " for the design-partner period."),
    ("No design fee", " during the design-partner period."),
    ("Permanent preferred pricing",
     ": the commercial rate locked at the end of the term is [Company]’s indefinitely, "
     "never subject to standard increases."),
    (None, "Any commercial terms that apply after the design-partner period will be set out in, "
           "and take effect only under, the definitive agreement (see Section 6)."),
]:
    p = doc.add_paragraph(style="List Bullet")
    if t[0]:
        p.add_run(t[0]).bold = True
    p.add_run(t[1])

# ---- 5 ----
heading("5. Mutual Commitments (intended, non-binding)")
p = doc.add_paragraph()
p.add_run("AegionAI will provide: ").bold = True
p.add_run("founder-led weekly sync (1 hr/week); [Company]’s priority use case scheduled and "
          "shipped within 3 weeks of agreement; early access to new capabilities 30 days before "
          "general availability.")
p = doc.add_paragraph()
p.add_run("[Company] will provide:").bold = True
for b in [
    "An executive sponsor and ~2 hrs/week from a senior platform engineer (able to instrument the "
    "integration and give architectural feedback).",
    "Access to a staging environment with representative agent traffic.",
    "The success metrics [Company] will use to judge the pilot, agreed at kickoff, plus a joint "
    "review against them at the end of the term.",
    "Regular feedback on the product and roadmap during the weekly sync.",
    "A reference — a short joint case study and/or a reference call to a future AegionAI "
    "prospect — subject to [Company]’s approval of any public use of its name.",
]:
    doc.add_paragraph(b, style="List Bullet")

# ---- 6 ----
heading("6. Path to a Definitive Agreement")
para("The parties intend to negotiate and execute a Design Partner Agreement (incorporating "
     "security/data terms, intellectual-property terms, and the commitments above) by "
     "[target date]. That agreement, once signed, supersedes this letter and is the binding "
     "contract between the parties.")

# ---- 7 ----
heading("7. No Obligation to Continue")
para("Neither party is obligated to continue beyond the evaluation or the design-partner term. "
     "At the end of the term, either party may decline to enter a commercial agreement for any "
     "reason and without penalty. On conclusion, each party will, on request, return or delete "
     "the other’s confidential information, and AegionAI will remove its instrumentation from "
     "[Company]’s environment. The confidentiality and intellectual-property terms below "
     "survive.")

# ---- 8 ----
heading("8. Confidentiality & Intellectual Property (binding)")
p = doc.add_paragraph()
p.add_run("Confidentiality. ").bold = True
p.add_run("Each party will treat the other’s non-public information — including "
          "AegionAI’s enforcement design and [Company]’s agent topology, configurations, "
          "and traffic — as confidential, used only to evaluate this partnership and not "
          "disclosed to third parties. [If a mutual NDA is already in place: “This section is "
          "governed by the mutual NDA dated [date], which controls in the event of any "
          "conflict.”]")
p = doc.add_paragraph()
p.add_run("Intellectual property. ").bold = True
p.add_run("Each party retains all right, title, and interest in its own pre-existing and "
          "independently developed intellectual property. AegionAI retains all rights in the "
          "AegionAI platform, software, and any improvements or derivatives developed during the "
          "partnership; [Company] retains all rights in its applications, agents, and data. No "
          "license is granted except the limited, non-exclusive right to use the other "
          "party’s IP solely as needed to carry out the pilot. This section is binding and "
          "survives termination of discussions.")

# ---- 9 ----
heading("9. Non-Binding Effect")
para("Except for Sections 7, 8, and 10, this letter creates no binding obligation on either "
     "party, imposes no exclusivity, and does not obligate either party to enter any further "
     "agreement. No purchase, payment, or commitment arises unless and until a definitive Design "
     "Partner Agreement is signed by both parties.")

# ---- 10 ----
heading("10. Governing Law (binding)")
para("This letter is governed by the laws of the State of [Delaware / __], without regard to "
     "conflict-of-laws principles.")

# ---- Signatures ----
doc.add_paragraph().paragraph_format.space_after = Pt(6)
para("If this reflects [Company]’s intent, please countersign below. We’re excited to "
     "build this with you.", space_after=10)
para("Sincerely,", space_after=18)

for name, title in [
    ("Shashank Gupta", "Founder & CEO — AegionAI, LLC"),
    ("Sylvester Fernandez", "Co-Founder — AegionAI, LLC"),
]:
    para("____________________________", space_after=0)
    rich([(name, True, False), (", " + title, False, False)], space_after=2)
    para("Date: ____________________", space_after=14)

para("Acknowledged and agreed (intent only):", bold=True, space_after=18)
para("____________________________", space_after=0)
rich([("[Recipient Name]", True, False), (", [Title] — [Company Legal Name]", False, False)],
     space_after=2)
para("Date: ____________________", space_after=0)

doc.save(OUT)
print("wrote", OUT)
