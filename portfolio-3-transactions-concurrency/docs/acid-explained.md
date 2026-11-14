# ACID Properties in Practice: Savannah Crest Hotels

**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** Savannah Crest Hotels Central Reservation System  
**Database Engine:** PostgreSQL 16  
**Implementation Evidence:** [sql/01_booking_transaction.sql](../sql/01_booking_transaction.sql), [sql/02_rollback_scenarios.sql](../sql/02_rollback_scenarios.sql), [evidence/](../evidence/)

---

## 1. Introduction to ACID in Hotel Reservation Systems

In a multi-property hotel chain operating across 6 Nigerian cities, database transactions must maintain strict financial and operational integrity. A failure during a booking must never leave an orphan reservation without a payment record, double-book a room, or lose confirmed transactions during a system restart.

PostgreSQL enforces the four ACID properties through its storage engine, Write-Ahead Logging (WAL), and Multi-Version Concurrency Control (MVCC). Below is a direct mapping of each ACID principle to the concrete implementations and test runs in this portfolio.

---

## 2. Atomicity ("All-or-Nothing")

### Definition
Atomicity guarantees that a transaction composed of multiple database operations either completes in its entirety (**COMMIT**) or has zero lasting effect on the database state (**ROLLBACK**). Intermediate states are never visible.

### Implementation in this Portfolio
A hotel reservation is an inherently multi-step operation:
1. Lock room and verify availability.
2. Insert reservation header into `booking`.
3. Insert room assignment into `booking_room`.
4. Process financial transaction in `payment`.
5. Update room housekeeping status in `room_status_history`.
6. Record change in `audit_log`.

#### Empirical Demonstrations:
1. **Successful Multi-Step Commit ([sql/01_booking_transaction.sql](../sql/01_booking_transaction.sql)):**
   - All 5 tables are modified within a single `BEGIN ... COMMIT` block.
   - The test verification in [evidence/01_booking_transaction_output.txt](../evidence/01_booking_transaction_output.txt) confirms that the booking (`TX-CONFIRMED-2027`), room stay, payment, and audit record appeared simultaneously upon commit.

2. **Mid-Transaction Payment Failure ([sql/02_rollback_scenarios.sql](../sql/02_rollback_scenarios.sql) - Scenario A):**
   - Steps 1 and 2 create the booking header and room assignment.
   - The simulated credit card gateway declines the transaction (`DECLINED_INSUFFICIENT_FUNDS`).
   - The application issues an explicit `ROLLBACK`.
   - **Empirical Proof:** The post-verification query confirms:
     ```text
     booking_header_count | booking_room_count | payment_count
     ---------------------+--------------------+---------------
                        0 |                  0 |             0
     ```
     Zero partial or orphan rows survived. The database was restored to its pristine pre-transaction state.

3. **Partial Failure Recovery via SAVEPOINT (Scenario C):**
   - Demonstrates nested transaction control using `SAVEPOINT sp_core_booking;`.
   - When an optional airport shuttle payment fails a check constraint, the application executes `ROLLBACK TO SAVEPOINT sp_core_booking;` and commits the core reservation.
   - **Empirical Proof:** The core room reservation is committed, while the failed shuttle sub-operation is discarded without aborting the entire customer booking.

### PostgreSQL Internal Mechanism
PostgreSQL tracks transaction state in the `pg_xact` (commit log / CLOG) ring buffer. Changes made during an uncommitted transaction are written to data pages tagged with the current transaction identifier (`xmin = txid`). If the transaction aborts or is rolled back, PostgreSQL marks the transaction status as `ABORTED` in `pg_xact`. Subsequent queries inspect `xmin` against `pg_xact` and treat those tuples as completely invisible, eventually cleaned up asynchronously by VACUUM.

---

## 3. Consistency (Invariants and State Validity)

### Definition
Consistency ensures that a transaction transitions the database from one valid state to another valid state, satisfying all explicit integrity constraints, foreign keys, triggers, and business invariants.

### Implementation in this Portfolio
Consistency is enforced at the database kernel level rather than relying on application code:

