# Distributed Transactions, Two-Phase Commit & The Saga Pattern

**Portfolio 5: Distributed and Cloud Database Exercise**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Summary & The Distributed Transaction Dilemma

In a monolithic architecture, ACID transactions (`BEGIN ... COMMIT`) provide seamless atomicity across multiple tables managed by a single database engine. However, modern cloud architectures decouple systems into autonomous microservices and distributed data stores:
- **Room Inventory Service:** PostgreSQL (authoritative room availability & GiST exclusion constraints).
- **Payment Gateway:** External third-party payment processor (Paystack, Flutterwave, Stripe) with asynchronous webhook settlement.
- **Notification Service:** Cloud email/SMS dispatcher (Twilio, SendGrid).

Executing an atomic reservation across these heterogeneous services cannot rely on local database transactions. This document analyzes why traditional **Two-Phase Commit (2PC)** fails at scale and demonstrates how Savannah Crest Hotels implements the **Saga Pattern with Orchestration and Compensating Transactions**.

---

## 2. Why Classic ACID Fails Across Microservices

Attempting to enforce strict ACID across distributed networks introduces three severe failure modes:

1. **Availability Degradation (The Product Rule):**
   If a distributed transaction requires three independent services, each with $99.5\%$ availability, the compound availability of the transaction degrades to:
   $$\text{Availability}_{\text{compound}} = 0.995^3 \approx 98.51\%$$
   A failure in the external payment gateway immediately locks the local database.
2. **Lock Amplification & Throughput Collapse:**
   Holding relational row locks (`SELECT ... FOR UPDATE`) while waiting for an external HTTP network request to an external payment processor ties up database connections for $500\text{--}2000\text{ ms}$, exhausting connection pools and stalling unrelated bookings.
3. **Lack of Uniform Transaction Interfaces:**
   External APIs (e.g., credit card payment gateways) do not implement database transaction protocols. Once money is debited from a guest's credit card, the operation cannot be physically rolled back via SQL `ROLLBACK`; it requires an explicit refund transaction.

---

## 3. Two-Phase Commit (2PC) Analysis & Limitations

The classic theoretical approach to distributed consensus is **Two-Phase Commit (2PC)**:

```
Coordinator (Booking App)               Participant 1 (PostgreSQL)    Participant 2 (Payment Gateway)
        │                                          │                                │
        ├──────────── Phase 1: PREPARE ───────────►│                                │
        ├──────────── Phase 1: PREPARE ────────────────────────────────────────────►│
        │                                          │                                │
        │◄─────────── VOTE_COMMIT ─────────────────┤                                │
        │◄─────────── VOTE_COMMIT ──────────────────────────────────────────────────┤
        │                                          │                                │
        ├──────────── Phase 2: GLOBAL_COMMIT ─────►│                                │
        ├──────────── Phase 2: GLOBAL_COMMIT ──────────────────────────────────────►│
        │                                          │                                │
        │◄─────────── ACK ─────────────────────────┤                                │
        │◄─────────── ACK ──────────────────────────────────────────────────────────┤
```

### Critical Flaws of 2PC in Cloud Environments:
1. **Blocking Protocol:** If the coordinator crashes after participants vote `VOTE_COMMIT` but before broadcasting `GLOBAL_COMMIT`, participants must hold their locks indefinitely. They cannot unilaterally commit or abort.
2. **Single Point of Failure (SPOF):** The transaction coordinator represents an operational bottleneck and failure single point.
3. **High Latency Overhead:** 2PC requires multiple synchronous network round-trips over WAN links, making it fundamentally incompatible with high-velocity consumer web applications.

---

## 4. The Saga Pattern: Orchestration & Compensating Transactions

To overcome 2PC limitations, Savannah Crest Hotels deploys the **Saga Pattern** (Garcia-Molina & Salem, 1987). A Saga is a sequence of local transactions ($T_1, T_2, \dots, T_n$) where each step updates a local database and publishes an event.

If a local step fails, the Saga Orchestrator executes backward **Compensating Transactions** ($C_{n-1}, \dots, C_1$) in reverse order to semantically undo previous changes:

```
[ Normal Forward Path ]
  (T1: Hold Room)  ══════►  (T2: Charge Payment)  ══════►  (T3: Confirm Hold)  ══════►  (T4: Dispatch SMS)
                                  │
                           Payment Declined
                                  │
                                  ▼
[ Backward Compensating Path ]
  (C1: Release Room Hold) ◄───────┘
  (Room unblocked; status set to CANCELLED)
```

### 4.1 Orchestration vs. Choreography
We selected **Saga Orchestration** (centralized state machine) over Choreography (decentralized event pub/sub):
- **Visibility:** A dedicated Orchestrator maintains an explicit audit log of the Saga's current state (`STARTED`, `HOLD_ACQUIRED`, `PAYMENT_CHARGED`, `COMPENSATING`, `COMPENSATED_ABORT`).
- **Simplicity:** Prevents complex circular event dependencies and distributed debugging nightmares across microservice teams.

