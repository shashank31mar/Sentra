#!/usr/bin/env python3
"""Build the AegionAI $5M seed cost model workbook.

Live, editable model: inputs are literal values; subtotals / totals / runway are
Excel formulas (Excel and Numbers recalc on open). Every external number carries a
sourced citation on the Sources sheet. Currency = USD; India salaries in INR at the
FX rate on the Assumptions sheet.

Produces pitch/cost/AegionAI-Cost-Model.xlsx
"""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OUT = os.path.join(os.path.dirname(__file__), "AegionAI-Cost-Model.xlsx")

# ---------- palette ----------
NAVY = "0F1B2D"; BLUE = "1559C9"; LIGHT = "EEF2F8"; ZEBRA = "F7F9FD"
GREEN = "E7F4EA"; AMBER = "FCF3E2"; WHITE = "FFFFFF"; GREY = "5A6577"

H1 = Font(name="Calibri", size=16, bold=True, color=NAVY)
H2 = Font(name="Calibri", size=12, bold=True, color=WHITE)
HDR = Font(name="Calibri", size=10, bold=True, color=NAVY)
BOLD = Font(name="Calibri", size=10, bold=True, color=NAVY)
BODY = Font(name="Calibri", size=10, color="1C2330")
SMALL = Font(name="Calibri", size=9, color=GREY)
LINK = Font(name="Calibri", size=9, color=BLUE, underline="single")

FILL_H2 = PatternFill("solid", fgColor=BLUE)
FILL_HDR = PatternFill("solid", fgColor=LIGHT)
FILL_ZEBRA = PatternFill("solid", fgColor=ZEBRA)
FILL_TOTAL = PatternFill("solid", fgColor=NAVY)
FILL_GREEN = PatternFill("solid", fgColor=GREEN)
FILL_AMBER = PatternFill("solid", fgColor=AMBER)
TOTAL_FONT = Font(name="Calibri", size=10, bold=True, color=WHITE)

thin = Side(style="thin", color="CFD8E8")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
RIGHT = Alignment(horizontal="right")
CENTER = Alignment(horizontal="center", vertical="center")
WRAP = Alignment(wrap_text=True, vertical="top")
USD = '"$"#,##0'
USD2 = '"$"#,##0.00'
INR = '"₹"#,##0'
PCT = '0.0%'
NUM1 = '0.0'

wb = Workbook()

def sheet(title):
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    return ws

def band(ws, row, text, span=8):
    c = ws.cell(row=row, column=1, value=text)
    c.font = H2; c.fill = FILL_H2
    for col in range(1, span + 1):
        ws.cell(row=row, column=col).fill = FILL_H2
    ws.row_dimensions[row].height = 20
    return row + 1

def hdr(ws, row, cols, widths=None):
    for i, t in enumerate(cols, start=1):
        c = ws.cell(row=row, column=i, value=t)
        c.font = HDR; c.fill = FILL_HDR; c.border = BORDER
        c.alignment = WRAP if len(str(t)) > 14 else Alignment(vertical="top")
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    return row + 1

# =====================================================================
# 0. OVERVIEW  (built last for values, placed first)
# =====================================================================
ov = wb.active
ov.title = "Overview"
ov.sheet_view.showGridLines = False
for i, w in enumerate([34, 16, 16, 16, 14, 14, 14, 14], start=1):
    ov.column_dimensions[get_column_letter(i)].width = w

ov["A1"] = "AegionAI — Seed Cost Model & Runway"
ov["A1"].font = H1
ov["A2"] = "$5M raise · build-in-India / sell-in-US · target runway ≥ 40 months"
ov["A2"].font = SMALL
ov["A3"] = "All external figures are sourced (see Sources tab). Inputs are values; totals & runway are live formulas — edit the Assumptions/Team/Operating Costs tabs and everything recalcs."
ov["A3"].font = SMALL
ov.merge_cells("A3:H3"); ov["A3"].alignment = WRAP
ov.row_dimensions[3].height = 26

r = 5
r = band(ov, r, "  HEADLINE (Base scenario)")
# Formulas filled in after the referenced sheets are built (rows resolved dynamically).
HEAD_ROW_START = r
head_labels = [
    ("Total raise", USD),
    ("One-time costs", USD),
    ("Recurring burn / year", USD),
    ("Recurring burn / month", USD),
    ("RUNWAY (months) — Base", NUM1),
    ("Total headcount", '0'),
]
for label, fmt in head_labels:
    ov.cell(row=r, column=1, value=label).font = BODY
    c = ov.cell(row=r, column=2); c.font = BOLD; c.number_format = fmt; c.alignment = RIGHT
    r += 1

r += 1
r = band(ov, r, "  USE OF FUNDS — model vs. pitch claim (see reconciliation tab)")
ov.cell(row=r, column=1, value="Bucket").font = HDR
ov.cell(row=r, column=2, value="Model % of $5M").font = HDR
ov.cell(row=r, column=3, value="Pitch claim").font = HDR
for c in (1, 2, 3):
    ov.cell(row=r, column=c).fill = FILL_HDR; ov.cell(row=r, column=c).border = BORDER
r += 1
# these % cells reference the Use of Funds tab (rows resolved after it's built)
UOF_ROW_START = r
uof_labels = [
    ("Team — eng + product + leadership (India)", "~45% team"),
    ("GTM — programs (US seller deferred)", "in 'GTM'"),
    ("Cloud / AWS + AI coding tools", "~20% infra/GPU"),
    ("Physical infra & facilities", "in 'ops'"),
    ("Operations & G&A", "'ops'"),
    ("Compliance & certifications", "'compliance'"),
]
for label, pitch in uof_labels:
    ov.cell(row=r, column=1, value=label).font = BODY
    c = ov.cell(row=r, column=2); c.number_format = PCT; c.alignment = RIGHT; c.font = BODY
    ov.cell(row=r, column=3, value=pitch).font = SMALL
    r += 1

