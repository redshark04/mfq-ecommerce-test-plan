# -*- coding: utf-8 -*-
"""Document metadata, scope and global assumptions for the MFQ test plan."""

META = {
    "title": "MFQ Test Plan and Test Case Design",
    "subtitle": "E-Commerce System (Product / Inventory / Cart / Order / WMS-SC2P Sync)",
    "framework": "MFQ - Models / Functional / Quality",
    "version": "1.0",
    "date": "2026-10-13",
    "doc_id": "MFQ-ECOM-001",
}

OBJECTIVE_MD = """
Design a **risk-based test plan** for an e-commerce system using the **MFQ (Models - Functional - Quality)**
framework. The plan must show three things a reviewer can grade independently:

1. **M - Models.** Do we understand the system before testing it? Business flow, order state machine,
   inventory state model, external interaction model, and the *consistency boundaries* between them.
2. **F - Functional.** Does the functional coverage actually exercise those models: happy path, the
   inventory-synchronization contract, boundary/race conditions, and the API contract itself?
3. **Q - Quality.** Are the non-functional risks (performance, reliability, observability, security,
   recoverability) controlled by measurable targets, not adjectives?

The single most expensive defect class in this system is **inventory truth**: an oversell, a double
deduct, a lost deduct or a leaked reservation is either direct money loss or an incorrect promise shown to the customer.
Every layer below is therefore anchored to inventory consistency as the primary risk.
"""

SCOPE_IN = [
    "Product/SPU-SKU listing, price and sellable-quantity exposure to the storefront",
    "Cart validation and order submission (single-SKU, multi-SKU, multi-warehouse)",
    "Order lifecycle: place -> pay -> allocate -> ship (partial/split) -> sign -> return -> refund -> close",
    "Inventory states: available, reserved, deducted (sold), restored, frozen",
    "Bidirectional sync with WMS/SC2P: order push, allocation, ship notice, stock snapshot/stream, inbound receipt, QC result, return receipt",
    "Payment gateway callback handling and refund write-back",
    "Customer/admin APIs that mutate order or inventory state, plus their validation contracts",
]

SCOPE_OUT = [
    "Third-party WMS/SC2P internal logic (covered only through its external interface and fault-injection behavior)",
    "Payment gateway internals (simulated via sandbox plus callback replay)",
    "Logistics carrier routing and last-mile optimization",
    "Marketing/coupon engine business rules (touched only for price-tamper and concurrency checks)",
    "Native mobile client UI rendering beyond the API contract (only API-level plus one smoke journey)",
]

ASSUMPTIONS = [
    "WMS/SC2P is the **authoritative source of physical stock**; the platform owns the sellable (available) view and the reservation ledger.",
    "All external messages are **at-least-once**; correctness must come from idempotency, not from exactly-once delivery.",
    "Inventory is tracked per **(sku_id, warehouse_code)**; a SKU may be sellable from several warehouses and an order may be split across them.",
    "Callback and message processing is **asynchronous**; the storefront may observe states out of order and must never display a state that contradicts the ledger.",
    "Peak traffic is flash-sale shaped: a ~10-second burst of 20k+ QPS against a SKU with a few hundred units, i.e. a contention-heavy, low-inventory profile.",
    "Environment split: DEV (functional), TEST/STAGE (integration + fault injection + full MFQ run), PERF (isolated data set, production-like topology).",
]

RISK_TABLE = {
    "title": "Top product risks driving this plan (and the layer that controls each)",
    "columns": ["#", "Risk", "Impact", "Controlled by", "Blast radius"],
    "rows": [
        ["R1", "Oversell under flash-sale concurrency (available goes negative)", "Direct money loss, legal, brand", "F2 / F3 / Q1 / S4", "Whole SKU, all channels"],
        ["R2", "Lost or duplicated deduct between order and WMS", "Silent inventory drift, later oversell", "F2 / Q2 / S5", "Grows over days"],
        ["R3", "Order stuck in a non-terminal state (paid but never shipped)", "Refund cost, CS load, SLA breach", "F1 / F2 / Q2 / Q3", "Per order"],
        ["R4", "Duplicate or reordered callback double-applies a state change", "Double refund / double deduct", "F2 / F4", "Per order"],
        ["R5", "Stale WMS snapshot overwrites in-flight reservations", "Phantom stock or lost stock", "F2 / S4", "Whole warehouse"],
        ["R6", "Data drift with no repair path", "Manual firefighting, audit failure", "Q5 / S5", "System-wide"],
        ["R7", "PII leak via logs, callbacks or admin API", "Compliance and trust", "Q4", "Customer base"],
        ["R8", "Peak overload collapses order creation (cascading failure)", "Revenue stop during peak", "Q1 / Q2", "Site-wide"],
    ],
}