---

## 5. Empirical Validation (from `scripts/saga_orchestrator.py`)

Our Python orchestration engine (`portfolio-5-distributed-cloud/scripts/saga_orchestrator.py`) simulates live interactions across the PostgreSQL Inventory Service, Payment Gateway, and Notification Service.

### Scenario 1: Happy Path Distributed Transaction (Commit)
```
>>> INITIATING SAGA [ID: 98c35b96-ffd6-4fd3-8e9b-8f5c05e98e7b] <<<
    Hotel: Savannah Crest Abuja | Room: 10 | Guest: 101 | Dates: 2026-12-10 to 2026-12-14
    [InventoryService] Holding Room 10 (Hotel 1) for Saga 98c35b96...
    [InventoryService] ✓ Room 10 held successfully (Booking ID: 500028)
    [PaymentGateway] Charging ₦180,000.00 via card (Idempotency: idemp_e2)...
    [PaymentGateway] ✓ Payment approved! Transaction Ref: TXN-SUCCESS-idemp_e2 (Payment ID: 520206)
    [InventoryService] Confirming reservation for Booking ID 500028...
    [InventoryService] ✓ Booking ID 500028 status updated to CONFIRMED.
    [NotificationService] Sending confirmation email to amina.bello101@mail.ng for SAGA-98C35B96...
    [NotificationService] ✓ Email and SMS alerts successfully dispatched.
    [Orchestrator] ✓ SAGA COMPLETED SUCCESSFULLY. All distributed services converged.
```

### Scenario 2: Payment Failure Triggering Compensating Rollback
```
>>> INITIATING SAGA [ID: 367f5bd3-abbd-415e-808d-47844b00931a] <<<
    Hotel: Savannah Crest Victoria Island | Room: 115 | Guest: 102 | Dates: 2026-12-15 to 2026-12-18
    [InventoryService] Holding Room 115 (Hotel 2) for Saga 367f5bd3...
    [InventoryService] ✓ Room 115 held successfully (Booking ID: 500029)
    [PaymentGateway] Charging ₦255,000.00 via card (Idempotency: idemp_73)...
    [PaymentGateway] ✗ PAYMENT DECLINED: Insufficient funds / Card expired (Simulated Error)

    [Orchestrator] ✗ Step 2 (Payment) Failed: Payment Authorization Refused by Issuing Bank.
    [Orchestrator] ⚡ TRIGGERING BACKWARD COMPENSATING TRANSACTIONS...
    [InventoryService] ⚠️ EXECUTING COMPENSATING ACTION: Releasing Booking ID 500029...
    [InventoryService] ✓ Booking ID 500029 marked CANCELLED. Room returned to pool.
    [Orchestrator] ✓ Saga 367f5bd3 rolled back cleanly. System consistency preserved.
```

**Post-Compensation Database Audit State in PostgreSQL:**
- `Booking Status:` `cancelled`
- `Room Status:` `cancelled`
- `Audit Notes:` `CANCELLED BY SAGA COMPENSATION: Payment Authorization Refused by Issuing Bank.`
- **Result:** Room 115 was immediately freed in PostgreSQL, allowing other guests to book it. Zero orphan payments or stranded reservation holds were left in the system.

### Scenario 3: Transient Timeout with Idempotent Retry
- Step 2 encountered a simulated network timeout.
- Rather than immediately triggering compensation, the Orchestrator retried with an **Idempotency Key** (`idemp_b3`).
- Attempt 2 succeeded, completing the reservation and avoiding unnecessary compensation overhead.

---

## 6. The Transactional Outbox Pattern

A persistent challenge in distributed architectures is **dual-write inconsistency**: what happens if the database write commits, but publishing the message to Apache Kafka or RabbitMQ fails due to a network outage?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       TRANSACTIONAL OUTBOX PATTERN                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PostgreSQL Atomic Transaction Boundary                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. INSERT INTO booking (...)                                           │ │
│  │ 2. INSERT INTO outbox_table (aggregate_type, event_payload, status)    │ │
│  │    VALUES ('BOOKING', '{"ref": "SC-2026-001", "room": 305}', 'PENDING')│ │
│  │ COMMIT;                                                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                               ▲                                             │
│                               │ Polling / WAL Logical Decoding              │
│                               │ (Debezium CDC Engine)                       │
│                               ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Debezium reads outbox_table and reliably pushes event to Apache Kafka  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│                               ▼                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Distributed Subscribers (Payment, Notification, Analytics, MongoDB)    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
By writing the message to an `outbox_table` inside the *exact same ACID database transaction* as the booking record, Savannah Crest Hotels guarantees **at-least-once event delivery** without distributed 2PC locking.