r += 1
note = ov.cell(row=r, column=1, value=(
    "KEY FLAG: the honest cost model is people-heavy (team + GTM ≈ 80% of spend); real cloud/infra is "
    "~5–10%, NOT the ~20% the pitch implies. A distilled model self-hosts on CPU (cheap), so you do NOT "
    "need ~$1M of GPU. Recommendation: either restate the pitch use-of-funds to reflect reality (investors "
    "expect seed money to go to people) OR carve out an explicit GPU/model-R&D line if you truly plan to spend it."
))
note.font = Font(name="Calibri", size=9, bold=True, color="8A5A00")
ov.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
ov.cell(row=r, column=1).fill = FILL_AMBER
ov.cell(row=r, column=1).alignment = WRAP
ov.row_dimensions[r].height = 52

# =====================================================================
# 1. ASSUMPTIONS
# =====================================================================
asm = sheet("Assumptions")
for i, w in enumerate([38, 16, 60], start=1):
    asm.column_dimensions[get_column_letter(i)].width = w
asm["A1"] = "Assumptions & Drivers"; asm["A1"].font = H1
r = 3
r = hdr(asm, r, ["Driver", "Value", "Note"])
# NOTE: these rows are referenced by formulas elsewhere — keep row order stable.
ASSUMP = [
    ("USD:INR FX rate", 90, "Used to convert India INR salaries to USD.", None),
    ("Total raise (USD)", 5000000, "Seed round per the pitch.", USD),
    ("Employer statutory + benefits load (India)", 0.15, "EPF/ESI/gratuity + benefits on top of base salary.", PCT),
    ("Contingency buffer (% of recurring burn)", 0.30, "Applied on top of recurring burn to absorb overruns / unknowns.", PCT),
    ("Target runway (months)", 40, "Investor floor. Base scenario must clear this.", '0'),
]
FX_ROW = r; RAISE_ROW = r + 1; LOAD_ROW = r + 2; BUFFER_ROW = r + 3
for i, (name, val, n, fmt) in enumerate(ASSUMP):
    rr = r + i
    asm.cell(row=rr, column=1, value=name).font = BODY
    c = asm.cell(row=rr, column=2, value=val); c.font = BOLD; c.alignment = RIGHT
    if fmt: c.number_format = fmt
    elif name.startswith("USD:INR"): c.number_format = '0'
    asm.cell(row=rr, column=3, value=n).font = SMALL
    asm.cell(row=rr, column=3).alignment = WRAP
    for col in (1, 2, 3):
        asm.cell(row=rr, column=col).border = BORDER
        if i % 2: asm.cell(row=rr, column=col).fill = FILL_ZEBRA
FX = f"Assumptions!$B${FX_ROW}"
RAISE = f"Assumptions!$B${RAISE_ROW}"
LOAD = f"Assumptions!$B${LOAD_ROW}"
BUFFER = f"Assumptions!$B${BUFFER_ROW}"

r = r + len(ASSUMP) + 2
r = band(asm, r, "  Methodology")
for line in [
    "• Inputs (salaries, unit costs) are entered as values; subtotals, totals and runway are live formulas.",
    "• Base scenario runs the full team + full GTM for the whole period (conservative — real phased hiring extends runway).",
    "• Every external unit cost is sourced on the Sources tab with a URL and access date (research 2026-07-23).",
    "• India comp shown in INR and USD; US roles (enterprise seller) priced in USD (cannot be India-priced).",
    "• Runway (months) = (Raise − one-time costs) ÷ annual recurring burn × 12.",
]:
    asm.cell(row=r, column=1, value=line).font = BODY
    asm.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    asm.cell(row=r, column=1).alignment = WRAP
    r += 1

# =====================================================================
# 2. TEAM & COMPENSATION
# =====================================================================
tm = sheet("Team & Compensation")
widths = [30, 12, 26, 16, 15, 12, 16, 40]
tm["A1"] = "Team & Compensation"; tm["A1"].font = H1
tm["A2"] = "All payroll (India build team incl. security CTO + US enterprise seller). Base salary; employer load added below."
tm["A2"].font = SMALL
r = 4
r = hdr(tm, r, ["Role", "Location", "Function", "Base salary (INR/yr)",
                "Base salary (USD/yr)", "Headcount", "Annual base (USD)", "Notes"], widths)
TEAM_FIRST = r
# (role, location, function, base_inr or None, base_usd_direct or None, headcount, note)
TEAM = [
    ("Founder / CEO", "India", "Leadership", 8500000, None, 1, "Base only; equity-heavy."),
    ("Security CTO", "India", "Leadership / Security", 8500000, None, 1, "Same base as CEO for now (cash conservation); equity-weighted. Bank-facing credibility hire."),
    ("Sr Engineer (SDE3)", "India", "Backend + Security", 8000000, None, 1, "Detection pipeline, policy engine, in-VPC."),
    ("ML Engineer", "India", "ML / Detection", 6000000, None, 1, "Distilled classifier, shadow→enforce."),
    ("Engineer (SDE2)", "India", "Backend", 5000000, None, 1, "Control-plane / connectors."),
    ("Engineer (SDE2)", "India", "Frontend", 5000000, None, 1, "Console / dashboard (React)."),
    ("Engineer (SDE2)", "India", "Platform / Full-stack", 5000000, None, 1, "SDK, infra, CDK."),
    ("Product Manager", "India", "Product", 7000000, None, 1, "Roadmap, design-partner delivery."),
    ("Enterprise Account Executive (AE)", "US", "Go-to-market", None, 300000, 1, "Fully-loaded on-target (base ~$140K / OTE ~$275K + ~15% burden). Hire ~mo 12–18; budgeted full for conservatism. [GTM]"),
]
for i, (role, loc, func, inr, usd, hc, note) in enumerate(TEAM):
    rr = r + i
    tm.cell(row=rr, column=1, value=role).font = BODY
    tm.cell(row=rr, column=2, value=loc).font = BODY
    tm.cell(row=rr, column=3, value=func).font = BODY
    if inr is not None:
        c = tm.cell(row=rr, column=4, value=inr); c.number_format = INR; c.alignment = RIGHT
        tm.cell(row=rr, column=5, value=f"=D{rr}/{FX}").number_format = USD
    else:
        tm.cell(row=rr, column=4, value="—").alignment = CENTER
        c = tm.cell(row=rr, column=5, value=usd); c.number_format = USD
    tm.cell(row=rr, column=5).alignment = RIGHT
    tm.cell(row=rr, column=6, value=hc).alignment = CENTER; tm.cell(row=rr, column=6).font = BODY
    tm.cell(row=rr, column=7, value=f"=E{rr}*F{rr}").number_format = USD
    tm.cell(row=rr, column=7).alignment = RIGHT
    tm.cell(row=rr, column=8, value=note).font = SMALL
    tm.cell(row=rr, column=8).alignment = WRAP
    for col in range(1, 9):
        tm.cell(row=rr, column=col).border = BORDER
        if i % 2: tm.cell(row=rr, column=col).fill = FILL_ZEBRA