| Invariant / Rule | Constraint Mechanism | Demonstration in Evidence |
|---|---|---|
| **No Double Booking** | `EXCLUDE USING gist (room_id WITH =, stay WITH &&)` | Rejected in [01_booking_transaction_output.txt](../evidence/01_booking_transaction_output.txt) Part 6 (`exclusion_violation`) |
| **Check-out after Check-in** | `CHECK (check_out_date > check_in_date)` | Enforced in `booking_room` table schema |
| **Non-Negative Payments** | `CHECK (amount >= 0)` | Triggered in Scenario B: rejected with `check_violation` |
| **Referential Integrity** | `FOREIGN KEY ... ON DELETE RESTRICT` | Prevents deleting guest or hotel records with active bookings |
| **Audit Log Integrity** | `AFTER UPDATE ON booking` trigger | Guaranteed generation of JSONB before/after values |

#### Empirical Demonstration:
- In `sql/02_rollback_scenarios.sql` (Scenario B), inserting a negative payment (`-50000.00`) fails:
  ```text
  ERROR: new row for relation "payment" violates check constraint "payment_amount_check"
  ERROR: current transaction is aborted, commands ignored until end of transaction block
  ```
- PostgreSQL immediately invalidates the entire transaction block. Any subsequent command (`SELECT 1;`) is blocked by the engine until an explicit `ROLLBACK` is issued.

---

## 4. Isolation (Concurrent Non-Interference)

### Definition
Isolation controls how concurrent transactions executing simultaneously perceive changes made by one another, preventing concurrency anomalies such as dirty reads, non-repeatable reads, and lost updates.

### Implementation in this Portfolio
1. **Pessimistic Concurrency Control ([sql/01_booking_transaction.sql](../sql/01_booking_transaction.sql)):**
   - The transaction opens with:
     ```sql
     SELECT room_id, hotel_id, room_number 
     FROM room WHERE room_id = 1 
     FOR UPDATE;
     ```
   - This takes an exclusive row-level lock (`RowShareLock` / `ExclusiveLock`) on Room 1. Any other concurrent transaction attempting to reserve or update Room 1 is queued until the first transaction issues `COMMIT` or `ROLLBACK`.

2. **Multi-Version Concurrency Control (MVCC):**
   - PostgreSQL readers do not lock writers, and writers do not lock readers.
   - When a front-desk receptionist queries occupancy reports via `v_daily_occupancy`, the query reads the snapshot of committed data corresponding to its query start timestamp, unaffected by concurrent online bookings in flight.

3. **Isolation Levels Evaluated:**
   - Detailed multi-session scripts and anomaly demonstrations for `READ COMMITTED`, `REPEATABLE READ`, and `SERIALIZABLE` are implemented and evaluated in Milestone 3.2.

---

## 5. Durability (Survivability of Committed Data)

### Definition
Durability guarantees that once a transaction commits, its effects permanently survive system crashes, server crashes, power outages, and container restarts.

### Implementation in this Portfolio
PostgreSQL achieves Durability through **Write-Ahead Logging (WAL)**:

1. **Write-Ahead Principle:**
   - Before any dirty table page is written to data files on disk, the exact logical change is serialized into a WAL buffer.
   - When the client issues `COMMIT`, PostgreSQL executes a synchronous flush (`fsync`) of the WAL records to physical disk storage.
   - Only after the WAL records are confirmed on persistent non-volatile media does PostgreSQL send the `COMMIT 0 1` acknowledgment to the client.

2. **Crash Recovery Test:**
   - In our Docker environment, PostgreSQL volumes are mounted to host non-volatile storage (`pgdata`).
   - If the PostgreSQL container is ungracefully killed (`docker compose kill postgres`), on restart PostgreSQL enters **redo recovery**: it scans the WAL from the last checkpoint, replays all committed transactions, and undoes all uncommitted transactions, restoring the exact state of Savannah Crest Hotels without data loss.

---

## 6. Summary Matrix

| Property | Threat to Hotel System | PostgreSQL Defence Mechanism | Repo Demonstration |
|---|---|---|---|
| **Atomicity** | Room booked but payment failed | CLOG (`pg_xact`), `ROLLBACK`, Savepoints | `sql/02_rollback_scenarios.sql` (Scenarios A & C) |
| **Consistency** | Double booking; negative payment | Constraints, Triggers, GiST Exclusion | `sql/01_booking_transaction.sql` (Stored Procedure) |
| **Isolation** | Two guests booking last room | MVCC, Row Locks (`FOR UPDATE`), SSI | `sql/01_booking_transaction.sql` (`FOR UPDATE`) |
| **Durability** | Power outage post-confirmation | Write-Ahead Log (WAL), `fsync` | Confirmed via Docker persistent volume & WAL |

