# -*- coding: utf-8 -*-
"""M - Models layer: business flow, order state machine, inventory state model,
external interaction model, consistency boundaries.

Node schema (shared by every layer, consumed by scripts/build.py):
  id, title, priority(P0/P1/P2|None), kind, intro_md, bullets[],
  tables[{title, columns[], rows[][]}], mermaid(str|None), refs[], children[]
"""

ORDER_STATES = [
    "REJECTED", "PENDING_PAYMENT", "CANCELED", "CLOSED", "PAID", "TO_SHIP",
    "PARTIAL_SHIPPED", "SHIPPED", "SIGNED", "RETURNING", "RETURNED",
    "REFUNDING", "REFUNDED", "COMPLETED",
]

MODELS = [
    {
        "id": "M1",
        "kind": "model",
        "title": "End-to-End Business Flow Model",
        "intro_md": "The flow crosses three ownership boundaries: **storefront** (order intent and payment), **platform inventory** (reservations and the sellable view) and **WMS/SC2P** (physical stock and outbound execution). Every stage is listed with the inventory effect it must produce, so each stage becomes a directly testable assertion rather than a narrative.",
        "tables": [
            {
                "title": "E2E stages: actor, system action, inventory effect, consistency contract",
                "columns": ["#", "Stage", "Trigger / actor", "System actions", "Inventory effect", "Consistency contract"],
                "rows": [
                    ["1", "Browse / quote", "Shopper reads SKU", "Read SPU-SKU, price, sellable qty", "none", "Read-your-writes on available qty"],
                    ["2", "Add to cart", "Shopper", "Validate on-shelf status, re-price", "none", "Price and qty revalidated again at submit"],
                    ["3", "Submit order", "Shopper", "Create order, freeze price, reserve stock, create payment intent", "available -1, reserved +1 per SKU", "STRONG: no oversell, no negative available"],
                    ["4", "Pay", "Shopper + payment gateway", "Create pay record, receive async callback, mark paid", "reserved -1, sold +1, on_hand -1", "STRONG + idempotent on pay_no"],
                    ["5", "Allocate / fulfil", "Platform -> WMS/SC2P", "Push sales order (SO), receive allocation ACK, receive pick/pack status", "none on platform; WMS reserves physically", "EVENTUAL, at-least-once, idempotent by SO id"],
                    ["6", "Ship", "WMS/SC2P -> platform", "Receive ship notice (packages, tracking no, SKU split)", "none (deduct already applied at pay)", "EVENTUAL; must reconcile platform sold vs WMS outbound"],
                    ["7", "Deliver / sign", "Carrier -> platform", "Update logistics, confirm receipt, open return window", "none", "EVENTUAL"],
                    ["8", "Return", "Shopper + WMS", "Create RMA, receive goods, QC", "on QC pass: on_hand +1, available +1, sold -1", "EVENTUAL + compensating"],
                    ["9", "Refund", "Platform -> gateway", "Refund request, gateway callback", "none", "STRONG + idempotent on refund_no"],
                    ["10", "Close", "Scheduler", "Auto-sign (15d), auto-complete (return window), archive", "release any leftover reservation on abnormal close", "EVENTUAL; must never close with a live reservation"],
                ],
            },
        ],
        "mermaid": "flowchart LR\n  A[Browse / Quote] --> B[Add to Cart]\n  B --> C[Submit Order]\n  C -->|reserve available->reserved| D[PENDING_PAYMENT]\n  D -->|pay callback| E[PAID: reserved->sold]\n  D -->|30min timeout| X1[CLOSED: release]\n  D -->|user cancel| X2[CANCELED: release]\n  E --> F[Push SO to WMS]\n  F --> G[TO_SHIP]\n  G -->|partial| H[PARTIAL_SHIPPED]\n  G -->|all| I[SHIPPED]\n  H --> I\n  I -->|user or 15d auto| J[SIGNED]\n  J -->|RMA + QC pass| K[RETURNED: restore]\n  J -->|window expiry| L[COMPLETED]\n  K --> M[REFUNDED]",
        "children": [
            {"id": "M1.1", "kind": "model", "title": "Stage-level failure modes (must be covered by F cases)",
             "bullets": [
                 "Stage 3 fails: reserve times out or WMS says insufficient -> order must be REJECTED, no ledger entry left behind.",
                 "Stage 4 fails after money moved: payment callback lost or gateway error -> order must not stay PENDING_PAYMENT silently; reconciliation job must find and repair it.",
                 "Stage 5 fails: SO push rejected or ACK lost -> order must not be double-pushed; retry must be idempotent by SO id.",
                 "Stage 6 out-of-order: ship notice arriving before allocation ACK must not corrupt state.",
                 "Stage 8 partial: only the returned quantity may be restored; the rest stays sold.",
                 "Stage 10 abnormal close: any non-terminal order closed by a job must release its reservation first.",
             ]},
        ],
    },

    {
        "id": "M2",
        "kind": "model",
        "title": "Order State Machine",
        "intro_md": "14 states, five of them terminal, and an explicit guard (or an explicit refusal) on every transition. Each transition lists a guard that is enforced before the transition runs. An omitted guard is how a refund gets issued against an already-shipped order, so the guards act as test oracles.",
        "tables": [
            {
                "title": "States",
                "columns": ["State", "Meaning (observable)", "Terminal"],
                "rows": [
                    ["REJECTED", "Order creation attempted but inventory reservation failed", "yes"],
                    ["PENDING_PAYMENT", "Order exists, price frozen, stock reserved, awaiting payment", "no"],
                    ["CANCELED", "Shopper canceled before payment, reservation released", "yes"],
                    ["CLOSED", "Unpaid order auto-closed by timeout job, reservation released", "yes"],
                    ["PAID", "Payment callback accepted, stock deducted (reserved -> sold)", "no"],
                    ["TO_SHIP", "Sales order acknowledged by WMS/SC2P as allocatable", "no"],
                    ["PARTIAL_SHIPPED", "Some SKUs or packages of the order shipped", "no"],
                    ["SHIPPED", "All order lines shipped", "no"],
                    ["SIGNED", "All packages signed for, return window opened", "no"],
                    ["RETURNING", "RMA created, goods in transit back to warehouse", "no"],
                    ["RETURNED", "Goods received and QC passed, stock restored", "no"],
                    ["REFUNDING", "Refund in flight to the payment channel", "no"],
                    ["REFUNDED", "Refund confirmed by gateway callback", "yes"],
                    ["COMPLETED", "Return window expired with no RMA", "yes"],
                ],
            },
            {
                "title": "Transitions: event, guard, side effect",
                "columns": ["From", "Event", "Guard / transition condition", "To", "Side effects (inventory, external)"],
                "rows": [
                    ["(new)", "createOrder", "Cart valid AND reserve(available>=qty) succeeds for all lines", "PENDING_PAYMENT", "ledger RESERVE per SKU; create payment intent"],
                    ["(new)", "createOrder", "reserve fails (insufficient / timeout)", "REJECTED", "no ledger entry persisted; metric reserve_fail++"],
                    ["PENDING_PAYMENT", "paySuccess (gateway callback)", "signature valid AND amount == order amount AND pay_no unseen", "PAID", "ledger DEDUCT per SKU (reserved->sold, on_hand-1); emit OrderPaid"],
                    ["PENDING_PAYMENT", "paySuccess (duplicate callback)", "same pay_no already applied", "PENDING_PAYMENT unchanged", "no-op, return success (idempotent), metric duplicate_callback++"],
                    ["PENDING_PAYMENT", "payFailed", "gateway returns failure", "PENDING_PAYMENT unchanged", "no ledger change; allow retry within timeout"],
                    ["PENDING_PAYMENT", "paymentTimeoutJob", "now - created_at >= 30min AND not paid", "CLOSED", "ledger RELEASE per SKU; close payment intent"],
                    ["PENDING_PAYMENT", "userCancel", "not paid", "CANCELED", "ledger RELEASE per SKU"],
                    ["PAID", "wmsAllocationAck", "SO accepted for at least one line", "TO_SHIP", "persist SO id, warehouse allocation"],
                    ["PAID", "refundBeforeShip", "not yet shipped AND rule allows", "REFUNDING", "compensating ledger per policy (see S5)"],
                    ["TO_SHIP", "shipNotice (partial)", "shipped qty < ordered qty", "PARTIAL_SHIPPED", "record packages, tracking no; sold stays"],
                    ["TO_SHIP", "shipNotice (full)", "shipped qty == ordered qty", "SHIPPED", "record packages; trigger auto-sign timer"],
                    ["PARTIAL_SHIPPED", "shipNotice (remaining)", "cumulative shipped qty == ordered qty", "SHIPPED", "record packages; trigger auto-sign timer"],
                    ["SHIPPED", "userConfirmReceipt", "logistics status delivered", "SIGNED", "open return window (7d for restockable)"],
                    ["SHIPPED", "autoSignJob", "now - shipped_at >= 15d AND logistics delivered", "SIGNED", "open return window"],
                    ["SIGNED", "createRMA", "within window AND SKU is returnable", "RETURNING", "create RMA, notify WMS"],
                    ["RETURNING", "wmsReturnReceived + QCPass", "qty received matches RMA", "RETURNED", "ledger RESTORE (on_hand+1, available+1, sold-1)"],
                    ["RETURNING", "QCFail", "goods not resellable", "SIGNED (unchanged, RMA closed)", "no RESTORE; ledger note with reason QC_FAIL"],
                    ["RETURNED", "refundRequested", "refund accepted by the gateway and no dispute is open", "REFUNDING", "create the refund record with reason RETURN_REFUND"],
                    ["RETURNED", "refundSuccess", "gateway confirms the refund (synchronous, or after REFUNDING)", "REFUNDED", "emit RefundDone; order terminal"],
                    ["SIGNED", "returnWindowExpiryJob", "no RMA within window", "COMPLETED", "none"],
                    ["CANCELED / CLOSED / REJECTED / REFUNDED / COMPLETED", "any", "state is terminal", "unchanged", "reject the event, return ORDER_STATE_ILLEGAL"],
                ],
            },
            {
                "title": "Illegal transitions that MUST be rejected (negative oracles)",
                "columns": ["Attempted transition", "Expected result"],
                "rows": [
                    ["SHIPPED -> paySuccess", "ORDER_STATE_ILLEGAL, no ledger change"],
                    ["CLOSED -> paySuccess", "ORDER_STATE_ILLEGAL; payment must be routed to auto-refund instead of reviving the order"],
                    ["SIGNED -> shipNotice again", "idempotent no-op, no second deduct"],
                    ["RETURNED -> RESTORE twice (duplicate return receipt)", "second RESTORE rejected as duplicate, ledger unchanged"],
                    ["Any transition on an order whose ledger is unbalanced", "blocked by invariant check; raises data-consistency alert"],
                ],
            },
        ],
        "mermaid": "stateDiagram-v2\n  [*] --> PENDING_PAYMENT: createOrder + reserve OK\n  [*] --> REJECTED: reserve failed\n  PENDING_PAYMENT --> PAID: paySuccess (idempotent)\n  PENDING_PAYMENT --> CLOSED: 30min timeout\n  PENDING_PAYMENT --> CANCELED: user cancel\n  PAID --> TO_SHIP: wmsAllocationAck\n  PAID --> REFUNDING: refund before ship\n  TO_SHIP --> PARTIAL_SHIPPED: partial ship notice\n  TO_SHIP --> SHIPPED: full ship notice\n  PARTIAL_SHIPPED --> SHIPPED: remaining shipped\n  SHIPPED --> SIGNED: user sign or 15d auto\n  SIGNED --> RETURNING: RMA created\n  SIGNED --> COMPLETED: window expiry\n  RETURNING --> RETURNED: received + QC pass (restore)\n  RETURNING --> SIGNED: QC fail (no restore)\n  RETURNED --> REFUNDING: refund requested\n  REFUNDING --> REFUNDED: gateway confirms\n  RETURNED --> REFUNDED: refund confirmed synchronously\n  REFUNDED --> [*]\n  COMPLETED --> [*]\n  CANCELED --> [*]\n  CLOSED --> [*]\n  REJECTED --> [*]",
        "children": [],
    },

    {
        "id": "M3",
        "kind": "model",
        "title": "Inventory State Model",
        "intro_md": "Four buckets (on_hand, available, reserved, frozen) plus a cumulative sold counter, six invariants and one append-only ledger. The invariants are what make inventory testable: every case asserts them **before and after**, and the reconciliation jobs assert them continuously.",
        "tables": [
            {
                "title": "Quantity model (granularity: sku_id x warehouse_code)",
                "columns": ["Field", "Meaning", "Source of truth", "Changed by"],
                "rows": [
                    ["on_hand", "Physically present stock", "WMS/SC2P", "Inbound receipt, outbound confirm, return receipt, ADJUST"],
                    ["available", "Sellable right now (exposed to storefront)", "Platform inventory", "RESERVE, RELEASE, RESTORE, INBOUND, FREEZE"],
                    ["reserved", "Held by non-terminal unpaid/pending orders (has a TTL)", "Platform inventory", "RESERVE, RELEASE, DEDUCT"],
                    ["frozen", "Blocked from sale (QC hold, damage, channel lock)", "Platform + WMS", "FREEZE, UNFREEZE, ADJUST"],
                    ["sold", "Cumulative deducted quantity (ledger concept, not a bucket)", "Platform inventory", "DEDUCT, RESTORE"],
                    ["safety_stock", "Configured buffer never exposed to sale", "Config", "Manual config change"],
                ],
            },
            {
                "title": "Core invariant (asserted by every inventory test case and by the reconciliation job)",
                "columns": ["#", "Invariant", "Violation symptom"],
                "rows": [
                    ["I1", "available + reserved + frozen == on_hand - safety_stock", "Oversell (negative available) or phantom stock"],
                    ["I2", "available >= 0 and reserved >= 0 and frozen >= 0", "Negative bucket, immediate P0"],
                    ["I3", "sum(ledger.qty for type=RESERVE - type=RELEASE - type=DEDUCT) == reserved", "Leaked or lost reservation"],
                    ["I4", "on_hand == snapshot_on_hand + sum(RESTORE + INBOUND - DEDUCT - ADJUST_out)", "Platform and WMS disagree on physical stock"],
                    ["I5", "every mutation has exactly one ledger entry with a unique idempotency key", "Double apply on message replay"],
                    ["I6", "every reservation is resolvable: it ends in DEDUCT or RELEASE within its TTL", "Stuck order / permanently frozen stock"],
                ],
            },
            {
                "title": "Ledger entry types and their transition",
                "columns": ["Type", "From -> To", "Trigger", "Idempotency key", "Reversible"],
                "rows": [
                    ["RESERVE", "available -> reserved", "Order create", "order_no + sku_id + RESERVE", "yes (RELEASE)"],
                    ["RELEASE", "reserved -> available", "Cancel / timeout close / abnormal close", "order_no + sku_id + RELEASE", "n/a (terminal for that reservation)"],
                    ["DEDUCT", "reserved -> sold, on_hand -1", "Payment success (WMS outbound confirm reconciles it)", "pay_no + sku_id + DEDUCT", "yes (RESTORE)"],
                    ["RESTORE", "sold -> available, on_hand +1", "Return received + QC pass", "rma_no + sku_id + RESTORE", "no (needs new RMA)"],
                    ["FREEZE / UNFREEZE", "available <-> frozen", "Ops action, QC hold, channel lock", "ticket_id + sku_id", "yes"],
                    ["INBOUND", "on_hand +1, available +1", "WMS inbound receipt", "receipt_no + sku_id", "no (ADJUST to correct)"],
                    ["ADJUST", "any -> any (with reason code)", "Reconciliation job or manual repair", "recon_batch_id + sku_id + seq", "no; immutable audit entry"],
                ],
            },
            {
                "title": "Cross-channel and multi-warehouse rules",
                "columns": ["Rule", "Description", "Test implication"],
                "rows": [
                    ["Per-warehouse allocation", "An order line may be allocated from any warehouse holding stock; a partial allocation splits the line", "Split shipment cases must assert per-warehouse ledger balance, not just the SKU total"],
                    ["Channel ring-fencing", "Stock may be reserved per sales channel (e.g. shop vs live-stream)", "A channel must not be able to consume another channel's ring-fenced stock"],
                    ["Reservation TTL ladder", "Unpaid 30min -> release; paid 24h unallocated -> escalate to stuck-order alert", "Timeout boundary cases must hit the exact boundary instant"],
                    ["Safety stock", "available never exposes the buffer", "Zero-stock cases must check available hits 0 while on_hand may still be > 0"],
                ],
            },
        ],
        "mermaid": "flowchart LR\n  subgraph Buckets\n    AV[available]\n    RS[reserved]\n    SO[sold]\n    FR[frozen]\n    OH[on_hand]\n  end\n  NEW((new stock)) -->|INBOUND| AV\n  AV -->|RESERVE| RS\n  RS -->|RELEASE| AV\n  RS -->|DEDUCT| SO\n  SO -->|RESTORE + QC pass| AV\n  AV -->|FREEZE| FR\n  FR -->|UNFREEZE| AV\n  SO -.->|outbound confirm from WMS| OH\n  AV -.->|invariant: available+reserved+frozen = on_hand| OH\n  ADJ[ADJUST (recon / manual, reason-coded)] -.-> AV\n  ADJ -.-> OH",
        "children": [],
    },

    {
        "id": "M4",
        "kind": "model",
        "title": "External Interaction Model (Storefront <-> WMS/SC2P)",
        "intro_md": "Nine external messages, each with a direction, a transport, an idempotency key and a declared failure policy. Anything not declared here is undeclared behavior and belongs in the exception taxonomy (S5).",
        "tables": [
            {
                "title": "Message catalog",
                "columns": ["#", "Direction", "Message", "Transport", "Key fields", "Idempotency key", "Failure policy"],
                "rows": [
                    ["E1", "Platform -> WMS", "SalesOrderCreate (SO push)", "HTTPS POST (sync ACK) + MQ retry", "so_id, order_no, lines[sku_id, qty], warehouse_hint, ship_to_hash", "so_id", "Retry x3 exp backoff -> DLQ; order stays PAID with stuck_order alert"],
                    ["E2", "WMS -> Platform", "AllocationAck", "MQ", "so_id, allocated_lines[], warehouse_code, shortage_lines[]", "so_id + ack_seq", "Idempotent apply; shortage triggers partial-allocation branch"],
                    ["E3", "WMS -> Platform", "ShipNotice", "MQ", "so_id, packages[], tracking_no, line_qty_shipped, shipped_at", "so_id + package_id", "Dedup per package; unknown so_id -> park + alert"],
                    ["E4", "WMS -> Platform", "StockSnapshot (bulk)", "MQ batch / SFTP nightly", "sku_id, warehouse_code, on_hand, version, snapshot_ts", "warehouse_code + version", "Version-guarded apply; stale version ignored (never overwrites newer in-flight state)"],
                    ["E5", "WMS -> Platform", "StockChangeEvent (delta)", "MQ", "sku_id, warehouse_code, delta, reason, event_ts", "event_id", "Out-of-order tolerance: apply by event_ts, drop older than last applied ts per SKU"],
                    ["E6", "WMS -> Platform", "InboundReceipt", "MQ", "receipt_no, sku_id, qty, warehouse_code", "receipt_no", "Idempotent; adds to on_hand and available"],
                    ["E7", "WMS -> Platform", "ReturnReceived + QCResult", "MQ", "rma_no, sku_id, qty, qc_result(PASS/FAIL), warehouse_code", "rma_no + qc_seq", "PASS -> RESTORE; FAIL -> no restore, reason logged"],
                    ["E8", "Platform -> WMS", "CancelSO / DeliveryAddressChange", "HTTPS POST", "so_id, reason_code / new_address_version", "so_id + action + version", "Reject if WMS already shipped; platform keeps SHIPPED state"],
                    ["E9", "Gateway -> Platform", "PaymentCallback / RefundCallback", "HTTPS POST (public endpoint)", "order_no, pay_no, amount, status, sign, ts, nonce", "pay_no / refund_no", "Verify sign + ts window + nonce; reject on mismatch, never mutate state"],
                ],
            },
        ],
        "mermaid": "sequenceDiagram\n  participant SF as Storefront\n  participant INV as Platform Inventory\n  participant OMS as Order Service\n  participant PG as Payment Gateway\n  participant WMS as WMS/SC2P\n  SF->>OMS: createOrder\n  OMS->>INV: reserve(sku,qty)\n  INV-->>OMS: reserved (ledger RESERVE)\n  OMS-->>SF: PENDING_PAYMENT\n  SF->>PG: pay\n  PG->>OMS: PaymentCallback (pay_no, sign)\n  OMS->>INV: deduct(sku,qty)\n  INV-->>OMS: sold (ledger DEDUCT)\n  OMS->>WMS: E1 SalesOrderCreate\n  WMS-->>OMS: E2 AllocationAck\n  WMS-->>OMS: E3 ShipNotice\n  OMS-->>SF: SHIPPED -> SIGNED\n  WMS-->>INV: E4 StockSnapshot / E5 StockChangeEvent\n  INV->>INV: reconcile against ledger (tolerance check)",
        "children": [
            {"id": "M4.1", "kind": "model", "title": "Interface contracts that must be frozen before test execution",
             "bullets": [
                 "Signed OpenAPI/JSON-Schema for E1, E8 and E9, published to the test team and validated by contract tests.",
                 "Message schema version field on every MQ message, with a documented compatibility rule (additive only within a major version).",
                 "Published error-code dictionary shared by platform, WMS and gateway, including retryable vs non-retryable classification.",
                 "Clock-skew tolerance declared (+/-5min) and enforced identically on both sides.",
                 "A mock WMS/SC2P with a fault-injection switch per message type, so every E-case can be driven deterministically.",
             ]},
        ],
    },

    {
        "id": "M5",
        "kind": "model",
        "title": "Consistency Boundaries and Reconciliation Points",
        "intro_md": "The system cannot make every boundary strongly consistent, and trying to do so is what produces overselling defects. Each boundary is assigned a mode, an authoritative side, a conflict rule and a reconciliation cadence.",
        "tables": [
            {
                "title": "Consistency boundaries",
                "columns": ["#", "Boundary", "Mode", "Authoritative side", "Mechanism", "Conflict rule"],
                "rows": [
                    ["C1", "Order create <-> inventory reserve", "STRONG", "Platform inventory", "Single transaction on the inventory row (SELECT ... FOR UPDATE / Redis-Lua atomic decrement with DB fallback)", "Second concurrent request loses; available never < 0"],
                    ["C2", "Payment callback <-> order state", "STRONG", "Platform order service", "Unique index on pay_no + state guard in the same transaction", "Duplicate callback is a no-op; state machine guard wins over the callback"],
                    ["C3", "Order <-> WMS sales order push (E1/E2)", "EVENTUAL", "Platform owns so_id", "At-least-once delivery (synchronous ACK with MQ-backed retry) + idempotent SO apply keyed on so_id", "WMS allocation is authoritative for warehouse/shortage; platform never re-pushes a live SO"],
                    ["C4", "WMS ship notice <-> order status (E3)", "EVENTUAL", "WMS", "Dedup on so_id + package_id", "Platform must accept shipment even if the allocation ACK was lost (out-of-order tolerance)"],
                    ["C5", "WMS stock <-> platform available (E4/E5)", "EVENTUAL", "WMS for on_hand, platform for available", "Version-guarded snapshot apply; delta events ordered by event_ts", "WMS on_hand always wins; an in-flight reservation is never canceled by a snapshot, the drift is reported instead"],
                    ["C6", "Return receipt <-> stock restore (E7)", "EVENTUAL", "WMS QC result", "Idempotent RESTORE keyed on rma_no + qc_seq", "restore only on QC PASS and only for the received quantity"],
                    ["C7", "Refund <-> order closure", "STRONG", "Platform", "Unique index on refund_no + state guard", "refund callback for an unknown/closed order goes to manual queue, never auto-revives the order"],
                ],
            },
            {
                "title": "Reconciliation points and cadence",
                "columns": ["Cadence", "Reconciliation job", "Scope", "Tolerance", "Action on breach"],
                "rows": [
                    ["Real time", "Reservation TTL guard", "reserved buckets older than TTL", "0 breaches", "auto RELEASE + ledger entry + metric"],
                    ["Real time", "Invariant assertion (I1/I2/I5) on every write", "all mutations", "0 violations", "reject the write; page P0"],
                    ["Every 5 min", "DLQ sweep and replay", "dead-letter queue", "DLQ == 0 after replay", "alert if DLQ > 0; manual approval above 100 messages"],
                    ["Every 5 min", "Stuck-order detector", "orders non-terminal longer than stage SLA", "< 50 stuck orders", "alert; auto-compensate where a safe rule exists"],
                    ["Hourly", "Inventory diff job: platform (available+reserved+frozen) vs WMS (on_hand - safety_stock)", "all sku x warehouse", "diff ratio < 0.05% per warehouse", "classify A/B/C and auto-repair A, page on ratio breach"],
                    ["Nightly", "Full stock snapshot reconciliation (E4) + three-way order/payment/shipment recon", "all SKUs; yesterday's orders", "0 unexplained diffs", "generate ADJUST with recon_batch_id; publish audit report"],
                    ["Nightly", "Ledger balance recon (I3/I4/I6)", "whole ledger", "0 unbalanced SKUs", "freeze the SKU from sale + P0 alert until repaired"],
                    ["Weekly", "Audit report + drift trend", "all reconciliations", "trend not degrading", "review and tune thresholds"],
                ],
            },
        ],
        "children": [
            {"id": "M5.1", "kind": "model", "title": "Why these modes (design rationale to defend in review)",
             "bullets": [
                 "C1 is strong because an oversell is unrecoverable: you cannot un-sell 200 units of a 100-unit SKU.",
                 "C4 is eventual and must tolerate the lost-ACK case, because the physical shipment already happened; refusing the ship notice corrupts customer-visible reality.",
                 "C5 lets WMS win on on_hand but never lets a snapshot silently delete a live reservation, otherwise a bulk sync becomes an oversell machine.",
                 "C2 and C7 are strong because a duplicated payment effect moves real money and shows up as a chargeback.",
                 "Every eventual boundary carries a named reconciliation point and a numeric tolerance; a boundary without one is treated as an untested defect.",
             ]},
        ],
    },
]