TEAM_LAST = r + len(TEAM) - 1

# India-only subtotal (rows where location=India) — AE is US, handled separately.
INDIA_FIRST = TEAM_FIRST; INDIA_LAST = TEAM_LAST - 1  # last row is US AE
AE_ROW = TEAM_LAST

rr = TEAM_LAST + 1
tm.cell(row=rr, column=1, value="India base payroll (sum)").font = BOLD
tm.cell(row=rr, column=6, value=f"=SUM(F{INDIA_FIRST}:F{INDIA_LAST})").alignment = CENTER
tm.cell(row=rr, column=6).font = BOLD
c = tm.cell(row=rr, column=7, value=f"=SUM(G{INDIA_FIRST}:G{INDIA_LAST})"); c.number_format = USD; c.font = BOLD; c.alignment = RIGHT
INDIA_BASE_ROW = rr

rr += 1
tm.cell(row=rr, column=1, value="India employer load (statutory + benefits)").font = BODY
tm.cell(row=rr, column=7, value=f"=G{INDIA_BASE_ROW}*{LOAD}").number_format = USD
tm.cell(row=rr, column=7).alignment = RIGHT; tm.cell(row=rr, column=8, value="=15% of India base").font = SMALL
INDIA_LOAD_ROW = rr

rr += 1
tm.cell(row=rr, column=1, value="BASE PAYROLL — India team, loaded (flows to runway)").font = TOTAL_FONT
c = tm.cell(row=rr, column=7, value=f"=G{INDIA_BASE_ROW}+G{INDIA_LOAD_ROW}")
c.number_format = USD; c.font = TOTAL_FONT; c.alignment = RIGHT
for col in range(1, 9):
    tm.cell(row=rr, column=col).fill = FILL_TOTAL
TOTAL_PAYROLL_ROW = rr  # base payroll = India only (AE deferred)

rr += 1
tm.cell(row=rr, column=1, value="US seller (enterprise AE, loaded) — DEFERRED").font = BODY
tm.cell(row=rr, column=1).font = Font(name="Calibri", size=10, italic=True, color=GREY)
c = tm.cell(row=rr, column=7, value=f"=G{AE_ROW}"); c.number_format = USD; c.alignment = RIGHT
tm.cell(row=rr, column=8, value="Founder-led sales first ~12–18mo; hired later → added in the High scenario. NOT in base burn.").font = SMALL
tm.cell(row=rr, column=8).alignment = WRAP
US_AE_ROW = rr

# total headcount cell used by Overview
rr += 1
tm.cell(row=rr, column=1, value="Total headcount (incl. deferred AE when hired)").font = BOLD
c = tm.cell(row=rr, column=6, value=f"=SUM(F{TEAM_FIRST}:F{TEAM_LAST})"); c.font = BOLD; c.alignment = CENTER
HEADCOUNT_ROW = rr

# split refs for use-of-funds
INDIA_LOADED_FORMULA = f"('Team & Compensation'!G{INDIA_BASE_ROW}+'Team & Compensation'!G{INDIA_LOAD_ROW})"
US_AE_FORMULA = f"'Team & Compensation'!G{US_AE_ROW}"
TOTAL_PAYROLL_FORMULA = f"'Team & Compensation'!G{TOTAL_PAYROLL_ROW}"  # India-only base

# =====================================================================
# 3. OPERATING COSTS  (the 7 buckets)
# =====================================================================
oc = sheet("Operating Costs")
widths = [40, 15, 15, 12, 42]
oc["A1"] = "Operating Costs — annual, by bucket"; oc["A1"].font = H1
oc["A2"] = "Recurring unless marked one-time. Sourced unit costs → see Sources tab. Payroll lives on the Team tab."
oc["A2"].font = SMALL

# We'll lay out each bucket with its line items and a subtotal row, capturing subtotal rows for the Runway sheet.
r = 4
bucket_subtotals = {}   # name -> (annual_cell, monthly_expr)
onetime_cells = []

def bucket(ws, start_row, name, rows):
    """rows: list of (item, annual_value_or_formula, is_onetime, note). Returns next_row, subtotal_row."""
    r = start_row
    r = band(ws, r, "  " + name, span=5)
    r = hdr(ws, r, ["Line item", "Annual (USD)", "Monthly (USD)", "Type", "Basis / note"],
            [40, 15, 15, 12, 42] if start_row == 4 else None)
    first = r
    for i, (item, val, onetime, note) in enumerate(rows):
        ws.cell(row=r, column=1, value=item).font = BODY
        c = ws.cell(row=r, column=2, value=val); c.number_format = USD; c.alignment = RIGHT
        # monthly = annual/12 for recurring, blank for one-time
        if onetime:
            ws.cell(row=r, column=3, value="—").alignment = CENTER
            ws.cell(row=r, column=4, value="one-time").font = SMALL; ws.cell(row=r, column=4).alignment = CENTER
            onetime_cells.append(f"'Operating Costs'!B{r}")
        else:
            ws.cell(row=r, column=3, value=f"=B{r}/12").number_format = USD; ws.cell(row=r, column=3).alignment = RIGHT
            ws.cell(row=r, column=4, value="recurring").font = SMALL; ws.cell(row=r, column=4).alignment = CENTER
        ws.cell(row=r, column=5, value=note).font = SMALL; ws.cell(row=r, column=5).alignment = WRAP
        for col in range(1, 6):
            ws.cell(row=r, column=col).border = BORDER
            if i % 2: ws.cell(row=r, column=col).fill = FILL_ZEBRA
        r += 1
    last = r - 1
    # subtotal (recurring only)
    ws.cell(row=r, column=1, value=f"{name} — recurring subtotal").font = BOLD
    # sum only recurring rows: sum col B where type recurring; simpler: sum all minus one-times.
    # We build an explicit SUMIF on the Type column (col D) = "recurring".
    c = ws.cell(row=r, column=2, value=f'=SUMIF(D{first}:D{last},"recurring",B{first}:B{last})')
    c.number_format = USD; c.font = BOLD; c.alignment = RIGHT
    ws.cell(row=r, column=3, value=f"=B{r}/12").number_format = USD; ws.cell(row=r, column=3).font = BOLD; ws.cell(row=r, column=3).alignment = RIGHT
    for col in range(1, 6):
        ws.cell(row=r, column=col).fill = FILL_GREEN
    subtotal_row = r
    return r + 2, subtotal_row

