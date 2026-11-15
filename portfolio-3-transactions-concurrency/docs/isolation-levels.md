# Transaction Isolation Levels & Concurrency Anomalies: Savannah Crest Hotels

**Course:** MIT 8103 Advanced Database Systems  
**Database Engine:** PostgreSQL 16.4  
**Implementation Evidence:** [scripts/run_two_sessions.py](../scripts/run_two_sessions.py), [sql/03_isolation_session_a.sql](../sql/03_isolation_session_a.sql), [evidence/isolation_levels_output.txt](../evidence/isolation_levels_output.txt)

---

## 1. ANSI SQL Standard vs PostgreSQL Implementation Reality

The ANSI/ISO SQL-92 standard defines four transaction isolation levels in terms of three theoretical read phenomena: Dirty Read, Non-Repeatable Read, and Phantom Read. However, PostgreSQL's Multi-Version Concurrency Control (MVCC) engine implements these levels differently from lock-based engines (e.g., standard 2PL in older relational databases).

### The "Dirty Read" Truth in PostgreSQL
In ANSI SQL, the `READ UNCOMMITTED` level is defined to permit **Dirty Reads** (reading uncommitted writes from a concurrent transaction).

> [!IMPORTANT]
> **PostgreSQL does NOT permit true Dirty Reads at ANY isolation level.**  
> In PostgreSQL, specifying `ISOLATION LEVEL READ UNCOMMITTED` is treated internally as `READ COMMITTED`. This is because PostgreSQL's MVCC tuple visibility rules (`heap_tuple_satisfies_mvcc`) require every read snapshot to check tuple creation headers (`xmin`) against the active commit log (`pg_xact`). An uncommitted row is invisible to all other database backends.

We proved this empirically in Experiment 1 of [scripts/run_two_sessions.py](../scripts/run_two_sessions.py): Session B updated Room 1 floor to `99` without committing; Session A at `READ UNCOMMITTED` queried Room 1 and saw floor `1`. The uncommitted write was strictly invisible.

---

## 2. Empirical Isolation Level vs Anomaly Matrix

The matrix below documents the phenomena **actually observed and measured** during our live multi-session testing in PostgreSQL 16.

| Isolation Level | Dirty Read | Non-Repeatable Read | Phantom Read | Write Skew | Concurrent Update Conflict | Evidence File Reference |
|---|---|---|---|---|---|---|
| **READ UNCOMMITTED** | **Not Possible** (Treated as Read Committed) | Observed | Observed | Observed | Blocks until commit | [evidence/isolation_levels_output.txt](../evidence/isolation_levels_output.txt) (Exp 1) |
| **READ COMMITTED** | **Not Possible** | **Observed** (Rate changed mid-tx) | Observed | Observed | Blocks on row lock | [evidence/isolation_levels_output.txt](../evidence/isolation_levels_output.txt) (Exp 2) |
| **REPEATABLE READ** | **Not Possible** | **Prevented** (Snapshot frozen) | **Prevented** (Snapshot frozen) | Observed | **Aborts with SQLSTATE 40001** | [evidence/isolation_levels_output.txt](../evidence/isolation_levels_output.txt) (Exp 3) |
| **SERIALIZABLE** | **Not Possible** | **Prevented** | **Prevented** | **Prevented** (Caught by SSI as a pivot) | **Aborts with SQLSTATE 40001** (Auto-Retried) | [evidence/isolation_levels_output.txt](../evidence/isolation_levels_output.txt) (Exp 4) |

---

## 3. Deep-Dive into Demonstrated Anomalies

### 3.1 Non-Repeatable Read (`READ COMMITTED`)
- **Business Scenario:** A front desk receptionist in Abuja queries the seasonal rate for Room 101, planning to quote a rate to a walk-in guest. Simultaneously, revenue management activates holiday pricing.
- **What happened:**
  1. Session A opened a transaction at `READ COMMITTED` and queried Rate 1: `₦35,000.00`.
  2. Session B concurrently executed `UPDATE seasonal_rate SET price_per_night = 48000.00 WHERE rate_id = 1; COMMIT;`.
  3. Session A re-issued the exact same query within its open transaction: the result was `₦48,000.00`.
