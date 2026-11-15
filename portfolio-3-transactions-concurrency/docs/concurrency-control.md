# Concurrency Control & Double-Booking Prevention: Savannah Crest Hotels

**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** Savannah Crest Hotels Central Reservation System  
**Implementation Evidence:**  
- [scripts/double_booking_demo.py](../scripts/double_booking_demo.py)  
- [evidence/double-booking-results.md](../evidence/double-booking-results.md)  
- [scripts/run_deadlock.py](../scripts/run_deadlock.py)  
- [evidence/deadlock_output.txt](../evidence/deadlock_output.txt)  

---

## 1. The Double-Booking Challenge in Hotel Databases

In high-concurrency property management databases, the most dangerous business failure is the **double booking**: assigning the same physical room to two different guests for overlapping date ranges ($[start_A, end_A) \cap [start_B, end_B) \neq \emptyset$).

Double bookings create severe operational distress, guest displacement, financial compensation costs, and reputational damage. To identify the optimal architectural defense, we evaluated four distinct concurrency control strategies under an intense 20-client concurrent booking burst for the last available room.

---

## 2. Empirical Evaluation of the 4 Concurrency Strategies

Data measured live via `scripts/double_booking_demo.py` (20 concurrent threads targeting Room 10 for dates `2027-06-01` to `2027-06-05`):

| Strategy | Clients | Successful Bookings | Rejected / Conflicts | Persisted Double Bookings | Elapsed Time | Operational Verdict |
|---|---|---|---|---|---|---|
| **Run A: Unsafe Check-Then-Insert** | 20 | **20** | 0 | **20** | 1.786s | **CRITICAL FAILURE: 20 overlapping bookings persisted.** |
| **Run B: Pessimistic Locking (`FOR UPDATE`)** | 20 | **1** | 19 | **1** | 1.003s | **PASS: Mutual exclusion enforced; 19 rejected cleanly.** |
| **Run C: GiST Exclusion Constraint** | 20 | **1** | 19 | **1** | 1.059s | **PASS: Database engine rejected 19 via `exclusion_violation`.** |
| **Run D: Optimistic Version CAS** | 20 | **1** | 19 | **1** | 0.644s | **PASS: Lock-free atomic versioning prevented overbooking.** |

---

## 3. In-Depth Analysis of Each Strategy

### 3.1 Run A: Unsafe Check-Then-Insert (The TOCTOU Anomaly)
- **The Pattern:**
  ```sql
  -- Step 1 (Time-of-Check):
  SELECT COUNT(*) FROM booking_room WHERE room_id = 10 AND stay && daterange(...);
  -- Step 2 (Time-of-Use):
  IF count == 0 THEN
      INSERT INTO booking ...;
      INSERT INTO booking_room ...;
  END IF;
  ```
- **Why it failed catastrophically:**
  - In a multi-threaded web application, all 20 threads executed Step 1 simultaneously.
  - Because no database locks or constraints were present, all 20 threads read `COUNT = 0`.
  - Every single thread concluded the room was vacant, proceeded to Step 2, and committed an overlapping reservation.
  - **Result:** **20 overlapping bookings were written to Room 10**, proving that application-level checks without concurrency control fail under real-world load.

---

### 3.2 Run B: Pessimistic Concurrency Control (`SELECT ... FOR UPDATE`)
- **The Pattern:**
  ```sql
  BEGIN;
  -- Take exclusive row-level lock on the room record
  SELECT room_id FROM room WHERE room_id = 10 FOR UPDATE;
  -- Now verify availability with guaranteed exclusive access
  SELECT COUNT(*) FROM booking_room WHERE room_id = 10 AND stay && ...;
  IF count == 0 THEN
      INSERT INTO booking ...;
      INSERT INTO booking_room ...;
  END IF;
  COMMIT;
  ```
- **How it works:**
  - The first client to execute `SELECT ... FOR UPDATE` acquires an exclusive row lock (`RowShareLock` / `ExclusiveLock`) on Room 10.
  - The other 19 clients are placed into a FIFO wait queue inside the PostgreSQL lock manager.
  - Once Client 1 commits, Client 2 wakes up, inspects `booking_room`, detects Client 1's newly committed reservation, rolls back, and returns `"Room Unavailable"`.
  - **Verdict:** 100% safe. Exactly 1 reservation created.
- **The `SKIP LOCKED` Variant for Free-Room Pools:**
  - When a guest requests *"Any available Deluxe room"* (rather than Room 10 specifically), queuing behind a single room is inefficient.
  - Using `SELECT room_id FROM room WHERE room_type_id = 2 FOR UPDATE SKIP LOCKED LIMIT 1;` allows concurrent threads to skip already-locked rooms and grab distinct rooms simultaneously without blocking.

---

