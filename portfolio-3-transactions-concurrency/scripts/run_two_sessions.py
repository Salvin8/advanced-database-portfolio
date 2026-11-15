#!/usr/bin/env python3
"""
run_two_sessions.py - Automated Multi-Session Concurrency & Isolation Level Harness
Portfolio 3: Transactions and Concurrency

Demonstrates real multi-threaded transactional interactions between Session A and Session B:
  1. READ UNCOMMITTED: Proves dirty reads are impossible in PostgreSQL (treated as READ COMMITTED).
  2. READ COMMITTED: Empirically demonstrates Non-Repeatable Read anomaly.
  3. REPEATABLE READ: Proves Snapshot Isolation eliminates non-repeatable reads, but raises
     serialization failure (40001) upon concurrent write conflict.
  4. SERIALIZABLE: Demonstrates Serializable Snapshot Isolation (SSI) detecting Write Skew,
     aborts with 40001, and executes an automated retry loop that successfully preserves the invariant.

Logs all output to terminal and evidence/isolation_levels_output.txt.
"""

import os
import sys
import time
import threading
import psycopg
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

OUTPUT_FILE = "portfolio-3-transactions-concurrency/evidence/isolation_levels_output.txt"
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)


class Logger:
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.log = open(filepath, "w")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


def get_connection():
    return psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB,
        autocommit=False
    )


