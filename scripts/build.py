#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build every deliverable from the single source of truth in data/.

Outputs:
  docs/01-test-plan-mfq.md          main MFQ test plan + test case document
  docs/02-mindmap-mfq.md            hierarchical Markdown (XMind import fallback)
  mindmaps/MFQ-Test-Plan.xmind      real .xmind workbook (ZIP + content.json/metadata.json/manifest.json)
  test-cases/MFQ-test-cases.xlsx    flat, filterable case table (CSV fallback if openpyxl is absent)
  data/cases.json                   generated mirror of the tree, for tooling and diffing

Run:  python3 scripts/build.py
"""
import base64
import csv
import io
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "data"))

from meta import META, OBJECTIVE_MD, SCOPE_IN, SCOPE_OUT, ASSUMPTIONS, RISK_TABLE   # noqa: E402
from models import MODELS, ORDER_STATES                                            # noqa: E402
from functional import FUNCTIONAL                                                   # noqa: E402
from quality import QUALITY                                                         # noqa: E402
from dedicated import DEDICATED                                                     # noqa: E402
from traceability import MANDATORY_COVERAGE, DELIVERABLE_MAP                        # noqa: E402
from strategy import STRATEGY_MD                                                    # noqa: E402

PDF_CSS = """
@page { size: A4; margin: 14mm 13mm 14mm 13mm; }
html { font-size: 10pt; }
body { font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
       color: #1b1b1b; line-height: 1.42; }
h1 { font-size: 17pt; margin: 0 0 4pt; color: #14243a; }
h2 { font-size: 12.5pt; margin: 12pt 0 4pt; color: #14243a; border-bottom: 1px solid #d4dae2; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 10pt 0 3pt; color: #24405f; }
h4 { font-size: 10pt; margin: 8pt 0 2pt; color: #2f4a68; }
p, li { margin: 2pt 0; }
ul, ol { margin: 2pt 0 4pt 14pt; padding: 0; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.5pt;
       background: #f1f3f6; padding: 0 2pt; border-radius: 2pt; }
pre { background: #f6f7f9; border: 1px solid #e0e4ea; padding: 5pt; font-size: 8pt;
      font-family: "SF Mono", Menlo, Consolas, monospace; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt; font-size: 8.2pt; }
th { background: #eef1f5; text-align: left; }
th, td { border: 1px solid #cfd6df; padding: 2.5pt 4pt; vertical-align: top; }
hr { border: none; border-top: 1px solid #cfd6df; margin: 8pt 0; }
.lede { color: #4a5568; font-style: italic; margin-bottom: 8pt; }
body.strategy { font-size: 8.6pt; line-height: 1.26; }
body.strategy h1 { font-size: 13.5pt; margin-bottom: 2pt; }
body.strategy h2 { font-size: 10pt; margin: 6pt 0 2pt; border-bottom: 1px solid #dfe4ea; padding-bottom: 1pt; }
body.strategy p { margin: 1.5pt 0; }
body.strategy ul { margin: 1pt 0 3pt 12pt; }
body.strategy li { margin: 0.5pt 0; }
body.strategy table { font-size: 7pt; margin: 2pt 0 4pt; }
body.strategy th, body.strategy td { padding: 1.6pt 3pt; }
body.strategy code { font-size: 7.4pt; }
.doc { page-break-before: always; }
"""


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s):
    s = _esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def _table_html(block):
    rows = []
    for ln in block:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    out = ["<table><thead><tr>"]
    out += ["<th>%s</th>" % _inline(c) for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def md_to_html(md):
    lines = md.split("\n")
    out, i = [], 0
    para_stop = ("#", "```", "|", "- ", ">")
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        if ln.lstrip().startswith("```"):
            lang = ln.lstrip()[3:].strip()
            buf, i = [], i + 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = ' class="diagram"' if lang == "mermaid" else ""
            out.append("<pre%s>%s</pre>" % (cls, _esc("\n".join(buf))))
            continue
        if re.match(r"^#{1,6}\s", ln):
            m = re.match(r"(#+)\s+(.*)", ln)
            lvl = min(len(m.group(1)), 4)
            out.append("<h%d>%s</h%d>" % (lvl, _inline(m.group(2)), lvl))
            i += 1
            continue
        if ln.strip() in ("---", "***", "___"):
            out.append("<hr/>")
            i += 1
            continue
        if ln.lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table_html(block))
            continue
        if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* "):
            items, cur = [], None
            while i < len(lines):
                l = lines[i]
                m = re.match(r"^\s*[-*]\s+(.*)", l)
                if m:
                    if cur is not None:
                        items.append(" ".join(cur))
                    cur = [m.group(1).strip()]
                    i += 1
                elif cur is not None and l.strip() and re.match(r"^(\s{2,}|\t)", l):
                    cur.append(l.strip())
                    i += 1
                else:
                    break
            if cur is not None:
                items.append(" ".join(cur))
            out.append("<ul>" + "".join("<li>%s</li>" % _inline(x) for x in items) + "</ul>")
            continue
        if re.match(r"^\s*\d+\.\s", ln):
            items, cur = [], None
            while i < len(lines):
                l = lines[i]
                m = re.match(r"^\s*\d+\.\s+(.*)", l)
                if m:
                    if cur is not None:
                        items.append(" ".join(cur))
                    cur = [m.group(1).strip()]
                    i += 1
                elif cur is not None and l.strip() and re.match(r"^(\s{2,}|\t)", l):
                    cur.append(l.strip())
                    i += 1
                else:
                    break
            if cur is not None:
                items.append(" ".join(cur))
            out.append("<ol>" + "".join("<li>%s</li>" % _inline(x) for x in items) + "</ol>")
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(para_stop) \
                and not re.match(r"^\s*\d+\.\s", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        if not buf:
            buf, i = [ln.strip()], i + 1
        text = " ".join(buf)
        cls = ' class="lede"' if re.fullmatch(r"\*[^*].*\*", text) else ""
        out.append("<p%s>%s</p>" % (cls, _inline(text)))
    return "\n".join(out)


def html_doc(title, body, extra_class=""):
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"/>\n"
        "<title>%s</title>\n<style>%s</style></head>\n<body%s>\n%s\n</body></html>\n"
        % (_esc(title), PDF_CSS, (' class="%s"' % extra_class) if extra_class else "", body)
    )


def chrome_pdf(html_path, pdf_path):
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome):
        return None
    scratch = os.path.expanduser("~/.hermes/cache/scratch/chrome-pdf-profile")
    os.makedirs(scratch, exist_ok=True)
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + scratch, "--no-pdf-header-footer",
        "--print-to-pdf=" + pdf_path, "file://" + html_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=240, check=False)
    except Exception:
        return None
    return pdf_path if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000 else None

# --------------------------------------------------------------------------- model

LAYER_STYLE = {
    "M": {"title": "M: Models", "fill": "#2E6DA4", "light": "#D6E4F0",
          "intro": "Five models, each with the invariant or guard that makes it testable."},
    "F": {"title": "F: Functional", "fill": "#2E7D4F", "light": "#D9EEDF",
          "intro": "Functional coverage expressed as a case tree: every case carries an id, a priority, preconditions, steps and an expected result traceable to a model."},
    "Q": {"title": "Q: Quality", "fill": "#B4622A", "light": "#F7E3D4",
          "intro": "Non-functional risk control: measurable targets, parameterised mechanisms, and drills with explicit targets."},
    "S": {"title": "Dedicated Sections (mandatory)", "fill": "#6B4AA0", "light": "#E4DAF2",
          "intro": "The three sections the brief marks as mandatory, viewed across layers: inventory synchronization consistency, exception handling and compensation, and release entry/exit criteria."},
}

LAYERS = [
    {"id": "M", "layer": "M", "title": LAYER_STYLE["M"]["title"], "children": MODELS},
    {"id": "F", "layer": "F", "title": LAYER_STYLE["F"]["title"], "children": FUNCTIONAL},
    {"id": "Q", "layer": "Q", "title": LAYER_STYLE["Q"]["title"], "children": QUALITY},
    {"id": "S", "layer": "S", "title": LAYER_STYLE["S"]["title"], "children": DEDICATED},
]

ROOT_TITLE = "MFQ Test Plan - E-Commerce System"

PRIORITY_MEANING = [
    ("P0", "Release-blocking. Money, inventory truth, or an irreversible one-way door. Executed on every build and every candidate."),
    ("P1", "Core regression. The flow a normal customer walks. Executed every test round; a failure blocks the release unless explicitly deferred."),
    ("P2", "Robustness, edge and hygiene. Executed at milestones; a failure is triaged rather than automatically blocking."),
]

SEVERITY_MEANING = [
    ("Sev1", "Data corruption or money loss: oversell, double deduct, lost payment, wrong refund. Stop the release."),
    ("Sev2", "Core function unusable or a wrong customer-facing outcome with no workaround."),
    ("Sev3", "Function degraded or a wrong outcome with a workaround."),
    ("Sev4", "Cosmetic, logging or documentation defect."),
]


def nid():
    return uuid.uuid4().hex


def walk(node):
    yield node
    for c in node.get("children") or []:
        yield from walk(c)


def all_cases():
    out = []
    for layer in LAYERS:
        for node in layer["children"]:
            for n in walk(node):
                if n.get("kind") == "case":
                    n["_layer"] = layer["layer"]
                    n["_module"] = node["id"]
                    n["_module_title"] = node["title"]
                    out.append(n)
    return out


CASES = all_cases()


# ----------------------------------------------------------------------- markdown

def md_escape(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_table(t, out):
    if t.get("title"):
        out.append("**%s**" % t["title"])
        out.append("")
    cols = t["columns"]
    out.append("| " + " | ".join(md_escape(c) for c in cols) + " |")
    out.append("|" + "|".join(["---"] * len(cols)) + "|")
    for row in t["rows"]:
        cells = [md_escape(c) for c in row] + [""] * (len(cols) - len(row))
        out.append("| " + " | ".join(cells[:len(cols)]) + " |")
    out.append("")


def render_case(c, level, out):
    head = "#" * level
    out.append("%s %s %s  `%s`" % (head, c["id"], c["title"], c.get("priority", "-")))
    out.append("")
    meta_bits = []
    if c.get("tags"):
        meta_bits.append("**Tags:** " + ", ".join("`%s`" % t for t in c["tags"]))
    if c.get("refs"):
        meta_bits.append("**Traceability:** " + ", ".join("`%s`" % r for r in c["refs"]))
    if c.get("api"):
        meta_bits.append("**API / artifact:** `%s`" % c["api"])
    if meta_bits:
        out.append(" · ".join(meta_bits))
        out.append("")
    for label, key in (("Precondition", "precondition"), ("Steps", "steps"), ("Expected result", "expected")):
        items = c.get(key) or []
        if not items:
            continue
        out.append("**%s**" % label)
        out.append("")
        for i, it in enumerate(items, 1):
            out.append("%d. %s" % (i, it))
        out.append("")


def render_node_body(n, level, out):
    if n.get("intro_md"):
        out.append(n["intro_md"].strip())
        out.append("")
    for t in n.get("tables") or []:
        render_table(t, out)
    if n.get("mermaid"):
        out.append("```mermaid")
        out.append(n["mermaid"])
        out.append("```")
        out.append("")
    for b in n.get("bullets") or []:
        out.append("- %s" % b)
    if n.get("bullets"):
        out.append("")
    for c in n.get("children") or []:
        render_node(c, min(level + 1, 6), out)


def render_node(n, level, out):
    if n.get("kind") == "case":
        render_case(n, level, out)
        return
    out.append("%s %s %s" % ("#" * level, n["id"], n["title"]))
    out.append("")
    render_node_body(n, level, out)


def build_main_md():
    out = []
    A = out.append
    A("# %s" % META["title"])
    A("")
    A("## %s" % META["subtitle"])
    A("")
    render_table({"columns": ["Attribute", "Value"], "rows": [
        ["Document", META["doc_id"]],
        ["Framework", META["framework"]],
        ["Version / date", "%s / %s" % (META["version"], META["date"])],
        ["Case count", "%d executable cases across %d modules (F1-F4 and Q1-Q5). The M layer and the dedicated sections contribute models and specifications; the traceability matrix maps each of them to the cases that carry the assertion" % (len(CASES), len(set(c["_module"] for c in CASES)))],
        ["Reading order", "M -> F -> Q -> dedicated sections -> traceability matrix. The dedicated sections are cross-layer summaries; read them after F."],
    ]}, out)

    # --- objective / scope
    A("## 0. Objective")
    A("")
    A(OBJECTIVE_MD.strip())
    A("")
    A("### 0.1 Scope in")
    A("")
    for s in SCOPE_IN:
        A("- %s" % s)
    A("")
    A("### 0.2 Scope out")
    A("")
    for s in SCOPE_OUT:
        A("- %s" % s)
    A("")
    A("### 0.3 Assumptions the plan depends on")
    A("")
    for i, s in enumerate(ASSUMPTIONS, 1):
        A("%d. %s" % (i, s))
    A("")
    A("### 0.4 Risk register")
    A("")
    render_table(RISK_TABLE, out)

    # --- layers
    A("### 0.5 MFQ structure at a glance")
    A("")
    for layer in LAYERS:
        st = LAYER_STYLE[layer["layer"]]
        A("- **%s** - %s" % (st["title"], st["intro"]))
    A("")

    num = 0
    for layer in LAYERS:
        key = layer["layer"]
        if key == "S":
            # The three dedicated sections are numbered top-level sections in their own right,
            # so a cross-reference like "see S5" lands on section 5.
            for n in layer["children"]:
                num += 1
                A("## %d. %s (dedicated section)" % (num, n["title"].replace("Dedicated: ", "")))
                A("")
                render_node_body(n, 3, out)
            continue
        num += 1
        st = LAYER_STYLE[key]
        A("## %d. %s" % (num, st["title"]))
        A("")
        A(st["intro"])
        A("")
        for n in layer["children"]:
            render_node(n, 3, out)

    # --- traceability
    A("## %d. Mandatory requirement coverage (traceability matrix)" % (num + 1))
    A("")
    A("Every item the brief marks as mandatory, mapped to the cases that cover it. The mapping is checked in both directions at build time: an uncovered requirement fails the build, and so does a case that no requirement row claims.")
    A("")
    render_table({
        "columns": ["Layer", "Mandatory requirement", "Covered by"],
        "rows": [[r["layer"], r["requirement"], r["cases"] and ", ".join("`%s`" % c for c in r["cases"]) or "-"] for r in MANDATORY_COVERAGE],
    }, out)

    # --- deliverables
    A("## %d. Deliverable map" % (num + 2))
    A("")
    render_table({
        "columns": ["Submission requirement", "Deliverable in this repository"],
        "rows": [[d["requirement"], d["deliverable"]] for d in DELIVERABLE_MAP],
    }, out)

    # --- appendix
    A("## %d. Appendix" % (num + 3))
    A("")
    A("### A.1 Priority definitions used throughout the case tree")
    A("")
    render_table({"columns": ["Priority", "Meaning"], "rows": [[p, m] for p, m in PRIORITY_MEANING]}, out)
    A("### A.2 Defect severity definitions")
    A("")
    render_table({"columns": ["Severity", "Meaning"], "rows": [[s, m] for s, m in SEVERITY_MEANING]}, out)
    A("### A.3 Priority distribution of this case set")
    A("")
    dist = {}
    for c in CASES:
        dist[c.get("priority", "-")] = dist.get(c.get("priority", "-"), 0) + 1
    render_table({"columns": ["Priority", "Cases"], "rows": [[k, dist[k]] for k in sorted(dist)]}, out)
    A("### A.4 Execution guidance")
    A("")
    for line in [
        "Smoke (every build, ~30min): the F1 happy path plus F2-01/F2-04/F2-08/F2-10.",
        "Core regression (every test round): all P0 plus the P1 inventory-sync block.",
        "Consistency campaign (per release): the whole F2 fault-injection matrix, repeated at least 20 times for the race cases, plus Q1-01 and Q2-01.",
        "Non-functional campaign (per release): Q1 targets at 1.5x peak, the Q2 chaos set, every alert in the Q3 catalog, Q4 security suite, Q5 drills.",
        "Entry/exit gate: see section 6 (release entry/exit criteria); the traceability matrix plus the invariant evidence is the release evidence pack.",
    ]:
        A("- %s" % line)
    A("")
    A("### A.5 Test data and environment")
    A("")
    for line in [
        "Environments: DEV (functional), TEST/STAGE (integration, fault injection, full MFQ run), PERF (production-like topology, isolated data).",
        "WMS/SC2P mock must expose a per-message fault-injection switch covering the matrix in the F2 section, plus controllable latency and version fields for E4/E5.",
        "Payment: sandbox gateway plus a signed-callback replay tool with controllable pay_no, amount and timestamp.",
        "Data: SKU/warehouse/stock fixtures, a conflict fixture (a single unit of stock for the race cases), and a one-command reset that also clears the ledger.",
        "Every automated inventory assertion must read the ledger, not just the API response; the ledger is the oracle.",
    ]:
        A("- %s" % line)
    A("")
    A("---")
    A("")
    A("Generated from `data/` by `scripts/build.py`. Do not edit this file by hand: change the data modules and rebuild, so the document, the mind map and the spreadsheet can never disagree.")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- mindmap markdown

def build_mindmap_md():
    """Nested bullets, indented two spaces per level: the most reliably importable shape."""
    out = ["# %s" % ROOT_TITLE, ""]

    def emit(node, depth):
        if node.get("kind") == "case":
            label = "%s %s [%s]" % (node["id"], node["title"], node.get("priority", "-"))
        else:
            label = ("%s %s" % (node.get("id", ""), node.get("title", ""))).strip()
        out.append("%s- %s" % ("  " * depth, label))
        for t in (node.get("tables") or []):
            out.append("%s  - [table] %s" % ("  " * depth, t.get("title") or "table"))
        for b in (node.get("bullets") or []):
            out.append("%s  - %s" % ("  " * depth, b))
        for c in (node.get("children") or []):
            emit(c, depth + 1)

    for layer in LAYERS:
        wrapper = {"id": layer["layer"], "title": LAYER_STYLE[layer["layer"]]["title"], "children": layer["children"]}
        emit(wrapper, 0)
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------ .xmind

PRIORITY_MARKER = {"P0": "priority-1", "P1": "priority-2", "P2": "priority-3"}
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def case_notes(c):
    parts = []
    parts.append("Priority: %s" % c.get("priority", "-"))
    if c.get("tags"):
        parts.append("Tags: " + ", ".join(c["tags"]))
    for label, key in (("Precondition", "precondition"), ("Steps", "steps"), ("Expected result", "expected")):
        items = c.get(key) or []
        if items:
            parts.append("")
            parts.append(label + ":")
            for i, it in enumerate(items, 1):
                parts.append("  %d. %s" % (i, it))
    if c.get("api"):
        parts.append("")
        parts.append("API/artifact: %s" % c["api"])
    if c.get("refs"):
        parts.append("Traceability: " + ", ".join(c["refs"]))
    return "\n".join(parts)


def json_topic(node, layer, role="module"):
    if node.get("kind") == "case":
        title = "%s %s" % (node["id"], node["title"])
    else:
        title = ("%s %s" % (node.get("id", ""), node.get("title", ""))).strip()
    t = {"id": nid(), "class": "topic", "title": title}
    if role == "root":
        t["structureClass"] = "org.xmind.ui.logic.right"
    st = LAYER_STYLE[layer]
    if role == "root":
        t["style"] = {"properties": {"svg:fill": "#1F3B57", "fo:color": "#FFFFFF"}}
    elif role in ("layer",):
        t["style"] = {"properties": {"svg:fill": st["fill"], "fo:color": "#FFFFFF"}}
    elif role == "case":
        t["markers"] = [{"markerId": PRIORITY_MARKER.get(node.get("priority"), "priority-3")}]
        t["labels"] = [node.get("priority", "-")]
        t["notes"] = {"plain": {"content": case_notes(node)}}
        t["style"] = {"properties": {"svg:fill": st["light"]}}
    else:
        t["style"] = {"properties": {"svg:fill": st["light"], "fo:color": "#1A1A1A"}}
    kids = node.get("children") or []
    if kids:
        t["children"] = {"attached": [
            json_topic(k, k.get("layer", layer), child_role(role, k)) for k in kids
        ]}
    return t


def child_role(parent_role, child):
    if child.get("kind") == "case":
        return "case"
    if parent_role == "root":
        return "layer"
    if parent_role == "layer":
        return "module"
    return "sub"


def build_content_json(root_topic):
    sheet_id = nid()
    sheet = {
        "id": sheet_id,
        "class": "sheet",
        "title": "MFQ Test Plan",
        "rootTopic": root_topic,
        "topicPositioning": "fixed",
        "topicOverlapping": "overlap",
    }
    return [sheet], sheet_id


def xml_topic(node, ns, layer):
    el = ET.Element("{%s}topic" % ns, {"id": nid()})
    if node.get("kind") == "case":
        title = "%s %s" % (node["id"], node["title"])
    else:
        title = ("%s %s" % (node.get("id", ""), node.get("title", ""))).strip()
    t = ET.SubElement(el, "{%s}title" % ns)
    t.text = title
    if node.get("kind") == "case":
        refs = ET.SubElement(el, "{%s}marker-refs" % ns)
        ET.SubElement(refs, "{%s}marker-ref" % ns, {"marker-id": PRIORITY_MARKER.get(node.get("priority"), "priority-3")})
    kids = node.get("children") or []
    if kids:
        ch = ET.SubElement(el, "{%s}children" % ns)
        topics = ET.SubElement(ch, "{%s}topics" % ns, {"type": "attached"})
        for k in kids:
            topics.append(xml_topic(k, ns, layer))
    return el


def build_xmind(path):
    root_topic = json_topic({"title": ROOT_TITLE, "children": LAYERS}, "M", role="root")
    sheets, sheet_id = build_content_json(root_topic)

    metadata = {
        "modifier": "",
        "dataStructureVersion": "2",
        "creator": {"name": "Hermes Agent", "version": "1.0"},
        "layoutEngineVersion": "3",
        "activeSheetId": sheet_id,
    }
    manifest = {
        "file-entries": {
            "content.json": {},
            "content.xml": {},
            "metadata.json": {},
            "Thumbnails/thumbnail.png": {},
        }
    }
    meta_inf = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<manifest xmlns="urn:xmind:xmap:xmlns:manifest:1.0">\n'
        '  <file-entry full-path="content.json" media-type="application/json"/>\n'
        '  <file-entry full-path="content.xml" media-type="text/xml"/>\n'
        '  <file-entry full-path="metadata.json" media-type="application/json"/>\n'
        '  <file-entry full-path="Thumbnails/thumbnail.png" media-type="image/png"/>\n'
        '</manifest>\n'
    )

    ns = "urn:xmind:xmap:xmlns:content:2.0"
    ET.register_namespace("", ns)
    xroot = ET.Element("{%s}xmap-content" % ns, {"version": "2.0"})
    sheet_el = ET.SubElement(xroot, "{%s}sheet" % ns, {"id": sheet_id})
    sheet_el.append(xml_topic({"title": ROOT_TITLE, "children": LAYERS}, ns, "M"))
    st = ET.SubElement(sheet_el, "{%s}title" % ns)
    st.text = "MFQ Test Plan"
    content_xml = ET.tostring(xroot, encoding="unicode")
    content_xml = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + content_xml + "\n"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("content.json", json.dumps(sheets, ensure_ascii=False, indent=1))
        z.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=1))
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr("content.xml", content_xml)
        z.writestr("META-INF/manifest.xml", meta_inf)
        z.writestr("Thumbnails/thumbnail.png", PNG_1PX)
    return sheets[0]


# ------------------------------------------------------------------------- xlsx

FLAT_HEADER = ["Case ID", "Layer", "Module", "Module title", "Case title", "Priority",
               "Precondition", "Steps", "Expected result", "API / artifact", "Tags", "Traceability"]


def flat_rows():
    rows = []
    for c in CASES:
        rows.append([
            c["id"], c["_layer"], c["_module"], c["_module_title"], c["title"], c.get("priority", ""),
            "\n".join("%d. %s" % (i, s) for i, s in enumerate(c.get("precondition") or [], 1)),
            "\n".join("%d. %s" % (i, s) for i, s in enumerate(c.get("steps") or [], 1)),
            "\n".join("%d. %s" % (i, s) for i, s in enumerate(c.get("expected") or [], 1)),
            c.get("api", ""),
            ", ".join(c.get("tags") or []),
            ", ".join(c.get("refs") or []),
        ])
    return rows


def build_xlsx(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        csv_path = path.replace(".xlsx", ".csv")
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(FLAT_HEADER)
            w.writerows(flat_rows())
        return csv_path

    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    fill_by_priority = {"P0": "FFC7CE", "P1": "FFEB9C", "P2": "D9E9D4"}
    hdr_fill = PatternFill("solid", fgColor="1F3B57")
    hdr_font = Font(bold=True, color="FFFFFF")
    ws.append(FLAT_HEADER)
    for i, _ in enumerate(FLAT_HEADER, 1):
        cell = ws.cell(row=1, column=i)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(vertical="center")
    for r in flat_rows():
        ws.append(r)
    widths = [10, 7, 9, 34, 52, 9, 44, 52, 62, 22, 22, 26]
    for i, wdt in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = wdt
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(FLAT_HEADER)):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        p = row[5].value
        if p in fill_by_priority:
            row[5].fill = PatternFill("solid", fgColor=fill_by_priority[p])
            row[5].font = Font(bold=True)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(FLAT_HEADER)), ws.max_row)

    ws2 = wb.create_sheet("MFQ Coverage")
    ws2.append(["Layer", "Mandatory requirement", "Covered by"])
    for i in range(1, 4):
        ws2.cell(row=1, column=i).fill = hdr_fill
        ws2.cell(row=1, column=i).font = hdr_font
    for r in MANDATORY_COVERAGE:
        ws2.append([r["layer"], r["requirement"], ", ".join(r["cases"])])
    ws2.column_dimensions["A"].width = 8
    ws2.column_dimensions["B"].width = 78
    ws2.column_dimensions["C"].width = 60
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row, max_col=3):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws3 = wb.create_sheet("Summary")
    dist = {}
    for c in CASES:
        dist[c.get("priority", "-")] = dist.get(c.get("priority", "-"), 0) + 1
    ws3.append(["MFQ Test Plan - case summary"])
    ws3.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws3.append([])
    ws3.append(["Layer", "Cases"])
    ws3.cell(row=3, column=1).font = Font(bold=True)
    ws3.cell(row=3, column=2).font = Font(bold=True)
    for layer in LAYERS:
        n = len([c for c in CASES if c["_layer"] == layer["layer"]])
        ws3.append([layer["title"], n if n else "n/a (no executable cases in this layer)"])
    ws3.append(["TOTAL", len(CASES)])
    ws3.append([])
    ws3.append(["Priority", "Cases"])
    ws3.cell(row=ws3.max_row, column=1).font = Font(bold=True)
    ws3.cell(row=ws3.max_row, column=2).font = Font(bold=True)
    for k in sorted(dist):
        ws3.append([k, dist[k]])
    ws3.column_dimensions["A"].width = 42
    ws3.column_dimensions["B"].width = 10

    wb.save(path)
    return path


# ------------------------------------------------------------------- README + SVG

README_TMPL = """# {title}

**{framework}** - test plan and test case design for the e-commerce system described in the brief
(Product SPU/SKU, Inventory, Cart, Order lifecycle, external WMS/SC2P synchronization).

This repository is the submission package. Everything in it is generated from one data source
(`data/`), so the document, the mind map and the spreadsheet cannot disagree with each other.

## Read this first

| # | File | What it is |
|---|---|---|
| 1 | [`docs/03-strategy-note.pdf`](docs/03-strategy-note.pdf) (or [`.md`](docs/03-strategy-note.md)) | One-page strategy note: how cases were prioritized and what was deliberately traded away |
| 2 | [`mindmaps/MFQ-Test-Plan.xmind`](mindmaps/MFQ-Test-Plan.xmind) | The mind map. Top level is exactly **M / F / Q**, colour-coded, plus the mandatory dedicated sections. Every case carries a priority marker |
| 3 | [`docs/01-test-plan-mfq.md`](docs/01-test-plan-mfq.md) | The full plan: M models, F case tree with priority and expected results, Q quality targets, dedicated sections, traceability matrix ([PDF](docs/01-test-plan-mfq.pdf), {plan_pages} pages) |
| 4 | [`test-cases/MFQ-test-cases.xlsx`](test-cases/MFQ-test-cases.xlsx) | Flat, filterable case table for execution, plus the coverage matrix and a summary sheet |

## MFQ structure at a glance

```
{tree}
```

`M` and the dedicated sections hold models and specifications rather than executable cases; their
coverage shows up as the `F` and `Q` cases that reference them, which is what the traceability
matrix at the end of the plan checks.

## The case set

| Layer | Module | Cases |
|---|---|---|
{module_rows}
| | **TOTAL** | **{total}** |

`-` means the module is a model or a specification section: it produces assertions that the F and Q
cases carry out, rather than cases of its own.

Priority distribution: {priority_dist} - the rule is in the strategy note (P0 = money, inventory
truth, or a one-way door).

Every one of the {mandatory_count} requirements the brief marks as mandatory is traced to the cases
that cover it; see the traceability matrix in `docs/01-test-plan-mfq.md` and the `MFQ Coverage`
sheet of the workbook.

## How to open the mind map

- **XMind 2020 (Zen) or newer:** open `mindmaps/MFQ-Test-Plan.xmind` directly. Priority markers and
  per-case notes (steps and expected results) are embedded in the topics - expand a case to read it.
- **No XMind available:** import `docs/02-mindmap-mfq.md`, the hierarchical Markdown version of the
  same tree, or read `docs/00-mindmap-preview.svg` for the structure without any tool.
- The workbook also carries a legacy `content.xml`, so older XMind 8 builds can read it too.

## Rebuilding

```bash
python3 scripts/build.py          # regenerates every deliverable from data/
python3 scripts/validate_xmind.py # reads the .xmind back and checks it against data/cases.json
```

`build.py` prints the case counts and fails loudly if any case is missing a priority, a step or an
expected result. `validate_xmind.py` unzips the workbook, parses both the JSON and the legacy XML
arm, and confirms every case in `data/cases.json` is present in the map.

## Repository layout

```
README.md
data/                     single source of truth
  meta.py                   scope, assumptions, risk register
  models.py                 M - the five models
  functional.py             F - {f_cases} cases in 4 modules
  quality.py                Q - {q_cases} cases in 5 quality areas
  dedicated.py              the three mandatory dedicated sections
  traceability.py           mandatory requirement -> case mapping
  strategy.py               the one-page strategy note
  cases.json                generated mirror, consumed by the validator
scripts/
  build.py                  generator: md, mindmap md, xmind, xlsx, pdf
  validate_xmind.py         independent read-back check of the workbook
docs/                     the documents (md, html, pdf, svg preview)
mindmaps/                 MFQ-Test-Plan.xmind
test-cases/               MFQ-test-cases.xlsx
```

## Scope note

In scope: listing, cart, order lifecycle, inventory states, WMS/SC2P synchronization, payment
callback handling and the APIs that mutate order or inventory state.
Out of scope: WMS/SC2P internals, payment-gateway internals, carrier routing, coupon rules and full
UI regression. The full assumption list and the risk register are in `docs/01-test-plan-mfq.md`
section 0.
"""


def build_readme(plan_pages="45"):
    modules = []
    for layer in LAYERS:
        for node in layer["children"]:
            n = len([c for c in CASES if c["_module"] == node["id"]])
            st = LAYER_STYLE[layer["layer"]]
            cell = str(n) if n else "-"
            modules.append("| %s | `%s` %s | %s |" % (st["title"], node["id"], node["title"], cell))
    dist = {}
    for c in CASES:
        dist[c.get("priority", "-")] = dist.get(c.get("priority", "-"), 0) + 1
    tree_lines = [ROOT_TITLE]
    for i, layer in enumerate(LAYERS):
        last_layer = i == len(LAYERS) - 1
        tree_lines.append(("`- " if last_layer else "+- ") + layer["title"])
        for node in layer["children"]:
            n = len([c for c in CASES if c["_module"] == node["id"]])
            prefix = "   " if last_layer else "|  "
            title = node["title"].replace("Dedicated: ", "")
            note = "  (%d cases)" % n if n else ""
            tree_lines.append("%s+- %s %s%s" % (prefix, node["id"], title, note))
    body = README_TMPL.format(
        title=META["title"],
        framework=META["framework"],
        tree="\n".join(tree_lines),
        module_rows="\n".join(modules),
        total=len(CASES),
        priority_dist=", ".join("%s %d" % (k, dist[k]) for k in sorted(dist)),
        mandatory_count=len(MANDATORY_COVERAGE),
        plan_pages=plan_pages,
        f_cases=len([c for c in CASES if c["_layer"] == "F"]),
        q_cases=len([c for c in CASES if c["_layer"] == "Q"]),
    )
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(body)
    return body


def build_svg(path):
    """A dependency-free preview of the top two levels, so the structure is visible without XMind."""
    import html as _html

    modules = []
    for layer in LAYERS:
        mods = []
        for node in layer["children"]:
            n = len([c for c in CASES if c["_module"] == node["id"]])
            mods.append({"id": node["id"], "title": node["title"], "n": n, "layer": layer["layer"]})
        modules.append({"layer": layer, "mods": mods})

    row_h, pad, col_l1, col_l2, w_l1, w_l2 = 30, 26, 300, 566, 252, 430
    badge = {}
    for layer in LAYERS:
        n = len([c for c in CASES if c["_layer"] == layer["layer"]])
        if n:
            badge[layer["layer"]] = "%d cases" % n
        elif layer["layer"] == "M":
            badge[layer["layer"]] = "%d models" % len(layer["children"])
        else:
            badge[layer["layer"]] = "%d sections" % len(layer["children"])
    short_title = {}
    for layer in LAYERS:
        t = layer["title"]
        short_title[layer["layer"]] = t if len(t) <= 26 else t.split("(")[0].strip()
    total_rows = sum(len(m["mods"]) for m in modules)
    height = pad * 2 + total_rows * row_h
    width = col_l2 + w_l2 + pad + 90

    ys = {}
    y = pad + row_h / 2.0
    for m in modules:
        layer_ys = []
        for mod in m["mods"]:
            ys[mod["id"]] = y
            layer_ys.append(y)
            y += row_h
        m["y"] = sum(layer_ys) / len(layer_ys)
    root_y = height / 2.0

    p = []
    p.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
             'viewBox="0 0 %d %d" font-family="-apple-system,Helvetica,Arial,sans-serif">'
             % (width, height, width, height))
    p.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    p.append('<text x="%d" y="16" font-size="13" font-weight="700" fill="#14243a">%s</text>'
             % (pad, _html.escape(ROOT_TITLE)))

    def edge(x1, y1, x2, y2, color):
        p.append('<path d="M%.1f %.1f C%.1f %.1f %.1f %.1f %.1f %.1f" fill="none" '
                 'stroke="%s" stroke-width="1.2" opacity="0.55"/>'
                 % (x1, y1, (x1 + x2) / 2, y1, (x1 + x2) / 2, y2, x2, y2, color))

    def box(x, y, w, fill, stroke, title, sub, tcolor, tsize=12, subcolor=None):
        p.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="5" fill="%s" stroke="%s"/>'
                 % (x, y - 12, w, 24, fill, stroke))
        p.append('<text x="%.1f" y="%.1f" font-size="%d" font-weight="600" fill="%s">%s</text>'
                 % (x + 9, y + 4, tsize, tcolor, _html.escape(title[:62])))
        if sub:
            p.append('<text x="%.1f" y="%.1f" font-size="10" fill="%s" text-anchor="end">%s</text>'
                     % (x + w - 9, y + 4, subcolor or tcolor, _html.escape(sub)))

    for m in modules:
        st = LAYER_STYLE[m["layer"]["layer"]]
        edge(pad + w_l1, root_y, col_l1, m["y"], "#1F3B57")
        for mod in m["mods"]:
            edge(col_l1 + w_l1, m["y"], col_l2, ys[mod["id"]], st["fill"])

    p.append('<rect x="%d" y="%.1f" width="%d" height="26" rx="6" fill="#1F3B57"/>'
             % (pad, root_y - 13, w_l1))
    p.append('<text x="%d" y="%.1f" font-size="12.5" font-weight="700" fill="#ffffff">%s</text>'
             % (pad + 10, root_y + 4.5, "MFQ Test Plan"))

    for i, m in enumerate(modules):
        st = LAYER_STYLE[m["layer"]["layer"]]
        box(col_l1, m["y"], w_l1, st["fill"], st["fill"],
            short_title[m["layer"]["layer"]], badge[m["layer"]["layer"]],
            "#ffffff", 12)
        for mod in m["mods"]:
            lab = "%s  %s" % (mod["id"], mod["title"])
            box(col_l2, ys[mod["id"]], w_l2, st["light"], st["fill"], lab,
                ("%d" % mod["n"]) if mod["n"] else "", "#1A1A1A", 11, "#3d4a57")

    p.append('</svg>')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p))
    return path

def pdf_pages(path):
    """Page count via Spotlight metadata on macOS, with a raw /Count fallback."""
    if not os.path.exists(path):
        return None
    try:
        out = subprocess.run(["mdls", "-name", "kMDItemNumberOfPages", "-raw", path],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        if out.isdigit():
            return int(out)
    except Exception:
        pass
    try:
        with open(path, "rb") as fh:
            hits = re.findall(rb"/Count\s+(\d+)", fh.read())
        if hits:
            return max(int(h) for h in hits)
    except Exception:
        pass
    return None


def self_check():
    problems = []
    seen = {}
    for c in CASES:
        if c["id"] in seen:
            problems.append("duplicate case id: %s" % c["id"])
        seen[c["id"]] = 1
        if c.get("priority") not in ("P0", "P1", "P2"):
            problems.append("%s has an invalid priority: %r" % (c["id"], c.get("priority")))
        if not c.get("expected"):
            problems.append("%s has no expected result" % c["id"])
        if not c.get("steps"):
            problems.append("%s has no steps" % c["id"])

    known = set()
    for layer in LAYERS:
        for node in layer["children"]:
            for n in walk(node):
                known.add(n.get("id"))
    known |= {"S4", "S5", "S6"}
    for c in CASES:
        for r in c.get("refs") or []:
            head = re.split(r"[/.]", r)[0]
            if head and head not in known and not head.startswith(("Q", "F", "M", "S")):
                problems.append("%s references an unknown id: %s" % (c["id"], r))

    # reverse traceability: every case must be claimed by at least one mandatory-coverage row
    def expand(spec):
        if ".." in spec:
            a, b = spec.split("..")
            pre, n1 = a.rsplit("-", 1)
            n2 = b.rsplit("-", 1)[1]
            return ["%s-%02d" % (pre, i) for i in range(int(n1), int(n2) + 1)]
        return [spec]

    named = set()
    for r in MANDATORY_COVERAGE:
        for spec in r["cases"]:
            named.update(expand(spec))
    for cid in sorted(set(c["id"] for c in CASES) - named):
        problems.append("%s is not named in any mandatory-coverage row" % cid)
    return problems


# ------------------------------------------------------------------------- main

def main():
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)

    main_md = build_main_md()
    with open(os.path.join(docs, "01-test-plan-mfq.md"), "w", encoding="utf-8") as fh:
        fh.write(main_md)

    mindmap_md = build_mindmap_md()
    with open(os.path.join(docs, "02-mindmap-mfq.md"), "w", encoding="utf-8") as fh:
        fh.write(mindmap_md)

    # strategy note (Markdown + HTML + PDF)
    strategy_md = STRATEGY_MD.strip() + "\n"
    strat_md_path = os.path.join(docs, "03-strategy-note.md")
    with open(strat_md_path, "w", encoding="utf-8") as fh:
        fh.write(strategy_md)
    strat_html_path = os.path.join(docs, "03-strategy-note.html")
    with open(strat_html_path, "w", encoding="utf-8") as fh:
        fh.write(html_doc("Strategy Note - MFQ Test Plan for the E-Commerce System", md_to_html(strategy_md), extra_class="strategy"))
    strat_pdf = chrome_pdf(strat_html_path, os.path.join(docs, "03-strategy-note.pdf"))

    # main plan (HTML + PDF, for readers who prefer a paged document)
    main_html_path = os.path.join(docs, "01-test-plan-mfq.html")
    with open(main_html_path, "w", encoding="utf-8") as fh:
        fh.write(html_doc(META["title"], md_to_html(main_md)))
    main_pdf = chrome_pdf(main_html_path, os.path.join(docs, "01-test-plan-mfq.pdf"))

    # structure preview (no XMind / no tooling required to see the MFQ layering)
    build_svg(os.path.join(docs, "00-mindmap-preview.svg"))

    build_xmind(os.path.join(ROOT, "mindmaps", "MFQ-Test-Plan.xmind"))

    xlsx = build_xlsx(os.path.join(ROOT, "test-cases", "MFQ-test-cases.xlsx"))

    mirror = {
        "meta": META,
        "layers": [
            {"layer": l["layer"], "title": l["title"], "nodes": l["children"]}
            for l in LAYERS
        ],
        "cases": [
            {k: v for k, v in c.items() if not k.startswith("_")} for c in CASES
        ],
        "traceability": MANDATORY_COVERAGE,
    }
    with open(os.path.join(ROOT, "data", "cases.json"), "w", encoding="utf-8") as fh:
        json.dump(mirror, fh, ensure_ascii=False, indent=1)

    dist = {}
    for c in CASES:
        dist[c.get("priority", "-")] = dist.get(c.get("priority", "-"), 0) + 1
    print("cases: %d  (%s)" % (len(CASES), ", ".join("%s=%d" % (k, dist[k]) for k in sorted(dist))))
    for layer in LAYERS:
        n = len([c for c in CASES if c["_layer"] == layer["layer"]])
        print("  %-28s %3d cases" % (layer["title"], n))
    print("modules: %d" % len(set(c["_module"] for c in CASES)))
    print("mandatory requirements traced: %d" % len(MANDATORY_COVERAGE))

    plan_pages = pdf_pages(os.path.join(docs, "01-test-plan-mfq.pdf"))
    build_readme(plan_pages=str(plan_pages or 45))
    strat_pages = pdf_pages(os.path.join(docs, "03-strategy-note.pdf"))

    problems = self_check()
    if problems:
        print("\nSELF-CHECK PROBLEMS (%d):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        sys.exit(1)
    print("\nself-check: OK (unique ids, valid priorities, non-empty steps and expected results, resolvable refs)")
    print("xlsx/csv: %s" % xlsx)
    print("mindmap: mindmaps/MFQ-Test-Plan.xmind")
    print("strategy pdf: %s (%s page)" % (strat_pdf or "SKIPPED (Chrome not found)", strat_pages))
    print("plan pdf: %s (%s pages)" % (main_pdf or "SKIPPED (Chrome not found)", plan_pages))
    print("readme: README.md")


if __name__ == "__main__":
    main()