### 3.3 Run C: Database-Enforced Kernel Invariants (GiST Exclusion Constraint)
- **The Pattern:**
  ```sql
  CONSTRAINT excl_no_overlapping_booking EXCLUDE USING gist (
      room_id WITH =,
      stay    WITH &&
  ) WHERE (status IN ('reserved', 'checked_in'))
  ```
- **How it works:**
  - Requires **zero application-level locking code**.
  - All 20 clients immediately attempt to insert their `booking_room` record.
  - PostgreSQL's storage engine evaluates the multi-column GiST index over `(room_id, stay)` during insertion.
  - The first transaction's index entry claims the range. When concurrent transactions attempt to insert intersecting ranges, the engine detects the key conflict and raises:
    ```text
    ERROR: conflicting key value violates exclusion constraint "excl_no_overlapping_booking"
    ```
  - **Verdict:** Exactly 1 winner; 19 received a clean `exclusion_violation`. Safe against all application bugs, rogue scripts, or manual psql inserts.

---

### 3.4 Run D: Optimistic Concurrency Control (OCC with Versioning)
- **The Pattern:**
  ```sql
  -- Step 1: Read current inventory and version without locking
  SELECT available_rooms, version FROM room_inventory WHERE hotel_id = 1 AND stay_date = '2027-07-01';
  -- Step 2: Atomic Compare-and-Swap
  UPDATE room_inventory 
  SET available_rooms = available_rooms - 1, version = version + 1
  WHERE hotel_id = 1 AND stay_date = '2027-07-01' AND version = :read_version AND available_rooms > 0;
  ```
- **How it works:**
  - If `rowcount == 1`, the update succeeded atomically.
  - If `rowcount == 0`, another client updated the version in the interim. The client rolls back, reads the new version, and retries.
  - **Verdict:** Succeeded in 0.644s (the fastest elapsed time). 11 version retries were caught and handled cleanly before inventory hit 0.

---

## 4. Architectural Comparison Matrix

| Dimension | Run A: Unsafe | Run B: Pessimistic (`FOR UPDATE`) | Run C: GiST Exclusion | Run D: Optimistic (OCC) |
|---|---|---|---|---|
| **Double-Booking Safety** | ❌ **Broken (20 double bookings)** | ✅ **100% Safe** | ✅ **100% Safe (Kernel)** | ✅ **100% Safe** |
| **Throughput (Low Contention)** | High | High | Very High | **Highest** |
| **Throughput (High Contention)** | High (Corrupts Data) | Moderate (Wait queues) | High | Degrades (Retry storm) |
| **Deadlock Vulnerability** | None | **High** (If locking multiple rooms) | Very Low | None |
| **Implementation Complexity** | Trivial | Moderate | **Lowest (Declarative DDL)** | High (Requires retry loops) |
| **Recommended Use Case** | Never | Multi-room checkout; Payment holds | **Core Room Reservation Engine** | Property-level room count quotas |

---

## 5. Deadlock Analysis and Architectural Prevention

When pessimistic locking is employed across multiple records, databases become vulnerable to **Deadlocks**.

### 5.1 Real Deadlock Reproduction ([evidence/deadlock_output.txt](../evidence/deadlock_output.txt))
In `scripts/run_deadlock.py` (Phase 1):
1. **Session 1:** `BEGIN; UPDATE room SET is_active = true WHERE room_id = 1;` (holds Room 1).
2. **Session 2:** `BEGIN; UPDATE room SET is_active = true WHERE room_id = 2;` (holds Room 2).
3. **Session 1:** Attempts to update Room 2 $\rightarrow$ Blocks waiting for Session 2.
4. **Session 2:** Attempts to update Room 1 $\rightarrow$ Blocks waiting for Session 1.
5. **The Cyclic Wait:** A directed cycle exists: $T_1 \rightarrow T_2 \rightarrow T_1$.
6. **Kernel Intervention:** After `deadlock_timeout = 500ms`, PostgreSQL's deadlock detector identified the cycle and aborted Session 1:
   ```text
   ERROR: deadlock detected (SQLSTATE 40P01)
   DETAIL: Process 6433 waits for ShareLock on transaction 1152; blocked by process 6434.
           Process 6434 waits for ShareLock on transaction 1151; blocked by process 6433.
   ```

### 5.2 The Architectural Fix: Consistent Resource Ordering
To eliminate deadlocks algebraically, all transactions must acquire locks in **identical, deterministic order**:
```sql
SELECT room_id FROM room 
WHERE room_id IN (1, 2) 
ORDER BY room_id ASC 
FOR UPDATE;
```
- In Phase 2 of `run_deadlock.py`, both workers requested locks ordered by `room_id ASC`.
- Worker 2 queued behind Worker 1 on Room 1 *before* acquiring Room 2.
- A circular wait condition became mathematically impossible. Both workers committed cleanly with **zero deadlocks**.

