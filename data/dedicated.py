# -*- coding: utf-8 -*-
"""Dedicated mandatory sections:
  S4 - Inventory Synchronization Consistency
  S5 - Exception Handling and Compensation Strategy
  S6 - Release Entry / Exit Criteria
"""

DEDICATED = [
    {
        "id": "S4",
        "kind": "section",
        "title": "Dedicated: Inventory Synchronization Consistency",
        "intro_md": "This section is the cross-layer view of the requirement that matters most. It restates the guarantee, lists the defect classes it must prevent, defines who wins each conflict, and states the exact evidence that proves the guarantee holds.",
        "tables": [
            {
                "title": "S4.1 The guarantee, stated as falsifiable claims",
                "columns": ["#", "Claim", "How it can be falsified", "Evidence of success"],
                "rows": [
                    ["G1", "The platform never authorizes a sale it cannot fulfil from sellable stock", "A successful order exists while available is negative, or oversell_count > 0", "Flash-sale case F3-03 and Q1-01 with exactly the configured quantity sold and zero negative samples"],
                    ["G2", "Every physical movement is reflected exactly once in the ledger", "A duplicate or replayed message changes a bucket twice, or a movement leaves no ledger row", "Idempotency suite F2-08..F2-10, F2-17, F3-12; ledger sum checks I3/I4"],
                    ["G3", "Platform and WMS converge to the same truth within one reconciliation cycle", "diff ratio above tolerance persists across two cycles", "Hourly diff job with a 24h zero-unexplained-diff report (F3-15, Q3-02)"],
                    ["G4", "No reservation can outlive its purpose", "A terminal order still holds reserved stock after the TTL", "Reservation TTL guard case F2-19 and invariant I6"],
                    ["G5", "Every divergence has an automated, audited repair path", "A drift is found with no job that can repair it, or a repair is done by a raw UPDATE", "Compensation sweep Q2-01 with reason-coded ADJUST entries"],
                ],
            },
            {
                "title": "S4.2 Defect classes this section must prevent (and the case that catches each)",
                "columns": ["Defect class", "Typical root cause", "Consequence", "Caught by"],
                "rows": [
                    ["Oversell / negative available", "Non-atomic check-then-update, cached availability used as authority, retry without idempotency", "Money loss, cancellation, legal exposure", "F3-02, F3-03, F3-04, Q1-01"],
                    ["Double deduct", "Redelivered DEDUCT or duplicate payment callback", "Phantom stock reduction, later oversell", "F2-09, F2-10"],
                    ["Lost deduct (paid but not deducted)", "Deduct call failed after payment succeeded, with no compensation", "Silent drift, later oversell", "F2-05, Q2-01"],
                    ["Leaked reservation", "Cancel/close path missed, or a job failed after the state change", "Sellable stock artificially reduced, lost sales", "F2-06, F2-19"],
                    ["Restored stock that was never returned", "Duplicate or pre-emptive RESTORE", "Oversell on the next sale", "F3-12, F2-17"],
                    ["Stale snapshot overwrite", "Bulk sync applied without a version guard", "Phantom stock or deleted live reservations", "F2-14, F2-15"],
                    ["Out-of-order state corruption", "Ship notice applied before allocation, or an old delta applied late", "Incorrect order status, unreconcilable quantities", "F2-11, F2-12, Q2-04"],
                    ["Silent sync stop", "Consumer died, backlog grew, nobody noticed", "Divergence grows for days", "Q3-01, Q3-02"],
                    ["Unrepaired drift", "No reconciliation, or a repair that cannot be replayed", "Audit failure, manual firefighting", "F2-18, F2-20, Q2-01"],
                ],
            },
            {
                "title": "S4.3 Conflict resolution rules (who wins, and why)",
                "columns": ["Conflict", "Winner", "Rule", "Losing side's role"],
                "rows": [
                    ["Physical stock: platform view vs WMS on_hand", "WMS", "WMS is the source of truth for on_hand", "The platform records the drift and raises an alert; it never silently rewrites live reservations"],
                    ["Sellability: cache vs ledger", "Ledger", "A reserve is authorized by the transactional ledger, never by a cached read", "The cache serves reads only and is marked stale when being rebuilt"],
                    ["Order state: state machine vs late callback", "State machine guard", "A terminal or later state rejects the older event, and the event is not lost, it is routed to a queue", "The callback is acknowledged to prevent a retry storm"],
                    ["Message ordering: two delta events for the same SKU", "Higher event_ts", "Monotonic per-SKU apply by event_ts", "The older event is discarded and counted in a metric"],
                    ["Snapshot vs in-flight reservation", "The in-flight reservation", "A bulk snapshot can never delete a live reservation", "The snapshot is applied to on_hand and the difference becomes a reported drift"],
                    ["Return restore: QC result vs RMA quantity", "QC result", "Only the received quantity with QC PASS is restored", "The rest stays sold and remains reconcilable"],
                ],
            },
            {
                "title": "S4.4 Test approach and exit thresholds for consistency",
                "columns": ["Activity", "Method", "Pass threshold"],
                "rows": [
                    ["Invariant assertion", "Assert I1, I2, I3, I5 before and after every inventory-touching test, plus continuous sampling during load tests", "Zero violations across the entire run"],
                    ["Fault injection", "The matrix in F2 (dropped responses, duplicates, reordering, stale versions, 500s, timeouts, MQ restarts)", "100% of injected faults handled per the declared policy; zero untriaged DLQ entries"],
                    ["Concurrency", "Synchronized-start contention runs, repeated at least 20 times per case", "Zero oversell and zero negative buckets in every iteration"],
                    ["Long soak", "8h at 1.2x peak with sync traffic included", "Diff ratio does not grow with time; no leaked reservations at the end of the soak"],
                    ["Reconciliation", "Run hourly and nightly jobs over all data produced during the test campaign", "diff ratio < 0.05% per warehouse; zero unexplained diffs; every auto-repair audited"],
                    ["Ledger audit", "Recompute every bucket from the ledger for the test data set", "100% of SKUs balance; any mismatch blocks the release"],
                ],
            },
        ],
        "mermaid": "flowchart TB\n  A[Order create] -->|atomic reserve| B{Ledger invariant OK?}\n  B -- no --> P0[Reject write + P0 page + freeze SKU]\n  B -- yes --> C[available->reserved]\n  C --> D[Payment callback]\n  D -->|idempotent deduct| E[reserved->sold, on_hand-1]\n  D -->|deduct failed| J[Compensation sweep detects paid-not-deducted]\n  J --> E\n  C -->|cancel or TTL| F[reserved->available]\n  E --> G[WMS ship notice]\n  G --> H[Outbound confirm reconciles sold vs shipped]\n  H --> I{Recon diff < tolerance?}\n  I -- no --> K[Classify A/B/C, ADJUST with reason, audit]\n  K --> I\n  I -- yes --> L[Consistency proven]",
        "children": [],
    },

    {
        "id": "S5",
        "kind": "section",
        "title": "Dedicated: Exception Handling and Compensation Strategy",
        "intro_md": "Two rules drive everything below. First, classify before you decide: a business rejection, a transient system fault and a data inconsistency need three different responses. Second, never leave a partial effect: if the second half of a two-step operation cannot complete, a named compensation job must own it within a stated SLA.",
        "tables": [
            {
                "title": "S5.1 Exception taxonomy and handling policy",
                "columns": ["Class", "Examples", "Detection", "Handling policy", "Retry?", "User-visible outcome"],
                "rows": [
                    ["Business rejection", "Insufficient stock, off-shelf SKU, illegal state, quantity limit, RMA outside the return window", "Validation and state guards at the boundary", "Reject with the documented code; change nothing", "No (unless a documented transition happens, e.g. stock replenishment)", "Clear, specific message; no order created"],
                    ["Transient system fault", "Timeout, connection reset, 5xx from a dependency, throttle", "Client error classification plus the circuit breaker", "Retry with bounded exponential backoff and jitter on idempotent operations", "Yes, max 3", "Slight delay, then success or a retryable message"],
                    ["Permanent external rejection", "WMS contract violation, schema error, unknown version, illegal tracking number", "Schema validation and DLQ routing", "Route to the DLQ with a reason, alert, fix and replay with approval", "No", "Stuck-order alert; ops intervene with a runbook"],
                    ["Data inconsistency", "Ledger imbalance, invariant violation, unexplained diff", "Reconciliation jobs, invariant assertions", "Reject the offending write, freeze the affected SKU, classify A/B/C and repair with an audited ADJUST", "No", "SKU temporarily unsellable rather than oversold"],
                    ["Money-related exception", "Amount mismatch, duplicate refund, callback for a closed order, successful refund with no order", "Callback validation plus the nightly three-way recon", "Never auto-revive an order; route to the money-exception queue with a P0/P1 alert and a named owner", "No", "Manual resolution with an audit record"],
                    ["Human/ops exception", "Manual adjustment, emergency recall, damaged goods", "Ops tooling with approval workflow", "Requires role permission, reason code and a ticket reference; never a raw database write", "No", "Auditable adjustment"],
                ],
            },
            {
                "title": "S5.2 Compensation job catalog (each drift class has exactly one owner)",
                "columns": ["Job", "Trigger / scope", "Action", "Idempotency key", "SLA", "Escalation"],
                "rows": [
                    ["compPaidNotDeducted", "Paid orders with no DEDUCT ledger entry", "Apply DEDUCT once, then continue normal fulfillment", "pay_no + sku_id + DEDUCT", "15min", "P1 if the count exceeds 100"],
                    ["compShippedNotDeducted", "WMS outbound confirm with no matching platform deduct", "Apply DEDUCT and record the reconciliation batch", "so_id + sku_id + SHIP_DEDUCT", "30min", "P1"],
                    ["compReleaseStaleReservation", "Reservations whose order is terminal or past TTL", "Apply RELEASE with reason RESERVATION_TTL", "order_no + sku_id + RELEASE", "Hourly", "P2"],
                    ["compRestoreReturn", "Return received with QC PASS and no RESTORE", "Apply RESTORE once", "rma_no + sku_id + RESTORE", "30min", "P1"],
                    ["compReplayLostCallback", "Order PAID with an unresolved payment record, or a callback rejected for a transient reason", "Replay the callback through the idempotent path", "pay_no + REPLAY", "15min", "P1"],
                    ["compReconAdjust", "Diff ratio above tolerance after classification", "Apply ADJUST with reason RECON_AUTO and a recon_batch_id", "recon_batch_id + sku_id + seq", "1h", "P0 if the ratio exceeds 0.5%"],
                    ["compDlqReplay", "DLQ entries with a fixed root cause", "Replay with approval; verify the effect was applied exactly once", "original message_id", "4h", "P1 if the DLQ exceeds 100"],
                ],
            },
            {
                "title": "S5.3 Pattern selection per boundary",
                "columns": ["Boundary", "Pattern", "Why this pattern", "Failure handling"],
                "rows": [
                    ["Order create -> inventory reserve", "Local transaction (atomic single-resource)", "Both live in the platform inventory service, so no distributed transaction is needed", "On failure, nothing is persisted; the caller receives a retryable or business code"],
                    ["Payment -> order -> inventory", "Idempotent event with a unique business key (pay_no)", "The gateway cannot participate in a distributed transaction", "Duplicate callbacks are no-ops; a lost callback is recovered by compReplayLostCallback"],
                    ["Order -> WMS/SC2P fulfillment", "Saga with forward recovery (retry) plus a compensating cancel", "The warehouse cannot roll back a physical pick; forward progress is the only safe direction", "Retry the SO push; if a cancel is needed, send CancelSO and reconcile the ledger"],
                    ["Return -> refund", "Saga with compensation in the reverse order (restore stock, then refund)", "Stock and money must not diverge; stock restore is reversible, the refund is not", "If the refund fails after the restore, retry the refund and alert; never re-deduct silently"],
                    ["Bulk stock sync", "Version-guarded idempotent apply with a reconciliation safety net", "The sync is a mass overwrite, so version control plus recon is the only safe combination", "Apply only newer versions; report the remainder as drift"],
                ],
            },
            {
                "title": "S5.4 Manual intervention playbook (what the runbook must contain)",
                "columns": ["Situation", "First action", "Never do", "Evidence to produce"],
                "rows": [
                    ["Oversell on a live SKU", "Freeze the SKU from sale, stop the offending job, identify affected orders, notify CS", "Do not delete orders or edit quantities directly", "Incident timeline, affected order list, repair batch id, post-mortem"],
                    ["Unbalanced ledger for a SKU", "Freeze the SKU, rebuild the buckets from the ledger, compare with WMS", "Do not hand-edit the on_hand column", "Rebuild report, before/after values, approval record"],
                    ["Money exception (duplicate refund / orphan payment)", "Route to the money queue with a P0 alert, block automated retries", "Do not auto-revive a closed order", "Payment reconciliation report, refund ledger, resolution note"],
                    ["WMS contract break", "Stop the consumer, preserve the DLQ, fix the contract or the mapper, replay with approval", "Do not drop DLQ messages to clear the alert", "DLQ reason histogram, replay log, verification that no duplicate effect occurred"],
                ],
            },
        ],
        "children": [],
    },

    {
        "id": "S6",
        "kind": "section",
        "title": "Dedicated: Release Entry and Exit Criteria",
        "intro_md": "The criteria turn the release decision into a checklist. Entry criteria protect the test team's time; exit criteria protect production. Any exit criterion that fails blocks the release unless a named approver signs a documented exception with an expiry.",
        "tables": [
            {
                "title": "S6.1 Entry criteria (all must hold before the test round starts)",
                "columns": ["#", "Criterion", "Evidence"],
                "rows": [
                    ["EN1", "Requirements and design frozen; the MFQ models (M1-M5) reviewed and approved by the system owner", "Signed design doc plus a review record referencing the model versions"],
                    ["EN2", "External contracts frozen: the OpenAPI/JSON Schema for messages E1, E8 and E9, the MQ schema for E2-E7, and the shared error-code dictionary", "Published contract artefacts; contract tests green in the pipeline"],
                    ["EN3", "Test environment deployed at production-like topology, including the WMS/SC2P mock with a fault-injection switch per message type", "Environment readiness checklist; a smoke run proving each injection works"],
                    ["EN4", "Observability live in the test environment: metrics, dashboards and alerts deployed with production thresholds", "Dashboard link plus one successfully fired test alert"],
                    ["EN5", "Test data prepared and resettable: SKU/warehouse/stock fixtures, user accounts, payment sandbox, and a one-command data reset", "Data provision record; reset script executed successfully twice"],
                    ["EN6", "Entry smoke passes: order -> pay -> allocate -> ship -> sign -> return -> refund end-to-end", "Smoke report with timestamps"],
                    ["EN7", "Performance baseline recorded and the load model reviewed against the projected peak", "Baseline report; load script version pinned"],
                    ["EN8", "Rollback plan and feature flags defined; the predecessor image is available", "Release checklist item signed by the release owner"],
                    ["EN9", "Defect severity definitions and the triage cadence agreed with the stakeholders", "Agreed severity matrix and triage meeting invite"],
                ],
            },
            {
                "title": "S6.2 Exit criteria (all must hold before the release is approved)",
                "columns": ["#", "Criterion", "Threshold", "Blocking?"],
                "rows": [
                    ["X1", "P0 case execution", "100% executed and 100% passed", "Yes"],
                    ["X2", "P1 case execution", ">= 98% passed; every failure either fixed or explicitly deferred by the release owner", "Yes"],
                    ["X3", "P2 cases", "Executed or explicitly triaged with an owner and a due date", "No"],
                    ["X4", "Open defects", "Zero open Sev1/Sev2; Sev3 within the agreed cap with documented workarounds; no open defect touching the ledger invariant", "Yes"],
                    ["X5", "Traceability", "100% of the mandatory requirements (MFQ must-include list) traced to at least one executed case; the traceability matrix is generated, not hand-written", "Yes"],
                    ["X6", "Inventory consistency", "oversell_count = 0; zero negative buckets; diff ratio < 0.05% per warehouse after a 24h continuous reconciliation; all ledger invariants (I1-I6) hold for the whole test data set", "Yes"],
                    ["X7", "Idempotency and ordering", "100% pass of the duplicate/reorder/fault-injection suites; zero untriaged DLQ entries", "Yes"],
                    ["X8", "Performance", "All targets in Q1 met at 1.5x peak; the 8h soak shows no leak and a stable diff ratio; zero oversell at the breakpoint", "Yes"],
                    ["X9", "Reliability", "Every chaos scenario CH1-CH8 executed with the declared outcome; all seeded drifts repaired within SLA by the compensation jobs", "Yes"],
                    ["X10", "Observability", "Every alert in the Q3 catalog verified to fire; the dashboard set complete; no PII in logs (CI scan green)", "Yes"],
                    ["X11", "Security", "No open high/critical finding; masking verified; callback authenticity tests pass; the dependency scan is clean", "Yes"],
                    ["X12", "Recoverability", "Backup restore and failover drills D1/D2 completed within RTO/RPO; the repair runbook validated by someone other than its author", "Yes"],
                    ["X13", "Regression", "The automated regression suite passes at >= 95%; no regression in adjacent modules (payment, promotion, logistics)", "Yes"],
                    ["X14", "Documentation", "Test summary report published, known-issues list published, release notes carry the residual-risk statement", "Yes"],
                ],
            },
            {
                "title": "S6.3 Residual-risk acceptance (what is knowingly deferred)",
                "columns": ["Deferred item", "Reason", "Mitigation", "Approver"],
                "rows": [
                    ["Exhaustive payment-channel matrix", "Only the primary channel carries the volume this iteration", "Channels share the same callback contract, covered by F4-07; the second channel is covered in the following iteration", "Product owner"],
                    ["Long-duration (72h) soak", "Time-boxed release window", "8h soak plus hourly reconciliation evidence", "QA lead"],
                    ["Multi-region/DR switch", "Not part of the current topology", "Failover drill D1 covers the single-region primary/replica case", "Architect"],
                    ["UI-level accessibility of the checkout journey", "Out of the API-focused scope of this plan", "Tracked as a separate workstream", "Product owner"],
                ],
            },
        ],
        "children": [],
    },
]