# ==============================================================================
# DEMONSTRATION 1: READ UNCOMMITTED vs DIRTY READS
# ==============================================================================
def demo_read_uncommitted(logger):
    logger.write("\n" + "=" * 70 + "\n")
    logger.write("EXPERIMENT 1: READ UNCOMMITTED & DIRTY READ VERIFICATION\n")
    logger.write("ANSI SQL Definition: Reading uncommitted changes made by another transaction.\n")
    logger.write("PostgreSQL Truth: PostgreSQL does NOT allow dirty reads at ANY isolation level.\n")
    logger.write("=" * 70 + "\n\n")

    conn_a = get_connection()
    conn_b = get_connection()
    cur_a = conn_a.cursor()
    cur_b = conn_b.cursor()

    # Reset room 1 notes
    cur_a.execute("UPDATE room SET floor = 1 WHERE room_id = 1;")
    conn_a.commit()

    barrier_1 = threading.Barrier(2)
    barrier_2 = threading.Barrier(2)
    barrier_3 = threading.Barrier(2)

    def thread_a():
        cur_a.execute("BEGIN TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
        cur_a.execute("SELECT floor FROM room WHERE room_id = 1;")
        val1 = cur_a.fetchone()[0]
        logger.write(f"  [Session A @ READ UNCOMMITTED] Initial floor for Room 1 = {val1}\n")
        
        barrier_1.wait() # Wait for Session B to perform uncommitted update
        barrier_2.wait() # Session B updated, now A queries

        cur_a.execute("SELECT floor FROM room WHERE room_id = 1;")
        val2 = cur_a.fetchone()[0]
        logger.write(f"  [Session A @ READ UNCOMMITTED] Re-reading while Session B is uncommitted = {val2}\n")
        if val1 == val2:
            logger.write("  -> RESULT: Dirty read PREVENTED! Session A cannot see Session B uncommitted update.\n")
        else:
            logger.write("  -> RESULT: Dirty read occurred!\n")
            
        barrier_3.wait() # Wait for Session B to rollback
        conn_a.rollback()

    def thread_b():
        barrier_1.wait()
        cur_b.execute("BEGIN;")
        cur_b.execute("UPDATE room SET floor = 99 WHERE room_id = 1;")
        logger.write("  [Session B] Executed uncommitted UPDATE room SET floor = 99 WHERE room_id = 1\n")
        barrier_2.wait()
        time.sleep(0.1)
        cur_b.execute("ROLLBACK;")
        logger.write("  [Session B] Rolled back uncommitted changes.\n")
        barrier_3.wait()

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    cur_a.close()
    cur_b.close()
    conn_a.close()
    conn_b.close()


# ==============================================================================
# DEMONSTRATION 2: READ COMMITTED -> NON-REPEATABLE READ
# ==============================================================================
def demo_read_committed(logger):
    logger.write("\n" + "=" * 70 + "\n")
    logger.write("EXPERIMENT 2: READ COMMITTED & NON-REPEATABLE READ ANOMALY\n")
    logger.write("Definition: Same query in open transaction sees different data after external commit.\n")
    logger.write("=" * 70 + "\n\n")

    conn_a = get_connection()
    conn_b = get_connection()
    cur_a = conn_a.cursor()
    cur_b = conn_b.cursor()

    # Reset rate 1 price
    cur_a.execute("UPDATE seasonal_rate SET price_per_night = 35000.00 WHERE rate_id = 1;")
    conn_a.commit()

    barrier_1 = threading.Barrier(2)
    barrier_2 = threading.Barrier(2)

    def thread_a():
        cur_a.execute("BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;")
        cur_a.execute("SELECT price_per_night FROM seasonal_rate WHERE rate_id = 1;")
        rate1 = cur_a.fetchone()[0]
        logger.write(f"  [Session A @ READ COMMITTED] Read 1: Rate = ₦{rate1:,.2f}\n")
        
        barrier_1.wait() # Wait for Session B to update and commit
        barrier_2.wait() # Session B committed

        cur_a.execute("SELECT price_per_night FROM seasonal_rate WHERE rate_id = 1;")
        rate2 = cur_a.fetchone()[0]
        logger.write(f"  [Session A @ READ COMMITTED] Read 2 (same transaction): Rate = ₦{rate2:,.2f}\n")
        
        if rate1 != rate2:
            logger.write("  -> ANOMALY CONFIRMED: Non-Repeatable Read occurred! (Value changed mid-transaction)\n")
        conn_a.commit()

    def thread_b():
        barrier_1.wait()
        cur_b.execute("BEGIN;")
        cur_b.execute("UPDATE seasonal_rate SET price_per_night = 48000.00 WHERE rate_id = 1;")
        cur_b.execute("COMMIT;")
        logger.write("  [Session B] Updated Rate to ₦48,000.00 and COMMITTED.\n")
        barrier_2.wait()

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    # Cleanup
    cur_a.execute("UPDATE seasonal_rate SET price_per_night = 35000.00 WHERE rate_id = 1;")
    conn_a.commit()
    cur_a.close()
    cur_b.close()
    conn_a.close()
    conn_b.close()


# ==============================================================================
# DEMONSTRATION 3: REPEATABLE READ -> SNAPSHOT ISOLATION & CONFLICT
# ==============================================================================
def demo_repeatable_read(logger):
    logger.write("\n" + "=" * 70 + "\n")
    logger.write("EXPERIMENT 3: REPEATABLE READ (SNAPSHOT ISOLATION & UPDATE CONFLICT)\n")
    logger.write("=" * 70 + "\n\n")

    conn_a = get_connection()
    conn_b = get_connection()
    cur_a = conn_a.cursor()
    cur_b = conn_b.cursor()

    cur_a.execute("UPDATE seasonal_rate SET price_per_night = 40000.00 WHERE rate_id = 1;")
    conn_a.commit()

    barrier_1 = threading.Barrier(2)
    barrier_2 = threading.Barrier(2)

    def thread_a():
        cur_a.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;")
        cur_a.execute("SELECT price_per_night FROM seasonal_rate WHERE rate_id = 1;")
        r1 = cur_a.fetchone()[0]
        logger.write(f"  [Session A @ REPEATABLE READ] Read 1: Rate = ₦{r1:,.2f}\n")
        
        barrier_1.wait() # Session B updates and commits
        barrier_2.wait()

        # Re-read: must see original snapshot
        cur_a.execute("SELECT price_per_night FROM seasonal_rate WHERE rate_id = 1;")
        r2 = cur_a.fetchone()[0]
        logger.write(f"  [Session A @ REPEATABLE READ] Read 2: Rate = ₦{r2:,.2f}\n")
        if r1 == r2:
            logger.write("  -> Non-repeatable read PREVENTED by Snapshot Isolation!\n")

        # Now attempt to update the row that Session B modified
        logger.write("  [Session A @ REPEATABLE READ] Attempting UPDATE on row modified by Session B...\n")
        try:
            cur_a.execute("UPDATE seasonal_rate SET price_per_night = price_per_night + 2000 WHERE rate_id = 1;")
            conn_a.commit()
        except psycopg.errors.SerializationFailure as e:
            logger.write(f"  -> SUCCESS: Caught expected SQLSTATE 40001:\n     {e.args[0].strip()}\n")
            conn_a.rollback()

    def thread_b():
        barrier_1.wait()
        cur_b.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;")
        cur_b.execute("UPDATE seasonal_rate SET price_per_night = 52000.00 WHERE rate_id = 1;")
        cur_b.execute("COMMIT;")
        logger.write("  [Session B] Concurrently updated rate to ₦52,000.00 and COMMITTED.\n")
        barrier_2.wait()

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    cur_a.execute("UPDATE seasonal_rate SET price_per_night = 40000.00 WHERE rate_id = 1;")
    conn_a.commit()
    cur_a.close()
    cur_b.close()
    conn_a.close()
    conn_b.close()


# ==============================================================================
# DEMONSTRATION 4: SERIALIZABLE -> WRITE SKEW DETECTION & RETRY LOOP
# ==============================================================================
def demo_serializable_retry_loop(logger):
    logger.write("\n" + "=" * 70 + "\n")
    logger.write("EXPERIMENT 4: SERIALIZABLE SNAPSHOT ISOLATION & AUTOMATED RETRY LOOP\n")
    logger.write("Business Rule: At least 1 emergency suite on floor 5 must remain active.\n")
    logger.write("Anomaly: Write Skew (both sessions check count=2 and concurrently deactivate one).\n")
    logger.write("=" * 70 + "\n\n")

    conn_admin = get_connection()
    cur_admin = conn_admin.cursor()

    # Setup: Ensure exactly 2 rooms on floor 5 of Hotel 1 are active
    cur_admin.execute("UPDATE room SET is_active = true WHERE room_id IN (81, 82);")
    conn_admin.commit()

    barrier_both_started = threading.Barrier(2)
    barrier_both_read = threading.Barrier(2)
    barrier_a_committed = threading.Event()

    def session_worker_a():
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
        barrier_both_started.wait()

        # Both sessions query the predicate concurrently
        cur.execute("SELECT COUNT(*) FROM room WHERE hotel_id = 1 AND floor = 5 AND is_active = true AND room_id IN (81, 82);")
        cnt = cur.fetchone()[0]
        logger.write(f"  [Agent A @ SERIALIZABLE] Checked emergency room pool: {cnt} active.\n")
        barrier_both_read.wait()

        # Agent A deactivates room 81
        cur.execute("UPDATE room SET is_active = false WHERE room_id = 81;")
        logger.write("  [Agent A @ SERIALIZABLE] Reserved room 81.\n")
        
        cur.execute("COMMIT;")
        logger.write("  [Agent A @ SERIALIZABLE] COMMITTED successfully.\n")
        barrier_a_committed.set()
        
        cur.close()
        conn.close()

    def session_worker_b():
        conn = get_connection()
        cur = conn.cursor()
        
        logger.write("  [Agent B @ SERIALIZABLE] (Attempt 1) Starting transaction...\n")
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
        barrier_both_started.wait()

        # Agent B reads the exact same predicate concurrently: sees 2 active!
        cur.execute("SELECT COUNT(*) FROM room WHERE hotel_id = 1 AND floor = 5 AND is_active = true AND room_id IN (81, 82);")
        cnt = cur.fetchone()[0]
        logger.write(f"  [Agent B @ SERIALIZABLE] Checked emergency room pool: {cnt} active.\n")
        barrier_both_read.wait()

        # Wait until Agent A has committed its change to establish the rw-dependency
        barrier_a_committed.wait()

        # Agent B now attempts to deactivate room 82 based on its earlier observation of cnt=2
        logger.write("  [Agent B @ SERIALIZABLE] Attempting to reserve room 82 and COMMIT...\n")
        try:
            cur.execute("UPDATE room SET is_active = false WHERE room_id = 82;")
            cur.execute("COMMIT;")
            logger.write("  [Agent B @ SERIALIZABLE] Committed.\n")
        except psycopg.errors.SerializationFailure as e:
            logger.write(f"  -> SUCCESS: Caught expected SQLSTATE 40001 (SSI Serialization Failure):\n     {e.args[0].strip()}\n")
            conn.rollback()
            
            # --- AUTOMATED RETRY LOOP ---
            logger.write("  -> [Agent B] Initiating automated RETRY loop (Attempt 2)...\n")
            time.sleep(0.1)
            
            # Fresh transaction
            cur.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
            cur.execute("SELECT COUNT(*) FROM room WHERE hotel_id = 1 AND floor = 5 AND is_active = true AND room_id IN (81, 82);")
            cnt_retry = cur.fetchone()[0]
            logger.write(f"  [Agent B @ SERIALIZABLE - RETRY] Re-checked emergency pool: {cnt_retry} active.\n")
            
            # Enforce invariant
            if cnt_retry <= 1:
                logger.write(f"  -> RETRY DECISION: Only {cnt_retry} room remaining! Invariant requires >= 1.\n")
                logger.write("  -> Reservation rejected gracefully without violating the business invariant!\n")
                cur.execute("ROLLBACK;")
            else:
                cur.execute("UPDATE room SET is_active = false WHERE room_id = 82;")
                cur.execute("COMMIT;")
        finally:
            cur.close()
            conn.close()

    t_a = threading.Thread(target=session_worker_a)
    t_b = threading.Thread(target=session_worker_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    # Verify final state
    cur_admin.execute("SELECT room_id, room_number, is_active FROM room WHERE room_id IN (81, 82) ORDER BY room_id;")
    res = cur_admin.fetchall()
    logger.write(f"\n--- FINAL VERIFICATION: POOL STATE PRESERVED ---\n")
    for rid, rnum, act in res:
        logger.write(f"  Room {rid} ({rnum}): is_active = {act}\n")
        
    active_remaining = sum(1 for _, _, a in res if a)
    logger.write(f"  Total Emergency Rooms Active: {active_remaining} (Invariant Maintained >= 1: {'PASS' if active_remaining >= 1 else 'FAIL'})\n")

    # Reset rooms
    cur_admin.execute("UPDATE room SET is_active = true WHERE room_id IN (81, 82);")
    conn_admin.commit()
    cur_admin.close()
    conn_admin.close()


def main():
    logger = Logger(OUTPUT_FILE)
    logger.write("=====================================================================\n")
    logger.write("PORTFOLIO 3: MULTI-SESSION ISOLATION LEVELS & ANOMALY HARNESS\n")
    logger.write(f"Database: {PG_DB} at {PG_HOST}:{PG_PORT}\n")
    logger.write("=====================================================================\n")

    demo_read_uncommitted(logger)
    demo_read_committed(logger)
    demo_repeatable_read(logger)
    demo_serializable_retry_loop(logger)

    logger.write("\n=====================================================================\n")
    logger.write(f"ALL ISOLATION TESTS COMPLETE. Evidence recorded to {OUTPUT_FILE}\n")
    logger.write("=====================================================================\n")
    logger.close()


if __name__ == "__main__":
    main()
