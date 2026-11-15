# Empirical Double-Booking Concurrency Experiment Results

**Test Configuration:** 20 concurrent client threads competing for 1 available room/inventory.
**Execution Timestamp:** 2026-11-15 11:11:31

## 1. Summary Comparison Table

| Strategy | Clients | Successes | Failures / Rejected | Persisted Bookings | Duration (s) | Verdict |
|---|---|---|---|---|---|---|
| **Run A (Unsafe Check-then-Insert)** | 20 | 20 | 0 | **20** | 0.531s | CRITICAL FAILURE: 20 double bookings persisted. |
| **Run B (Pessimistic FOR UPDATE)** | 20 | 1 | 19 | **1** | 0.683s | PASS: Exactly 1 client won; 19 rejected safely by lock serialization. |
| **Run C (GiST Exclusion Constraint)** | 20 | 1 | 19 | **1** | 0.666s | PASS: Kernel-level enforcement; exactly 1 won, 19 caught exclusion_violation. |
| **Run D (Optimistic Version CAS)** | 20 | 1 | 19 | **1** | 1.474s | PASS: Compare-and-swap prevented overbooking (19 retries caught). |

## 2. Key Findings

1. **Unsafe Check-Then-Insert (Run A):** All 20 threads simultaneously passed the `COUNT = 0` check due to the lack of mutual exclusion during the read-insert interval. Multiple overlapping records were persisted to disk, empirically proving the classic double-booking anomaly.
2. **Pessimistic Locking (Run B):** `SELECT ... FOR UPDATE` successfully serialized all 20 clients. Exactly 1 client booked the room; the remaining 19 waited and cleanly aborted upon re-checking the room state.
3. **GiST Exclusion Constraint (Run C):** Required zero application locking logic. PostgreSQL's storage engine rejected 19 concurrent conflicting transactions with `ExclusionViolation`, guaranteeing that exactly 1 booking succeeded.
4. **Optimistic Versioning (Run D):** Used a version column and atomic Compare-And-Swap. Conflicting threads retried and gracefully aborted once inventory hit 0, proving lock-free safety.