def usdf(v):  # helper: pass literal
    return v

# --- Bucket 1: Team & Compensation (reference the Team tab total) ---
r = band(oc, r, "  1 · Team & Compensation (payroll — from Team tab)", span=5)
r = hdr(oc, r, ["Line item", "Annual (USD)", "Monthly (USD)", "Type", "Basis / note"], widths)
oc.cell(row=r, column=1, value="Total loaded payroll (India team + US seller)").font = BODY
c = oc.cell(row=r, column=2, value=f"={TOTAL_PAYROLL_FORMULA}"); c.number_format = USD; c.alignment = RIGHT
oc.cell(row=r, column=3, value=f"=B{r}/12").number_format = USD; oc.cell(row=r, column=3).alignment = RIGHT
oc.cell(row=r, column=4, value="recurring").font = SMALL; oc.cell(row=r, column=4).alignment = CENTER
oc.cell(row=r, column=5, value="See Team & Compensation tab for per-role salaries incl. security CTO.").font = SMALL
oc.cell(row=r, column=5).alignment = WRAP
for col in range(1, 6): oc.cell(row=r, column=col).border = BORDER
TEAM_SUBTOTAL_ROW = r
r += 2

# --- Bucket 2: Physical infra & facilities ---
r, sub = bucket(oc, r, "2 · Physical Infrastructure & Facilities", [
    ("Office rent — Bangalore", 33333, False, "₹2.5L/mo × 12 (base sheet)."),
    ("Laptops — MacBook Pro × 10", 27800, True, "₹25L one-time; refresh on 3-yr cycle."),
    ("Mac Studio × 1 (ML/dev)", 4400, True, "₹4L one-time."),
    ("Office deposit + setup", 11100, True, "₹10L one-time, refundable deposit + fit-out."),
])
bucket_subtotals["Physical infra & facilities"] = sub

# --- Bucket 3: AI coding tools (Claude Code) ---
r, sub = bucket(oc, r, "3 · AI Coding Tools (Claude Code)", [
    ("Claude Code — Team plan (8 × $150/seat)", 14400, False, "8 seats × $150/seat/mo × 12. Anthropic Team plan (premium seat, annual): Claude Code + org SSO / central billing / admin; cheaper than 8 individual Max subscriptions. Source: claude.com/pricing."),
])
bucket_subtotals["Claude Code"] = sub

# --- Bucket 4: Cloud / AWS ---
r, sub = bucket(oc, r, "4 · Cloud / AWS Infrastructure", [
    ("Bedrock foundation-model inference (Haiku/Sonnet)", 30000, False, "~$2.5K/mo; dominant lever. Declines as distilled sidecar absorbs ALLOWs. (Real run-rate.)"),
    ("Distilled classifier serving — CPU Fargate (HA)", 1740, False, "~$145/mo; 5× cheaper than always-on GPU. In-VPC self-host path."),
    ("GPU retraining (periodic, amortized)", 1440, False, "~$120/mo amortized; rent g5/p4 for distillation runs only."),
    ("ECS platform + DynamoDB + S3 + CloudWatch + API GW + ALB + NAT", 14520, False, "~$1,210/mo core production platform (real run-rate)."),
    ("Legacy tail (OpenSearch/SageMaker/EC2), decaying → $0", 18000, False, "~$1.5K/mo winding down; not part of clean target."),
])
bucket_subtotals["Cloud / AWS"] = sub

# --- Bucket 5: GTM programs (non-payroll; AE payroll is in Team) ---
r, sub = bucket(oc, r, "5 · GTM Programs (non-payroll)", [
    ("Events & conferences (RSA + meetups)", 42000, False, "Booth/passes; excludes BLR→US travel (below). Get RSAC prospectus quote."),
    ("Founder US travel (sell-in-US)", 26400, False, "5–6 trips/yr SF/NYC; GSA per-diem basis."),
    ("Content / website / demand-gen", 18000, False, "Seed-stage light demand-gen."),
    ("CRM + sales tooling (HubSpot etc.)", 8400, False, "~$700/mo."),
    ("HubSpot Pro onboarding", 1500, True, "One-time."),
    ("Design-partner program (mostly non-cash)", 6000, False, "Credits/support for observe-only partners."),
])
bucket_subtotals["GTM programs"] = sub

# --- Bucket 6: Operations & G&A ---
r, sub = bucket(oc, r, "6 · Operations & G&A (US C-corp + India Pvt Ltd)", [
    ("Legal counsel — ongoing (MSAs/DPAs/IP)", 36000, False, "~$3K/mo; bank MSA/DPA load."),
    ("Accounting / bookkeeping (US + India)", 10200, False, "~$850/mo (Kruze)."),
    ("Payroll processing + tax filings (US+India)", 4200, False, "~$350/mo amortized."),
    ("Insurance — D&O", 4800, False, "<$10M funding band."),
    ("Insurance — Tech E&O + Cyber + GL", 5200, False, "Security vendor; banks demand $2–5M limits."),
    ("Business SaaS stack (~$60/head × 9)", 6480, False, "Google WS, Slack, Notion, GitHub, 1Password, Zoom."),
    ("US C-corp + India Pvt Ltd ongoing compliance", 2400, False, "DE franchise/agent + India ROC/MCA/statutory audit."),
    ("Banking / cross-border FX fees", 2400, False, "~$200/mo (Wise/wires)."),
    ("Entity formation (US C-corp + India)", 500, True, "One-time."),
    ("Seed-financing legal + first patent", 27000, True, "One-time: round docs ~$20–40K + patent ~$10–15K."),
])
bucket_subtotals["Operations & G&A"] = sub

