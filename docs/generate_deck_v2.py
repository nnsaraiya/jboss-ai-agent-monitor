"""
generate_deck_v2.py — Rebuild jboss-ai-monitor-deck.pptx with 12 slides
using the extracted template design system.
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu

# ── Color palette ──────────────────────────────────────────────────────────────
RED        = RGBColor(0xEE, 0x00, 0x00)
BLUE       = RGBColor(0x3C, 0x8F, 0xF7)
DARK_GRAY  = RGBColor(0x21, 0x21, 0x21)
MID_GRAY   = RGBColor(0x59, 0x59, 0x59)
LIGHT_GRAY = RGBColor(0xEE, 0xEE, 0xEE)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
GREEN      = RGBColor(0x3E, 0x8C, 0x35)
NEAR_BLACK = RGBColor(0x1A, 0x1A, 0x1A)
TICKET_BG  = RGBColor(0x1E, 0x1E, 0x1E)
ALT_GRAY   = RGBColor(0xF5, 0xF5, 0xF5)
LIGHT_RED_TINT = RGBColor(0xFF, 0xF0, 0xF0)
DARK_NEAR  = RGBColor(0x21, 0x21, 0x21)
DDDDDD     = RGBColor(0xDD, 0xDD, 0xDD)


# ── Helper functions ───────────────────────────────────────────────────────────

def add_rect(slide, left, top, width, height, fill_rgb, line_rgb=None):
    shape = slide.shapes.add_shape(1,
        Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_rgb
    if line_rgb:
        shape.line.color.rgb = line_rgb
    else:
        shape.line.fill.background()
    return shape


def add_text_box(slide, text, left, top, width, height,
                 font_size, bold, color_rgb,
                 align=PP_ALIGN.LEFT, wrap=True, italic=False):
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height))
    txBox.text_frame.word_wrap = wrap
    p = txBox.text_frame.paragraphs[0]
    p.alignment = align

    # Handle multi-line strings by splitting on \n
    lines = text.split('\n')
    first_line = lines[0]
    run = p.add_run()
    run.text = first_line
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color_rgb

    for line in lines[1:]:
        p2 = txBox.text_frame.add_paragraph()
        p2.alignment = align
        run2 = p2.add_run()
        run2.text = line
        run2.font.size = Pt(font_size)
        run2.font.bold = bold
        run2.font.italic = italic
        run2.font.color.rgb = color_rgb

    return txBox


def add_bullet_list(slide, items, left, top, width, height,
                    font_size, color_rgb, bullet_char="▶  "):
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        from pptx.util import Pt as _Pt
        p.space_before = _Pt(8)
        run = p.add_run()
        run.text = bullet_char + item
        run.font.size = _Pt(font_size)
        run.font.color.rgb = color_rgb
    return txBox


def red_top_bar(slide):
    """Thin red banner across the very top of the slide."""
    add_rect(slide, 0, 0, 20, 0.5, RED)


def cell(slide, text, x, y, w, h, bg, fg, font_size=22, bold=False,
         align=PP_ALIGN.LEFT, italic=False):
    """Draw a table cell as rect + text box."""
    add_rect(slide, x, y, w, h, bg)
    add_text_box(slide, text, x + 0.1, y + 0.05, w - 0.2, h - 0.1,
                 font_size, bold, fg, align=align, italic=italic)


# ── Presentation setup ─────────────────────────────────────────────────────────

prs = Presentation()
prs.slide_width  = Inches(20)
prs.slide_height = Inches(11.25)
BLANK = prs.slide_layouts[6]


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title (dark background)
# ══════════════════════════════════════════════════════════════════════════════
s1 = prs.slides.add_slide(BLANK)

add_rect(s1, 0, 0, 20, 11.25, NEAR_BLACK)           # dark bg
add_rect(s1, 0, 0, 0.5, 11.25, RED)                 # left red accent bar

add_text_box(s1,
    "Autonomous JBoss Operations\nwith Red Hat OpenShift AI",
    1.2, 2.0, 17, 3.5, 60, True, WHITE)

add_text_box(s1,
    "Reducing MTTR and operational cost with an AI-powered monitoring agent",
    1.2, 5.8, 14, 1.5, 28, False, LIGHT_GRAY)

add_text_box(s1,
    "Red Hat — Confidential",
    14, 10.5, 5.5, 0.5, 16, False, MID_GRAY,
    align=PP_ALIGN.RIGHT)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — The Problem
# ══════════════════════════════════════════════════════════════════════════════
s2 = prs.slides.add_slide(BLANK)

red_top_bar(s2)

add_text_box(s2,
    "The Status Quo: Manual, Reactive, Expensive",
    1.0, 0.7, 18, 2.5, 60, True, RED)

add_rect(s2, 1.0, 3.0, 18, 0.06, RED)   # thin rule

add_bullet_list(s2, [
    "JBoss incidents go undetected until users complain",
    "Senior engineers spend 2+ hours per incident on root cause",
    "JIRA tickets created manually — late, incomplete, inconsistent",
    "On-call rotations are expensive and cause burnout",
    "The same incidents recur — fixes are never documented",
], 1.5, 3.3, 17, 7.0, 28, DARK_GRAY)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — The Solution (4 pillars)
# ══════════════════════════════════════════════════════════════════════════════
s3 = prs.slides.add_slide(BLANK)

red_top_bar(s3)

add_text_box(s3,
    "Detect. Analyse. Document. Automatically.",
    1.0, 0.7, 18, 2.0, 60, True, RED)

pillars = [
    (0.5,  "🔍", "Detect",      "Monitors pod state, logs, alerts and health every 60 seconds"),
    (5.0,  "🧠", "Analyse",     "RHOAI-hosted LLM generates root cause and resolution steps"),
    (9.5,  "🎫", "Document",    "Structured JIRA ticket created automatically with full context"),
    (14.0, "🔕", "Deduplicate", "Suppresses repeat tickets within a configurable time window"),
]

for bx, emoji, title, body in pillars:
    add_rect(s3, bx, 3.2, 4.3, 7.0, LIGHT_GRAY)          # box bg
    add_rect(s3, bx, 3.2, 4.3, 0.15, RED)                 # red top strip
    add_text_box(s3, emoji,  bx + 0.3, 3.6,  3.7, 1.2, 44, False, DARK_GRAY, align=PP_ALIGN.CENTER)
    add_text_box(s3, title,  bx + 0.2, 5.0,  3.9, 0.7, 24, True,  RED,       align=PP_ALIGN.CENTER)
    add_text_box(s3, body,   bx + 0.2, 5.8,  3.9, 4.3, 22, False, DARK_GRAY, wrap=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — Time Savings (table)
# ══════════════════════════════════════════════════════════════════════════════
s4 = prs.slides.add_slide(BLANK)

red_top_bar(s4)

add_text_box(s4,
    "2.5 Hours of Senior Engineer Time → 15 Minutes of Review",
    1.0, 0.7, 18, 1.8, 52, True, RED)

# Header row
hdr_cells = [
    (1.0, 5.0, "Step"),
    (6.2, 4.0, "Before"),
    (10.4, 4.0, "After"),
    (14.6, 4.8, "Time Saved"),
]
for x, w, lbl in hdr_cells:
    cell(s4, lbl, x, 2.8, w, 0.7, RED, WHITE, 22, True, PP_ALIGN.CENTER)

# Data rows
rows = [
    ("Issue detection",       "5–30 min",    "60 seconds",       "~29 min saved"),
    ("Root cause analysis",   "60–120 min",  "AI: 14 seconds",   "~119 min saved"),
    ("JIRA ticket creation",  "10–15 min",   "Automated",        "~13 min saved"),
]
row_bgs = [WHITE, RGBColor(0xF5, 0xF5, 0xF5), WHITE]
for ri, (c1, c2, c3, c4) in enumerate(rows):
    y = 3.6 + ri * 0.9
    bg = row_bgs[ri]
    col_data = [(1.0, 5.0, c1), (6.2, 4.0, c2), (10.4, 4.0, c3), (14.6, 4.8, c4)]
    for x, w, txt in col_data:
        cell(s4, txt, x, y, w, 0.8, bg, DARK_GRAY, 22, False, PP_ALIGN.CENTER)

# Footer row
footer_data = [
    (1.0, 5.0, "TOTAL"),
    (6.2, 4.0, "~2.5 hours"),
    (10.4, 4.0, "~15 min review"),
    (14.6, 4.8, "~2 hours saved"),
]
for x, w, txt in footer_data:
    cell(s4, txt, x, 6.3, w, 0.9, DARK_NEAR, WHITE, 24, True, PP_ALIGN.CENTER)

# Callout
add_rect(s4, 3.0, 7.6, 14, 1.2, BLUE)
add_text_box(s4,
    "At $100/hr blended SRE rate → $225 saved per incident",
    3.0, 7.6, 14, 1.2, 26, True, WHITE, align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — ROI by Size
# ══════════════════════════════════════════════════════════════════════════════
s5 = prs.slides.add_slide(BLANK)

red_top_bar(s5)

add_text_box(s5,
    "The Value Scales With Your Environment",
    1.0, 0.7, 18, 2.0, 60, True, RED)

boxes5 = [
    (0.5,  6.0, LIGHT_GRAY, DARK_GRAY, DARK_GRAY,
     "Small — 1 env · 10 incidents/mo", "$27,000/yr", "annual savings"),
    (7.0,  6.0, DDDDDD,     DARK_GRAY, DARK_GRAY,
     "Medium — 3 envs · 30 incidents/mo", "$81,000/yr", "annual savings"),
    (13.5, 6.0, RED,        WHITE,     WHITE,
     "Large — 10 envs · 100 incidents/mo", "$270,000/yr", "annual savings"),
]

for bx, bw, bg, text_col, label_col, profile, number, label in boxes5:
    add_rect(s5, bx, 3.2, bw, 6.5, bg)
    add_text_box(s5, profile, bx + 0.2, 3.8, bw - 0.4, 1.5, 24, False, text_col, wrap=True)
    add_text_box(s5, number,  bx + 0.2, 5.5, bw - 0.4, 1.5, 48, True,  RED if bg != RED else WHITE, align=PP_ALIGN.CENTER)
    add_text_box(s5, label,   bx + 0.2, 7.2, bw - 0.4, 0.8, 20, False, label_col, align=PP_ALIGN.CENTER)

add_text_box(s5,
    "Conservative estimate — direct engineer time only. Excludes on-call premiums, prevented downtime, and revenue protection.",
    1.0, 10.3, 18, 0.8, 18, False, MID_GRAY, italic=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — On-Call Value
# ══════════════════════════════════════════════════════════════════════════════
s6 = prs.slides.add_slide(BLANK)

red_top_bar(s6)

add_text_box(s6,
    "24/7 Coverage — Without 3am Pages",
    1.0, 0.7, 18, 2.0, 60, True, RED)

add_rect(s6, 1.0, 3.0, 18, 3.5, DARK_NEAR)
add_text_box(s6,
    '"The first P1 incident it catches at 3am on a Sunday — without waking anyone — pays for the entire implementation."',
    1.2, 3.1, 17.6, 3.3, 30, False, WHITE,
    align=PP_ALIGN.CENTER, italic=True)

stat_boxes = [
    (0.5,  "10–25%", "On-call salary premium eliminated"),
    (7.3,  "3am",    "Agent works nights, weekends, holidays"),
    (14.0, "0 min",  "Time to ticket after issue detection"),
]
for bx, big, desc in stat_boxes:
    add_rect(s6, bx, 7.0, 5.5, 3.5, LIGHT_GRAY)
    add_text_box(s6, big,  bx + 0.2, 7.3, 5.1, 1.2, 40, True,  RED,       align=PP_ALIGN.CENTER)
    add_text_box(s6, desc, bx + 0.2, 8.7, 5.1, 1.5, 22, False, DARK_GRAY, align=PP_ALIGN.CENTER, wrap=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — Sample JIRA Ticket
# ══════════════════════════════════════════════════════════════════════════════
s7 = prs.slides.add_slide(BLANK)

red_top_bar(s7)

add_text_box(s7,
    "Every Incident Gets a Structured, Actionable Ticket",
    1.0, 0.7, 14, 2.0, 52, True, RED)

add_rect(s7, 1.0, 3.0, 13.5, 7.8, TICKET_BG)

ticket_text = (
    "\U0001f534  OOMKilled — jboss-instance-0  |  CRITICAL  |  jboss-production\n\n"
    "\U0001f9e0  Root Cause  (AI — Confidence: HIGH)\n"
    "JVM heap exhausted. -Xmx setting too low for workload.\n"
    "Container memory limit: 1536Mi.  Current heap: 256Mi.\n\n"
    "\U0001f527  Resolution Steps\n"
    "  1. Increase -Xmx to 1024m in standalone.xml\n"
    "  2. Set OpenShift memory limit to 1536Mi\n"
    "  3. Enable -XX:+HeapDumpOnOutOfMemoryError\n\n"
    "\U0001f6e1️  Prevention Tips\n"
    "  •  Set JVM heap to 75% of container memory limit\n"
    "  •  Add readiness probe on /health/ready\n\n"
    "\U0001f4da  References\n"
    "  •  Red Hat KBase: Tuning JVM for EAP on OpenShift"
)
add_text_box(s7, ticket_text, 1.5, 3.3, 12.5, 7.2, 20, False, WHITE, wrap=True)

add_rect(s7, 15.0, 4.5, 4.5, 3.0, GREEN)
add_text_box(s7,
    "Created in\n14 seconds\nNo human\ninvolved",
    15.0, 4.5, 4.5, 3.0, 26, True, WHITE, align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — Red Hat Platform
# ══════════════════════════════════════════════════════════════════════════════
s8 = prs.slides.add_slide(BLANK)

red_top_bar(s8)

add_text_box(s8,
    "Runs on Technology You Already Own",
    1.0, 0.7, 18, 2.0, 60, True, RED)

# Left table
table8_hdr = [("Component", 5.0), ("Red Hat Product", 5.5)]
hdr_xs = [1.0, 6.0]
for (lbl, w), x in zip(table8_hdr, hdr_xs):
    cell(s8, lbl, x, 3.0, w, 1.1, RED, WHITE, 22, True, PP_ALIGN.LEFT)

table8_rows = [
    ("JBoss runtime",       "Red Hat JBoss EAP / WildFly Operator"),
    ("Container platform",  "Red Hat OpenShift"),
    ("AI inference",        "Red Hat OpenShift AI (RHOAI)"),
    ("Model serving",       "KServe + vLLM on GPU"),
    ("Container image",     "UBI9 (Universal Base Image)"),
]
row_bgs8 = [WHITE, LIGHT_GRAY, WHITE, LIGHT_GRAY, WHITE]
for ri, (c1, c2) in enumerate(table8_rows):
    y = 4.1 + ri * 1.1
    bg = row_bgs8[ri]
    cell(s8, c1, 1.0, y, 5.0, 1.1, bg, DARK_GRAY, 22)
    cell(s8, c2, 6.0, y, 5.5, 1.1, bg, DARK_GRAY, 22)

# Right callout boxes
right_boxes8 = [
    (3.3,  "✓  Activates your RHOAI investment on Day 1"),
    (5.3,  "✓  No new vendor relationship"),
    (7.3,  "✓  Customer data never leaves the cluster"),
]
for y, txt in right_boxes8:
    add_rect(s8, 12.0, y, 7.5, 1.6, BLUE)
    add_text_box(s8, txt, 12.2, y + 0.2, 7.1, 1.2, 24, False, WHITE)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — Competitive Differentiation
# ══════════════════════════════════════════════════════════════════════════════
s9 = prs.slides.add_slide(BLANK)

red_top_bar(s9)

add_text_box(s9,
    "No Generic APM Tool Does This",
    1.0, 0.7, 18, 2.0, 55, True, RED)

# Header
hdr9 = [
    (0.5,  7.0, "Capability"),
    (7.7,  3.5, "Generic APM"),
    (11.4, 3.5, "Cloud AI Services"),
    (15.1, 4.5, "This Solution"),
]
for x, w, lbl in hdr9:
    bg = RED if lbl == "This Solution" else RED
    cell(s9, lbl, x, 3.0, w, 0.8, RED, WHITE, 22, True, PP_ALIGN.CENTER)

# Data rows
data9 = [
    ("JBoss-specific root cause",                  "✗", "Partial", "✓"),
    ("AI resolution steps",                        "✗", "✗",       "✓"),
    ("On-premises LLM (no data leaves cluster)",   "✗", "✗",       "✓"),
    ("Structured JIRA tickets",                    "✗", "✗",       "✓"),
    ("No per-API-call cost",                       "—", "✗",       "✓"),
    ("OpenShift-native",                           "✗", "✗",       "✓"),
]
for ri, (cap, apm, cloud, sol) in enumerate(data9):
    y = 3.9 + ri * 0.9
    bg = WHITE if ri % 2 == 0 else ALT_GRAY
    # Capability
    cell(s9, cap, 0.5, y, 7.0, 0.9, bg, DARK_GRAY, 21)
    # Generic APM
    apm_col = MID_GRAY if apm == "✗" else DARK_GRAY
    cell(s9, apm, 7.7, y, 3.5, 0.9, bg, apm_col, 21, False, PP_ALIGN.CENTER)
    # Cloud AI
    cloud_col = MID_GRAY if cloud == "✗" else DARK_GRAY
    cell(s9, cloud, 11.4, y, 3.5, 0.9, bg, cloud_col, 21, False, PP_ALIGN.CENTER)
    # This Solution — light red tint, green checkmark
    sol_col = GREEN if sol == "✓" else MID_GRAY
    sol_bold = sol == "✓"
    cell(s9, sol, 15.1, y, 4.5, 0.9, LIGHT_RED_TINT, sol_col, 21, sol_bold, PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — Time to Value
# ══════════════════════════════════════════════════════════════════════════════
s10 = prs.slides.add_slide(BLANK)

red_top_bar(s10)

add_text_box(s10,
    "Running in Your Environment in Under a Day",
    1.0, 0.7, 18, 2.0, 60, True, RED)

phases = [
    (0.5,  LIGHT_GRAY, DARK_GRAY, DARK_GRAY,
     "PHASE 1 — 2 to 4 hours", "Deploy",
     "OpenShift manifests, RHOAI endpoint, JIRA configuration"),
    (7.3,  LIGHT_GRAY, DARK_GRAY, DARK_GRAY,
     "PHASE 2 — 1 to 2 hours", "Validate",
     "Inject test errors, confirm ticket creation, tune patterns"),
    (14.1, RED,        WHITE,     WHITE,
     "PHASE 3 — Ongoing", "Expand",
     "Add namespaces, extend to Quarkus and Spring Boot"),
]

for bx, bg, text_col, body_col, phase_lbl, phase_title, body in phases:
    add_rect(s10, bx, 3.2, 5.5, 6.8, bg)
    add_text_box(s10, phase_lbl,   bx + 0.2, 3.5, 5.1, 0.7, 22, True,  BLUE if bg != RED else WHITE)
    add_text_box(s10, phase_title, bx + 0.2, 4.4, 5.1, 0.8, 30, True,  RED  if bg != RED else WHITE)
    add_text_box(s10, body,        bx + 0.2, 5.3, 5.1, 4.5, 22, False, body_col, wrap=True)

# Arrows
for ax in [6.3, 13.1]:
    add_text_box(s10, "→", ax, 6.0, 1.0, 0.8, 32, True, RED, align=PP_ALIGN.CENTER)

add_text_box(s10,
    "No professional services engagement required for initial deployment. Customer owns and operates it.",
    1.0, 10.3, 18, 0.8, 20, False, MID_GRAY, italic=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 11 — Call to Action
# ══════════════════════════════════════════════════════════════════════════════
s11 = prs.slides.add_slide(BLANK)

red_top_bar(s11)

add_text_box(s11,
    "Three Ways to Move Forward Today",
    1.0, 0.7, 18, 2.0, 60, True, RED)

options = [
    (3.0, LIGHT_GRAY, DARK_GRAY,
     "Option 1 — Proof of Value (1 week)",
     "Deploy in non-production. Run for one week. Measure MTTR delta vs baseline."),
    (5.4, LIGHT_GRAY, DARK_GRAY,
     "Option 2 — Architecture Workshop (half day)",
     "Red Hat architect maps the solution to your JBoss topology and RHOAI setup."),
    (7.8, RED,        WHITE,
     "Option 3 — Production Deployment",
     "Scoped engagement: deploy, configure, and hand over with runbook and training."),
]

for y, bg, body_col, lbl, body in options:
    add_rect(s11, 1.5, y, 17, 2.0, bg)
    lbl_col = WHITE if bg == RED else BLUE
    add_text_box(s11, lbl,  1.7, y + 0.15, 16.6, 0.7, 22, True,  lbl_col)
    add_text_box(s11, body, 1.7, y + 0.85, 16.6, 1.0, 22, False, body_col, wrap=True)

add_text_box(s11,
    "All source code is open and customer-owned.",
    1.5, 10.2, 17, 0.7, 20, False, MID_GRAY, italic=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 12 — Thank You
# ══════════════════════════════════════════════════════════════════════════════
s12 = prs.slides.add_slide(BLANK)

add_rect(s12, 0, 0, 20, 11.25, NEAR_BLACK)
add_rect(s12, 0, 0, 0.5, 11.25, RED)

add_text_box(s12, "Questions?",
    1.5, 2.5, 16, 3.0, 80, True, WHITE)

add_text_box(s12,
    "Let us talk about your JBoss environment.",
    1.5, 5.8, 14, 1.5, 32, False, LIGHT_GRAY)

add_text_box(s12,
    "[Name] · [email] · Red Hat Senior Architect",
    1.5, 9.5, 14, 0.8, 22, False, MID_GRAY)


# ── Save ───────────────────────────────────────────────────────────────────────
import os
out_path = os.path.join(os.path.dirname(__file__), "jboss-ai-monitor-deck.pptx")
prs.save(out_path)
print(f"DONE — deck written to docs/jboss-ai-monitor-deck.pptx")
