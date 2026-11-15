-- =============================================================================
-- deadlock_demo.sql
-- Savannah Crest Hotels: Real Deadlock Reproduction & Resolution Demo
-- Portfolio 3: Transactions and Concurrency
--
-- Demonstrates:
--   1. The Classic Deadlock: Two transactions updating Room 1 and Room 2
--      in opposite order (T1: Room 1 -> Room 2; T2: Room 2 -> Room 1).
--   2. The PostgreSQL Deadlock Detector: Detects cyclic wait graph (40P01)
--      and terminates one transaction with an informative error message.
--   3. The Architectural Solution: Consistent resource locking order (ORDER BY PK).
--
-- Can be run interactively across two psql terminals, or automatically via
-- python3 scripts/run_deadlock.py.
-- =============================================================================

-- =============================================================================
-- PART 1: THE DEADLOCK ANOMALY (OPPOSITE LOCK ORDER)
-- =============================================================================

-- In Terminal 1 (Session 1):
-- -------------------------
-- BEGIN;
-- UPDATE room SET is_active = true WHERE room_id = 1; -- Acquires RowExclusiveLock on Room 1
-- (Wait for Terminal 2 to acquire lock on Room 2)
-- UPDATE room SET is_active = true WHERE room_id = 2; -- BLOCKS waiting for Terminal 2!

-- In Terminal 2 (Session 2):
-- -------------------------
-- BEGIN;
-- UPDATE room SET is_active = true WHERE room_id = 2; -- Acquires RowExclusiveLock on Room 2
-- UPDATE room SET is_active = true WHERE room_id = 1; -- BLOCKS waiting for Terminal 1!

-- RESULT:
-- Cycle established: Session 1 -> Session 2 -> Session 1.
-- After deadlock_timeout (default 1s), PostgreSQL terminates one session:
-- ERROR:  deadlock detected
-- DETAIL: Process 123 waits for ExclusiveLock on tuple (0,1) of relation "room";
--         blocked by process 456.
--         Process 456 waits for ExclusiveLock on tuple (0,2) of relation "room";
--         blocked by process 123.
-- HINT:   See server log for query details. (SQLSTATE 40P01)


-- =============================================================================
-- PART 2: THE ARCHITECTURAL FIX (CONSISTENT LOCK ORDERING)
-- =============================================================================
-- Both transactions ALWAYS acquire locks in deterministic primary key order
-- (e.g. min(room_id) then max(room_id)):

-- Both Terminal 1 and Terminal 2 execute:
-- BEGIN;
-- SELECT room_id FROM room WHERE room_id IN (1, 2) ORDER BY room_id ASC FOR UPDATE;
-- UPDATE room SET is_active = true WHERE room_id = 1;
-- UPDATE room SET is_active = true WHERE room_id = 2;
-- COMMIT;

-- RESULT:
-- Session 2 politely queues behind Session 1 on Room 1 without holding Room 2.
-- Once Session 1 commits, Session 2 proceeds. Zero deadlocks!