# --- Bucket 7: Compliance & certifications ---
r, sub = bucket(oc, r, "7 · Compliance & Certifications", [
    ("SOC 2 automation platform (Vanta/Drata)", 12000, False, "~$1K/mo."),
    ("SOC 2 Type II auditor (annual)", 18000, False, "Recurring annual audit."),
    ("Third-party pen test (annual)", 12000, False, "Banks demand current annual report."),
    ("SOC 2 Type I auditor (interim)", 10000, True, "One-time Yr-1 interim to unblock early deals."),
    ("SOC 2 readiness / gap + policy dev", 8000, True, "One-time Yr-1."),
    ("GDPR — fractional DPO + tooling (conditional on EU data)", 32400, False, "~$2.7K/mo; gate until EU customers exist."),
])
bucket_subtotals["Compliance"] = sub

# =====================================================================
# 4. RUNWAY & SCENARIOS
# =====================================================================
rw = sheet("Runway & Scenarios")
for i, w in enumerate([34, 4, 18, 18, 4, 18, 18], start=1):
    rw.column_dimensions[get_column_letter(i)].width = w
rw["A1"] = "Runway & Scenarios"; rw["A1"].font = H1

rw["A3"] = "Inputs"; rw["A3"].font = BOLD
rw["A4"] = "Total raise (USD)"; rw["A4"].font = BODY
c = rw["C4"]; c.value = f"={RAISE}"; c.number_format = USD; c.font = BOLD; c.alignment = RIGHT

# --- recurring buckets table ---
r = 7
r = band(rw, r, "  RECURRING BURN — by bucket (Base scenario)", span=7)
rw.cell(row=r, column=1, value="Bucket").font = HDR; rw.cell(row=r, column=1).fill = FILL_HDR; rw.cell(row=r, column=1).border = BORDER
rw.cell(row=r, column=6, value="Annual (USD)").font = HDR; rw.cell(row=r, column=6).fill = FILL_HDR; rw.cell(row=r, column=6).border = BORDER
rw.cell(row=r, column=7, value="Monthly (USD)").font = HDR; rw.cell(row=r, column=7).fill = FILL_HDR; rw.cell(row=r, column=7).border = BORDER
r += 1
recurring_rows = []
buckets_for_runway = [
    ("1 · Team & compensation (loaded payroll)", f"'Operating Costs'!B{TEAM_SUBTOTAL_ROW}"),
    ("2 · Physical infra & facilities", f"'Operating Costs'!B{bucket_subtotals['Physical infra & facilities']}"),
    ("3 · AI coding tools (Claude Code)", f"'Operating Costs'!B{bucket_subtotals['Claude Code']}"),
    ("4 · Cloud / AWS", f"'Operating Costs'!B{bucket_subtotals['Cloud / AWS']}"),
    ("5 · GTM programs (non-payroll)", f"'Operating Costs'!B{bucket_subtotals['GTM programs']}"),
    ("6 · Operations & G&A", f"'Operating Costs'!B{bucket_subtotals['Operations & G&A']}"),
    ("7 · Compliance & certifications", f"'Operating Costs'!B{bucket_subtotals['Compliance']}"),
]
for i, (name, ref) in enumerate(buckets_for_runway):
    rw.cell(row=r, column=1, value=name).font = BODY
    c = rw.cell(row=r, column=6, value=f"={ref}"); c.number_format = USD; c.alignment = RIGHT
    rw.cell(row=r, column=7, value=f"=F{r}/12").number_format = USD; rw.cell(row=r, column=7).alignment = RIGHT
    for col in [1, 6, 7]:
        rw.cell(row=r, column=col).border = BORDER
        if i % 2: rw.cell(row=r, column=col).fill = FILL_ZEBRA
    recurring_rows.append(r)
    r += 1
REC_FIRST, REC_LAST = recurring_rows[0], recurring_rows[-1]
# subtotal of the 7 buckets (before buffer)
rw.cell(row=r, column=1, value="Subtotal — buckets 1–7").font = BOLD
c = rw.cell(row=r, column=6, value=f"=SUM(F{REC_FIRST}:F{REC_LAST})"); c.number_format = USD; c.font = BOLD; c.alignment = RIGHT
c = rw.cell(row=r, column=7, value=f"=F{r}/12"); c.number_format = USD; c.font = BOLD; c.alignment = RIGHT
for col in [1, 6, 7]: rw.cell(row=r, column=col).fill = FILL_GREEN
SUBTOTAL_REC_ROW = r
r += 1
# contingency buffer (30% of the bucket subtotal)
rw.cell(row=r, column=1, value="Contingency buffer").font = BODY
rw.cell(row=r, column=1).font = Font(name="Calibri", size=10, italic=True, color="8A5A00")
c = rw.cell(row=r, column=6, value=f"=F{SUBTOTAL_REC_ROW}*{BUFFER}"); c.number_format = USD; c.alignment = RIGHT
c = rw.cell(row=r, column=7, value=f"=F{r}/12"); c.number_format = USD; c.alignment = RIGHT
rw.cell(row=r, column=1, value=f"Contingency buffer (× Assumptions buffer %)")
rw.cell(row=r, column=1).font = BODY
for col in [1, 6, 7]: rw.cell(row=r, column=col).fill = FILL_AMBER
BUFFER_LINE_ROW = r
r += 1
# total recurring row (incl. buffer)
rw.cell(row=r, column=1, value="TOTAL RECURRING BURN (incl. buffer)").font = TOTAL_FONT
c = rw.cell(row=r, column=6, value=f"=F{SUBTOTAL_REC_ROW}+F{BUFFER_LINE_ROW}"); c.number_format = USD; c.font = TOTAL_FONT; c.alignment = RIGHT
c = rw.cell(row=r, column=7, value=f"=F{r}/12"); c.number_format = USD; c.font = TOTAL_FONT; c.alignment = RIGHT
for col in range(1, 8): rw.cell(row=r, column=col).fill = FILL_TOTAL
TOTAL_REC_ROW = r