- **Underlying Mechanism:** In `READ COMMITTED`, PostgreSQL establishes a **new MVCC snapshot at the start of each individual SQL statement**, rather than at the start of the transaction. Any data committed by another transaction before the second statement begins is visible.

---

### 3.2 Snapshot Isolation & Serialization Conflict (`REPEATABLE READ`)
- **Snapshot Freezing:**
  - In `REPEATABLE READ`, the snapshot is taken at the start of the **first non-transaction-control query** in the transaction.
  - In Experiment 3, when Session B committed the rate increase to `₦52,000.00`, Session A re-read the rate and continued to see `₦40,000.00`. Non-repeatable reads and phantom reads are completely eliminated.
- **Concurrent Update Failure (First-Committer-Wins):**
  - Session A then attempted to update the same row: `UPDATE seasonal_rate SET price_per_night = price_per_night + 2000 WHERE rate_id = 1;`.
  - In `READ COMMITTED`, Session A would simply wait for Session B to finish and then update the new version.
  - In `REPEATABLE READ`, PostgreSQL detects that the target row was updated and committed by a concurrent transaction *after* Session A's snapshot was established. Updating it would violate snapshot consistency.
  - **Result:** PostgreSQL immediately raises:
    ```text
    ERROR: could not serialize access due to concurrent update (SQLSTATE 40001)
    ```
  - The transaction is aborted and must be re-attempted by the application.

---

### 3.3 Write Skew and Serializable Snapshot Isolation (`SERIALIZABLE`)
- **The Invariant:** Savannah Crest Hotels enforces a property policy: *"At least 1 emergency executive suite on floor 5 of Hotel 1 must remain unassigned for urgent VIP walk-ins."*
- **Initial State:** Exactly 2 rooms are active on floor 5 (`room_id = 81` and `room_id = 82`).
- **The Write Skew Trap:**
  - Front Desk Agent A (Session A) checks available emergency rooms: `SELECT COUNT(*) ...` $\rightarrow$ sees 2.
  - Front Desk Agent B (Session B) concurrently checks available emergency rooms: `SELECT COUNT(*) ...` $\rightarrow$ sees 2.
  - Agent A decides it is safe to assign room 81 and updates it to `is_active = false`.
  - Agent B decides it is safe to assign room 82 and updates it to `is_active = false`.
  - Under `REPEATABLE READ`, **both transactions succeed and commit!** Why? Because they updated different physical rows (81 vs 82). But the combined result leaves **0 emergency rooms active**, breaking the invariant! This is the classic **Write Skew anomaly**.

- **How PostgreSQL SSI Solves It:**
  Under `SERIALIZABLE`, PostgreSQL tracks read-write conflicts using **SIREAD (predicate) locks** in shared memory.
  1. Session A reads the room count (acquiring an SIREAD lock on the table/index predicate).
  2. Session B reads the room count (acquiring an SIREAD lock on the same predicate).
  3. Session A writes to room 81, creating a rw-antidependency from Session B to Session A.
  4. Session B writes to room 82, creating a rw-antidependency from Session A to Session B.
  5. When Session A commits, PostgreSQL detects a **cycle in the Serialization Graph (a "pivot" transaction)**.
  6. When Session B attempts to commit, PostgreSQL aborts Session B to break the cycle:
     ```text
     ERROR: could not serialize access due to read/write dependencies among transactions
     DETAIL: Reason code: Canceled on identification as a pivot, during write.
     HINT: The transaction might succeed if retried. (SQLSTATE 40001)
     ```

- **The Automated Retry Loop:**
  In `scripts/run_two_sessions.py`, Agent B catches exception `40001`, backs off 100ms, and starts a fresh transaction.
  Upon retry, Agent B re-queries the pool, sees `COUNT = 1`, determines that deactivating room 82 would violate the hotel policy, and **gracefully cancels the assignment**.
  - **Final Verification:** 1 emergency suite remains active. The business invariant was preserved.

