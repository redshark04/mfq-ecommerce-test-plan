# MFQ Test Plan and Test Case Design

**MFQ - Models / Functional / Quality** - test plan and test case design for the e-commerce system described in the brief
(Product SPU/SKU, Inventory, Cart, Order lifecycle, external WMS/SC2P synchronization).

This repository is the submission package. Everything in it is generated from one data source
(`data/`), so the document, the mind map and the spreadsheet cannot disagree with each other.

## Read this first

| # | File | What it is |
|---|---|---|
| 1 | [`docs/03-strategy-note.pdf`](docs/03-strategy-note.pdf) (or [`.md`](docs/03-strategy-note.md)) | One-page strategy note: how cases were prioritized and what was deliberately traded away |
| 2 | [`mindmaps/MFQ-Test-Plan.xmind`](mindmaps/MFQ-Test-Plan.xmind) | The mind map. Top level is exactly **M / F / Q**, colour-coded, plus the mandatory dedicated sections. Every case carries a priority marker |
| 3 | [`docs/01-test-plan-mfq.md`](docs/01-test-plan-mfq.md) | The full plan: M models, F case tree with priority and expected results, Q quality targets, dedicated sections, traceability matrix ([PDF](docs/01-test-plan-mfq.pdf), 43 pages) |
| 4 | [`test-cases/MFQ-test-cases.xlsx`](test-cases/MFQ-test-cases.xlsx) | Flat, filterable case table for execution, plus the coverage matrix and a summary sheet |

## MFQ structure at a glance

```
MFQ Test Plan - E-Commerce System
+- M: Models
|  +- M1 End-to-End Business Flow Model
|  +- M2 Order State Machine
|  +- M3 Inventory State Model
|  +- M4 External Interaction Model (Storefront <-> WMS/SC2P)
|  +- M5 Consistency Boundaries and Reconciliation Points
+- F: Functional
|  +- F1 Core Happy Path and Order Acceptance  (12 cases)
|  +- F2 Inventory Synchronization Scenarios  (20 cases)
|  +- F3 Boundary, Race and Volume Scenarios  (16 cases)
|  +- F4 Critical API and Contract Validation  (13 cases)
+- Q: Quality
|  +- Q1 Performance  (4 cases)
|  +- Q2 Reliability  (4 cases)
|  +- Q3 Observability  (4 cases)
|  +- Q4 Security  (4 cases)
|  +- Q5 Recoverability  (4 cases)
`- Dedicated Sections (mandatory)
   +- S4 Inventory Synchronization Consistency
   +- S5 Exception Handling and Compensation Strategy
   +- S6 Release Entry and Exit Criteria
```

`M` and the dedicated sections hold models and specifications rather than executable cases; their
coverage shows up as the `F` and `Q` cases that reference them, which is what the traceability
matrix at the end of the plan checks.

## The case set

| Layer | Module | Cases |
|---|---|---|
| M: Models | `M1` End-to-End Business Flow Model | - |
| M: Models | `M2` Order State Machine | - |
| M: Models | `M3` Inventory State Model | - |
| M: Models | `M4` External Interaction Model (Storefront <-> WMS/SC2P) | - |
| M: Models | `M5` Consistency Boundaries and Reconciliation Points | - |
| F: Functional | `F1` Core Happy Path and Order Acceptance | 12 |
| F: Functional | `F2` Inventory Synchronization Scenarios | 20 |
| F: Functional | `F3` Boundary, Race and Volume Scenarios | 16 |
| F: Functional | `F4` Critical API and Contract Validation | 13 |
| Q: Quality | `Q1` Performance | 4 |
| Q: Quality | `Q2` Reliability | 4 |
| Q: Quality | `Q3` Observability | 4 |
| Q: Quality | `Q4` Security | 4 |
| Q: Quality | `Q5` Recoverability | 4 |
| Dedicated Sections (mandatory) | `S4` Dedicated: Inventory Synchronization Consistency | - |
| Dedicated Sections (mandatory) | `S5` Dedicated: Exception Handling and Compensation Strategy | - |
| Dedicated Sections (mandatory) | `S6` Dedicated: Release Entry and Exit Criteria | - |
| | **TOTAL** | **81** |

`-` means the module is a model or a specification section: it produces assertions that the F and Q
cases carry out, rather than cases of its own.

Priority distribution: P0 47, P1 31, P2 3 - the rule is in the strategy note (P0 = money, inventory
truth, or a one-way door).

Every one of the 28 requirements the brief marks as mandatory is traced to the cases
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
  functional.py             F - 61 cases in 4 modules
  quality.py                Q - 20 cases in 5 quality areas
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