# --- one-time costs ---
r += 2
r = band(rw, r, "  ONE-TIME COSTS", span=7)
onetime_sum = "+".join(onetime_cells)
rw.cell(row=r, column=1, value="Total one-time (laptops, deposits, SOC2 T1, seed legal + patent, formation, onboarding)").font = BODY
rw.cell(row=r, column=1).alignment = WRAP
c = rw.cell(row=r, column=3, value=f"={onetime_sum}"); c.number_format = USD; c.font = BOLD; c.alignment = RIGHT
ONETIME_ROW = r  # expected 22

# --- runway calc + scenarios ---
r += 2
r = band(rw, r, "  RUNWAY", span=7)
rw.cell(row=r, column=1, value="Scenario").font = HDR;
rw.cell(row=r, column=3, value="Annual burn").font = HDR
rw.cell(row=r, column=4, value="Runway (months)").font = HDR
rw.cell(row=r, column=6, value="Note").font = HDR
for col in [1,3,4,6]:
    rw.cell(row=r, column=col).fill = FILL_HDR; rw.cell(row=r, column=col).border = BORDER
# Phased hiring (recommended): start 6 India heads for LEAN_MONTHS, then full team; AE deferred further.
# start-team delta = 3rd SDE2 + PM payroll (loaded) + 2 Claude seats (×3 PAYG), all ×(1+buffer).
LEAN_MONTHS = 9
rw.cell(row=r, column=1, value="Phased hiring (recommended): 6 heads → full team ~mo %d" % LEAN_MONTHS).font = BOLD
# start recurring = full total − (SDE2 + PM loaded)*(1+buf) − (2 Team seats*$150*12)*(1+buf)
start_delta = f"(('Team & Compensation'!E9+'Team & Compensation'!E12)*(1+{LOAD})+2*150*12)*(1+{BUFFER})"
rw.cell(row=r, column=3, value=f"=F{TOTAL_REC_ROW}-{start_delta}").number_format = USD; rw.cell(row=r, column=3).alignment = RIGHT
# phased runway = LEAN_MONTHS + (cash - start_burn*LEAN_MONTHS)/full_burn_mo
rw.cell(row=r, column=4, value=(
    f"={LEAN_MONTHS}+((C4-C{ONETIME_ROW})-C{r}/12*{LEAN_MONTHS})/(F{TOTAL_REC_ROW}/12)"
)).number_format = NUM1
rw.cell(row=r, column=4).font = BOLD; rw.cell(row=r, column=4).alignment = RIGHT
rw.cell(row=r, column=6, value="Start: CEO+CTO+SDE3+2×SDE2+ML. Add 3rd SDE2 + PM ~mo %d; US AE ~mo 12–18. C-col = starting annual burn." % LEAN_MONTHS).font = SMALL
rw.cell(row=r, column=6).alignment = WRAP
for col in [1,3,4]:
    rw.cell(row=r, column=col).fill = FILL_GREEN
PHASED_ROW = r
r += 1
BASE_RUNWAY_ROW = r
# Base — full India team day 1 + full GTM programs + buffer; US AE DEFERRED (founder-led sales)
rw.cell(row=r, column=1, value="Base (full India team day 1, founder-led sales)").font = BOLD
c = rw.cell(row=r, column=3, value=f"=F{TOTAL_REC_ROW}"); c.number_format = USD; c.alignment = RIGHT
c = rw.cell(row=r, column=4, value=f"=(C4-C{ONETIME_ROW})/F{TOTAL_REC_ROW}*12"); c.number_format = NUM1; c.font = BOLD; c.alignment = RIGHT
rw.cell(row=r, column=6, value="All 8 India hires from day one; US AE deferred. Must clear the 40-mo floor.").font = SMALL
rw.cell(row=r, column=6).alignment = WRAP
for col in [1,3,4]:
    rw.cell(row=r, column=col).fill = FILL_ZEBRA
r += 1
# + US AE hired
rw.cell(row=r, column=1, value="+ US enterprise AE hired (full year)").font = BODY
rw.cell(row=r, column=3, value=f"=F{TOTAL_REC_ROW}+{US_AE_FORMULA}*(1+{BUFFER})").number_format = USD; rw.cell(row=r, column=3).alignment = RIGHT
rw.cell(row=r, column=4, value=f"=(C4-C{ONETIME_ROW})/C{r}*12").number_format = NUM1; rw.cell(row=r, column=4).alignment = RIGHT
rw.cell(row=r, column=6, value="Full US seller from day one (+30% buffer on it too). Shows AE cost impact.").font = SMALL
rw.cell(row=r, column=6).alignment = WRAP
AE_SCENARIO_ROW = r
r += 1
# Lean
rw.cell(row=r, column=1, value="Lean (founder-led, trim cloud & GTM to low case)").font = BODY
rw.cell(row=r, column=3, value=f"=F{TOTAL_REC_ROW}-40000-24000").number_format = USD; rw.cell(row=r, column=3).alignment = RIGHT
rw.cell(row=r, column=4, value=f"=(C4-C{ONETIME_ROW})/C{r}*12").number_format = NUM1; rw.cell(row=r, column=4).alignment = RIGHT
rw.cell(row=r, column=6, value="Trim AWS legacy tail + GTM events to stretch runway further.").font = SMALL
rw.cell(row=r, column=6).alignment = WRAP
r += 1
# High
rw.cell(row=r, column=1, value="High (US AE + fractional VP + GDPR + high cloud)").font = BODY
rw.cell(row=r, column=3, value=f"=F{TOTAL_REC_ROW}+({US_AE_FORMULA}+120000)*(1+{BUFFER})").number_format = USD; rw.cell(row=r, column=3).alignment = RIGHT
rw.cell(row=r, column=4, value=f"=(C4-C{ONETIME_ROW})/C{r}*12").number_format = NUM1; rw.cell(row=r, column=4).alignment = RIGHT
rw.cell(row=r, column=6, value="Aggressive scale — pace these hires against actual traction.").font = SMALL
rw.cell(row=r, column=6).alignment = WRAP
r += 2
tgt = rw.cell(row=r, column=1, value=f"Target floor: ≥ 40 months (Assumptions). Base scenario must clear it — see cell D{BASE_RUNWAY_ROW}.")
tgt.font = Font(name="Calibri", size=9, bold=True, color="1559C9")
rw.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)

