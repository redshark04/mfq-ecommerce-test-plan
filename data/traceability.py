# -*- coding: utf-8 -*-
"""Mandatory-requirement -> case traceability matrix.

Every bullet the exam marks as mandatory ("Must include at least ...") is listed here with the
cases that cover it, so the coverage claim is checkable rather than asserted.
"""

MANDATORY_COVERAGE = [
    {"layer": "M", "requirement": "End-to-end business flow model (order -> payment -> shipment -> signed -> return)",
     "cases": ["M1", "M1.1", "F1-01", "F1-06", "F1-07", "F1-09", "F1-12"]},
    {"layer": "M", "requirement": "Order state machine (states, events, transition conditions)",
     "cases": ["M2", "F1-11", "F3-06", "F3-07", "F3-16", "F4-11"]},
    {"layer": "M", "requirement": "Inventory state model (available, reserved, deducted, restored)",
     "cases": ["M3", "F2-01", "F2-04", "F2-06", "F2-17", "F3-10", "F3-15"]},
    {"layer": "M", "requirement": "External interaction model (storefront <-> WMS/SC2P)",
     "cases": ["M4", "M4.1", "F1-03", "F1-07", "F2-11", "F4-08", "F4-09"]},
    {"layer": "M", "requirement": "Consistency boundaries (strong, eventual, reconciliation points)",
     "cases": ["M5", "M5.1", "F2-14", "F2-15", "F2-18", "F2-20", "Q2-01"]},

    {"layer": "F", "requirement": "Core happy path coverage (order, payment, shipment, signed)",
     "cases": ["F1-01", "F1-02", "F1-06", "F1-07", "F1-08", "F1-09", "F1-10", "F1-12"]},
    {"layer": "F", "requirement": "Cart validation and order acceptance (off-shelf SKU, price change between add-to-cart and submit)",
     "cases": ["F1-04", "F1-05"]},
    {"layer": "F", "requirement": "Inventory sync: reserve success / failure",
     "cases": ["F2-01", "F2-02", "F2-03", "F3-01"]},
    {"layer": "F", "requirement": "Inventory sync: deduct success / failure",
     "cases": ["F2-04", "F2-05", "Q2-01", "Q2-03"]},
    {"layer": "F", "requirement": "Inventory sync: cancel and restore",
     "cases": ["F2-06", "F2-07", "F2-19", "F3-10", "F3-11"]},
    {"layer": "F", "requirement": "Inventory sync: idempotency for duplicate messages and duplicated requests",
     "cases": ["F2-08", "F2-09", "F2-10", "F2-17", "F3-12", "F3-14", "F4-02"]},
    {"layer": "F", "requirement": "Inventory sync: out-of-order message handling",
     "cases": ["F2-11", "F2-12", "F2-13", "Q2-04"]},
    {"layer": "F", "requirement": "Boundary: zero stock",
     "cases": ["F3-01", "F2-02"]},
    {"layer": "F", "requirement": "Boundary: quantity limits and oversized payload",
     "cases": ["F3-05", "F3-13"]},
    {"layer": "F", "requirement": "Boundary: high-concurrency flash sale",
     "cases": ["F3-02", "F3-03", "F3-04", "F3-15", "Q1-01"]},
    {"layer": "F", "requirement": "Boundary: partial shipment / split shipment",
     "cases": ["F1-08", "F3-08", "F3-09"]},
    {"layer": "F", "requirement": "Boundary: return and stock restoration",
     "cases": ["F1-12", "F3-10", "F3-11", "F3-12"]},
    {"layer": "F", "requirement": "Critical API validation: request fields",
     "cases": ["F4-01", "F4-05", "F4-06", "F4-10", "F4-11"]},
    {"layer": "F", "requirement": "Critical API validation: error codes",
     "cases": ["F4-05", "F4-07", "F4-08", "F4-09"]},
    {"layer": "F", "requirement": "Critical API validation: callback / write-back fields",
     "cases": ["F4-07", "F4-08", "F4-09", "Q4-01"]},

    {"layer": "Q", "requirement": "Performance: concurrency target, latency, error rate, throughput",
     "cases": ["Q1-01", "Q1-02", "Q1-03", "Q1-04"]},
    {"layer": "Q", "requirement": "Reliability: retry, fallback, timeout, circuit breaker, compensation jobs",
     "cases": ["Q2-01", "Q2-02", "Q2-03", "Q2-04"]},
    {"layer": "Q", "requirement": "Observability: logs, metrics, alerts (inventory diff ratio, message backlog, stuck orders)",
     "cases": ["Q3-01", "Q3-02", "Q3-03", "Q3-04"]},
    {"layer": "Q", "requirement": "Security: auth, permission boundaries, sensitive-data masking",
     "cases": ["Q4-01", "Q4-02", "Q4-03", "F4-03", "F4-04", "F4-12", "F4-13"]},
    {"layer": "Q", "requirement": "Recoverability: failure drills and data repair process",
     "cases": ["Q5-01", "Q5-02", "Q5-03", "Q5-04"]},

    {"layer": "S4", "requirement": "Dedicated section: inventory synchronization consistency",
     "cases": ["S4", "F2-01..F2-20", "F3-02", "F3-03", "F3-15", "Q1-01", "Q3-02"]},
    {"layer": "S5", "requirement": "Dedicated section: exception handling and compensation strategy",
     "cases": ["S5", "F2-05", "F2-07", "Q2-01", "Q2-03"]},
    {"layer": "S6", "requirement": "Dedicated section: release entry / exit criteria",
     "cases": ["S6", "Q4-04", "Q5-04"]},
]


# How the four candidate deliverables map to the exam's submission requirements.
DELIVERABLE_MAP = [
    {"requirement": "Test cases with case tree, priority and expected result",
     "deliverable": "docs/01-test-plan-mfq.md (case tree + priority + expected result) and test-cases/MFQ-test-cases.xlsx (flat, filterable)"},
    {"requirement": "Mind map in .xmind (preferred) or XMind-importable structured Markdown",
     "deliverable": "mindmaps/MFQ-Test-Plan.xmind (both provided; Markdown is the import fallback)"},
    {"requirement": "Bonus: mind map with a clear MFQ-layer structure",
     "deliverable": "mindmaps/MFQ-Test-Plan.xmind - top level is exactly M / F / Q, each colour-coded, with a dedicated-sections branch and priority markers on every case"},
    {"requirement": "Brief strategy note, within 1 page, explaining priorities and trade-offs",
     "deliverable": "docs/03-strategy-note.md and docs/03-strategy-note.pdf"},
]
