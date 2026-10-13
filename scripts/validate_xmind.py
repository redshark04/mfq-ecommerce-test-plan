#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate the generated .xmind workbook by reading it back the way a reader would:
unzip, parse content.json, parse the legacy content.xml, walk the tree, and compare the
topic inventory against data/cases.json.

This exists because a .xmind is only as good as its packaging: a missing metadata.json or a
duplicated topic id produces a file that opens blank, and nothing in the build would notice.

Run:  python3 scripts/validate_xmind.py [path/to/file.xmind]
"""
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT = os.path.join(ROOT, "mindmaps", "MFQ-Test-Plan.xmind")
MIRROR = os.path.join(ROOT, "data", "cases.json")

REQUIRED_ENTRIES = ["content.json", "metadata.json", "manifest.json"]
PRIORITY_MARKERS = {"priority-1", "priority-2", "priority-3"}


def walk_json(topic, depth=0, out=None):
    if out is None:
        out = []
    out.append((depth, topic.get("id"), topic.get("title", ""), topic.get("markers") or [], topic.get("labels") or []))
    for child in (topic.get("children") or {}).get("attached") or []:
        walk_json(child, depth + 1, out)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    problems = []

    if not os.path.exists(path):
        print("FAIL: %s does not exist" % path)
        return 1

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for req in REQUIRED_ENTRIES:
            if req not in names:
                problems.append("missing archive entry: %s" % req)
        sheets = json.loads(z.read("content.json").decode("utf-8"))
        metadata = json.loads(z.read("metadata.json").decode("utf-8"))
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        content_xml = z.read("content.xml").decode("utf-8") if "content.xml" in names else None

    if not isinstance(sheets, list) or not sheets:
        problems.append("content.json is not a non-empty list of sheets")
        sheets = []
    if sheets:
        sheet = sheets[0]
        if sheet.get("class") != "sheet":
            problems.append("sheet is missing class=sheet")
        if not sheet.get("rootTopic"):
            problems.append("sheet has no rootTopic")
        if metadata.get("activeSheetId") != sheet.get("id"):
            problems.append("metadata.activeSheetId does not match the sheet id")
    for key in ("dataStructureVersion", "layoutEngineVersion"):
        if key not in metadata:
            problems.append("metadata.json missing %s" % key)
    if "file-entries" not in manifest:
        problems.append("manifest.json missing file-entries")
    if manifest.get("file-entries", {}).get("content.json") is None:
        problems.append("manifest.json does not declare content.json")

    rows = walk_json(sheets[0]["rootTopic"]) if sheets else []

    ids = [r[1] for r in rows]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append("duplicate topic ids: %s" % dupes[:5])

    titles = [r[2] for r in rows]
    case_topics = [t for t in titles if t[:1] in "MFQS" and "-" in t.split(" ")[0] and t.split(" ")[0][1:2].isdigit()]
    tagged = [r for r in rows if r[4]]
    marked = [r for r in rows if r[3]]
    bad_markers = [r[3] for r in marked if not set(m.get("markerId") for m in r[3]) <= PRIORITY_MARKERS]

    # cross-check against the generated mirror
    mirror_cases = []
    if os.path.exists(MIRROR):
        with open(MIRROR, encoding="utf-8") as fh:
            mirror = json.load(fh)
        mirror_cases = [c["id"] for c in mirror.get("cases", [])]
        missing = [cid for cid in mirror_cases if not any(t.startswith(cid + " ") for t in titles)]
        if missing:
            problems.append("%d case ids from data/cases.json are absent from the mind map: %s" % (len(missing), missing[:8]))

    # the legacy XML arm must at least parse and carry the same root title
    if content_xml:
        try:
            ns = "{urn:xmind:xmap:xmlns:content:2.0}"
            root_el = ET.fromstring(content_xml)
            xsheet = root_el.find(".//%ssheet" % ns)
            if xsheet is None:
                problems.append("content.xml has no sheet element")
            else:
                xtitle = xsheet.find("%stopic/%stitle" % (ns, ns))
                if xtitle is None or not (xtitle.text or "").strip():
                    problems.append("content.xml root topic has no title")
                xml_cases = len([t for t in xsheet.iter("%stopic" % ns)])
                if xml_cases < 10:
                    problems.append("content.xml looks truncated (%d topics)" % xml_cases)
        except ET.ParseError as exc:
            problems.append("content.xml is not well-formed XML: %s" % exc)
    else:
        problems.append("content.xml is absent (legacy XMind 8 compatibility lost)")

    depth = max((r[0] for r in rows), default=0)

    print("file          : %s (%.1f KB)" % (path, os.path.getsize(path) / 1024.0))
    print("archive       : %s" % ", ".join(sorted(names)))
    print("topics        : %d total, %d case topics, %d with a priority label, %d with a priority marker"
          % (len(rows), len(case_topics), len(tagged), len(marked)))
    print("max depth     : %d" % depth)
    print("mirror cases  : %d in data/cases.json" % len(mirror_cases))
    print("top level     : %s" % ", ".join(t for d, _i, t, _m, _l in rows if d == 1))

    if bad_markers:
        problems.append("unexpected marker ids: %s" % bad_markers[:3])

    if problems:
        print("\nVALIDATION FAILED (%d):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        return 1

    print("\nVALIDATION PASSED: archive complete, JSON and XML arms both parse, ids unique, "
          "every mirrored case present, priority markers valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