# fill Overview headline formulas now that all rows are resolved
head_formulas = [
    "='Runway & Scenarios'!C4",                              # Total raise
    f"='Runway & Scenarios'!C{ONETIME_ROW}",                 # One-time costs
    f"='Runway & Scenarios'!F{TOTAL_REC_ROW}",               # Recurring burn / year
    f"='Runway & Scenarios'!G{TOTAL_REC_ROW}",               # Recurring burn / month
    f"='Runway & Scenarios'!D{BASE_RUNWAY_ROW}",             # Base runway months
    f"='Team & Compensation'!F{HEADCOUNT_ROW}",              # Total headcount
]
for i, f in enumerate(head_formulas):
    ov.cell(row=HEAD_ROW_START + i, column=2, value=f)

# =====================================================================
# 5. USE OF FUNDS RECONCILIATION
# =====================================================================
uf = sheet("Use of Funds")
for i, w in enumerate([42, 18, 18, 16, 40], start=1):
    uf.column_dimensions[get_column_letter(i)].width = w
uf["A1"] = "Use of Funds — model vs. pitch"; uf["A1"].font = H1
uf["A2"] = ("Share of the $5M raise over the base runway (US enterprise AE deferred, so it is NOT in the base "
            "buckets below — it is added in the '+ US AE' scenario). Contingency buffer shown as its own line, "
            "not folded into any bucket.")
uf["A2"].font = SMALL; uf.merge_cells("A2:E2"); uf["A2"].alignment = WRAP
r = 4
r = hdr(uf, r, ["Bucket", "Annual (USD)", "Over runway (USD)", "% of $5M", "Comment"], [42,18,18,16,40])
UF_FIRST = r
# months for allocation = base runway
months_ref = f"'Runway & Scenarios'!D{BASE_RUNWAY_ROW}"
# base recurring subtotal (buckets, pre-buffer) and buffer, from the Runway sheet
SUBTOTAL_REF = f"'Runway & Scenarios'!F{SUBTOTAL_REC_ROW}"
BUFFER_REF = f"'Runway & Scenarios'!F{BUFFER_LINE_ROW}"
uf_rows = [
    ("Team — eng + product + leadership (India, loaded)", INDIA_LOADED_FORMULA, "Core build team incl. security CTO. Excludes deferred US AE."),
    ("GTM — programs only, founder-led sales (AE deferred)", f"'Operating Costs'!B{bucket_subtotals['GTM programs']}", "Events/travel/content/CRM only. Excludes the US enterprise AE salary — see memo row below for the with-AE figure."),
    ("Cloud / AWS + AI coding tools", f"('Operating Costs'!B{bucket_subtotals['Cloud / AWS']}+'Operating Costs'!B{bucket_subtotals['Claude Code']})", "Real infra is ~10% — NOT the ~20% generic AI templates assume (CPU self-host, no GPU)."),
    ("Physical infra & facilities", f"'Operating Costs'!B{bucket_subtotals['Physical infra & facilities']}", "Office + hardware."),
    ("Operations & G&A", f"'Operating Costs'!B{bucket_subtotals['Operations & G&A']}", "Legal, accounting, insurance, entities."),
    ("Compliance & certifications", f"'Operating Costs'!B{bucket_subtotals['Compliance']}", "SOC 2 + pentest + GDPR (conditional) — heavy for seed, justified by bank buyers."),
    ("Contingency buffer (30% of recurring)", BUFFER_REF, "Held as reserve; not allocated to a bucket. Matches the buffer in the runway calc."),
]
for i, (name, annual_expr, comment) in enumerate(uf_rows):
    rr = r + i
    uf.cell(row=rr, column=1, value=name).font = BODY
    c = uf.cell(row=rr, column=2, value=f"={annual_expr}"); c.number_format = USD; c.alignment = RIGHT
    c = uf.cell(row=rr, column=3, value=f"=B{rr}*{months_ref}/12"); c.number_format = USD; c.alignment = RIGHT
    c = uf.cell(row=rr, column=4, value=f"=C{rr}/{RAISE}"); c.number_format = PCT; c.alignment = RIGHT
    uf.cell(row=rr, column=5, value=comment).font = SMALL; uf.cell(row=rr, column=5).alignment = WRAP
    for col in range(1, 6):
        uf.cell(row=rr, column=col).border = BORDER
        if i % 2: uf.cell(row=rr, column=col).fill = FILL_ZEBRA
UF_LAST = r + len(uf_rows) - 1
rr = UF_LAST + 1
uf.cell(row=rr, column=1, value="TOTAL (≈ full raise over runway)").font = TOTAL_FONT
c = uf.cell(row=rr, column=3, value=f"=SUM(C{UF_FIRST}:C{UF_LAST})"); c.number_format = USD; c.font = TOTAL_FONT; c.alignment = RIGHT
c = uf.cell(row=rr, column=4, value=f"=SUM(D{UF_FIRST}:D{UF_LAST})"); c.number_format = PCT; c.font = TOTAL_FONT; c.alignment = RIGHT
for col in range(1, 6): uf.cell(row=rr, column=col).fill = FILL_TOTAL

# Memo row (not summed into Total): what GTM looks like once the deferred AE is actually hired.
rr += 1
gtm_incl_ae_annual = f"'Operating Costs'!B{bucket_subtotals['GTM programs']}+{US_AE_FORMULA}*(1+{BUFFER})"
runway_with_ae = f"'Runway & Scenarios'!D{AE_SCENARIO_ROW}"
uf.cell(row=rr, column=1, value="Memo: GTM incl. full-year AE hire (not in Total above)").font = SMALL
c = uf.cell(row=rr, column=2, value=f"={gtm_incl_ae_annual}"); c.number_format = USD; c.font = SMALL; c.alignment = RIGHT
c = uf.cell(row=rr, column=3, value=f"=B{rr}*{runway_with_ae}/12"); c.number_format = USD; c.font = SMALL; c.alignment = RIGHT
c = uf.cell(row=rr, column=4, value=f"=C{rr}/{RAISE}"); c.number_format = PCT; c.font = SMALL; c.alignment = RIGHT
uf.cell(row=rr, column=5, value="Programs + AE (loaded, buffered), pro-rated over the shorter 33-mo runway once the AE is on. See '+ US AE' scenario.").font = SMALL
uf.cell(row=rr, column=5).alignment = WRAP
for col in range(1, 6):
    uf.cell(row=rr, column=col).border = BORDER

# =====================================================================
# 6. SOURCES
# =====================================================================
sc = sheet("Sources")
for i, w in enumerate([34, 30, 62, 16], start=1):
    sc.column_dimensions[get_column_letter(i)].width = w
sc["A1"] = "Sources & Citations"; sc["A1"].font = H1
sc["A2"] = "Every external unit cost traces to a source. Accessed 2026-07-23. Ranges (low/base/high) and full notes are in the research packet."
sc["A2"].font = SMALL; sc.merge_cells("A2:D2"); sc["A2"].alignment = WRAP
r = 4
r = hdr(sc, r, ["Bucket", "Figure", "Source", "URL"], [34, 30, 40, 16])
SOURCES = [
    ("Claude Code", "Max 20x $200 / Max 5x $100; blend $150/seat", "Anthropic pricing", "https://claude.com/pricing"),
    ("Claude Code", "PAYG ~$13/dev/active-day; $150–250/dev/mo", "Anthropic Claude Code cost docs", "https://code.claude.com/docs/en/costs"),
    ("AWS — Bedrock", "Haiku $1/$5, Sonnet $3/$15 per MTok; ~$2.5K/mo", "Anthropic/Bedrock pricing", "https://platform.claude.com/docs/en/about-claude/pricing"),
    ("AWS — Fargate", "CPU serving ~$145/mo; $0.04048/vCPU-hr", "AWS Fargate pricing", "https://aws.amazon.com/fargate/pricing/"),
    ("AWS — GPU", "g5.xlarge $1.006/hr; retraining amortized ~$120/mo", "Vantage EC2 pricing", "https://instances.vantage.sh/aws/ec2/g5.xlarge"),
    ("AWS — real run-rate", "~$6–14K/mo actual (Apr–Jun 2026), sentra acct", "AWS Cost Explorer (this account)", "acct 531109575379"),
    ("GTM — US AE", "base ~$140K / OTE ~$275K; loaded ~$312K", "RepVue enterprise-AE salaries", "https://www.repvue.com/salaries/enterprise-account-executive"),
    ("GTM — fractional VP/SDR", "loaded ~$10K/mo (corrected from $12K)", "BuiltIn SDR salaries", "https://builtin.com/salaries/us/sales-development-representative"),
    ("GTM — events", "RSA passes/booth; get prospectus quote", "Lensmor RSAC 2026 guide", "https://www.lensmor.com/event-guides/rsa-conference-2026-attendee-guide"),
    ("GTM — travel", "GSA per-diem; SF/NYC lodging", "GSA per-diem", "https://www.gsa.gov/travel/plan-book/per-diem-rates"),
    ("GTM — CRM", "HubSpot Sales Starter/Pro; $1.5K onboarding", "HubSpot pricing", "https://www.hubspot.com/pricing/sales"),
    ("Compliance — SOC 2", "Type I ~$10K, Type II ~$18K/yr, readiness ~$8K", "Drata SOC 2 cost", "https://drata.com/learn/soc-2/cost"),
    ("Compliance — SOC 2 platform", "Vanta/Drata ~$12K/yr", "RiskPublishing SOC 2 breakdown", "https://riskpublishing.com/soc-2-audit-cost-complete-pricing-breakdown/"),
    ("Compliance — GDPR DPO", "fractional DPO ~$2.2K/mo (EUR 2,000+)", "EngageCompliance DPO benchmark", "https://engagecompliance.co/fractional-dpo-pricing-benchmark-2026"),
    ("Ops — legal", "seed ongoing ~$3K/mo; round+patent ~$27K one-time", "Arceus / Kruze startup legal", "https://arceus.legal/blog/how-much-should-legal-cost-startup-by-stage"),
    ("Ops — accounting", "~$850/mo bookkeeping; payroll+tax", "Kruze pricing", "https://kruzeconsulting.com/pricing/"),
    ("Ops — insurance", "D&O $3.5–6K/yr; E&O+cyber+GL", "Embroker D&O cost", "https://www.embroker.com/blog/directors-and-officers-insurance-cost/"),
    ("Ops — India entity", "Pvt Ltd ROC/MCA ₹40K–1.5L/yr", "Incorpx compliance cost", "https://incorpx.io/blog/annual-compliance-cost-startups-2026"),
    ("Ops — US entity", "DE franchise/agent + CA $800", "Delaware Div. of Corporations", "https://corp.delaware.gov/paytaxes/"),
    ("Ops — India EOR (alt)", "$599–699/head (corrected from $500)", "Deel pricing", "https://www.deel.com/pricing/"),
    ("Ops — SaaS stack", "~$60/head (Google WS, Slack, etc.)", "Google Workspace pricing", "https://workspace.google.com/pricing"),
    ("Team — India base salaries", "SDE2 ₹50L, SDE3 ₹80L, ML ₹60L, CEO ₹85L", "Founder base sheet (Compensation-Runway-Model.xlsx)", "internal 2026-02"),
]
for i, (bucket_n, fig, src, url) in enumerate(SOURCES):
    rr = r + i
    sc.cell(row=rr, column=1, value=bucket_n).font = BODY
    sc.cell(row=rr, column=2, value=fig).font = BODY; sc.cell(row=rr, column=2).alignment = WRAP
    sc.cell(row=rr, column=3, value=src).font = BODY; sc.cell(row=rr, column=3).alignment = WRAP
    lc = sc.cell(row=rr, column=4, value=url)
    if url.startswith("http"):
        lc.hyperlink = url; lc.font = LINK
    else:
        lc.font = SMALL
    lc.alignment = WRAP
    for col in range(1, 5):
        sc.cell(row=rr, column=col).border = BORDER
        if i % 2: sc.cell(row=rr, column=col).fill = FILL_ZEBRA

# resolve Overview use-of-funds % cells to the Use of Funds tab rows (col D = % of $5M)
for i in range(6):
    ov.cell(row=UOF_ROW_START + i, column=2, value=f"='Use of Funds'!D{UF_FIRST + i}")

# order sheets
wb.move_sheet("Overview", -wb.sheetnames.index("Overview"))
wb.save(OUT)
print("wrote", OUT)
