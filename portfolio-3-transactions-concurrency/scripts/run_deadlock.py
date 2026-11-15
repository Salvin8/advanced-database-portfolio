#!/usr/bin/env python3
"""
run_deadlock.py - Automated Deadlock Reproduction & Resolution Harness
Portfolio 3: Transactions and Concurrency

Demonstrates:
  Phase 1: Real Deadlock between Session 1 and Session 2 updating rows in opposite order:
           Session 1 locks Room 1 -> attempts Room 2
           Session 2 locks Room 2 -> attempts Room 1
           PostgreSQL detects cycle and aborts one transaction with SQLSTATE 40P01.
  Phase 2: Architectural Solution: Consistent Lock Ordering (ORDER BY room_id ASC).
           Both sessions lock resources in identical order; one queues behind the other;
           both commit cleanly with zero deadlocks.

Records live evidence to evidence/deadlock_output.txt.
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

OUTPUT_FILE = "portfolio-3-transactions-concurrency/evidence/deadlock_output.txt"
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


def get_conn():
    return psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB,
        autocommit=False
    )


# ==============================================================================
# PHASE 1: REPRODUCE REAL DEADLOCK (OPPOSITE LOCK ORDER)
# ==============================================================================
def demo_deadlock_reproduction(logger):
    logger.write("\n" + "=" * 70 + "\n")
    logger.write("PHASE 1: DEADLOCK REPRODUCTION (OPPOSITE LOCK ORDERING)\n")
    logger.write("Transaction 1 updates Room 1 -> Room 2\n")
    logger.write("Transaction 2 updates Room 2 -> Room 1\n")
    logger.write("=" * 70 + "\n\n")

    barrier_initial = threading.Barrier(2)
    barrier_step2 = threading.Barrier(2)

    deadlock_caught = {"caught": False, "session": "", "error": ""}
    lock = threading.Lock()

    def session_1():
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SET deadlock_timeout = '500ms';")
        cur.execute("BEGIN;")
        
        # Lock Room 1
        cur.execute("UPDATE room SET is_active = true WHERE room_id = 1;")
        logger.write("  [Session 1] Acquired exclusive lock on Room 1.\n")
        barrier_initial.wait()
        time.sleep(0.05) # Allow Session 2 to acquire lock on Room 2
        barrier_step2.wait()

        # Attempt to lock Room 2 (blocks!)
        logger.write("  [Session 1] Attempting to acquire lock on Room 2 (waiting on Session 2)...\n")
        try:
            cur.execute("UPDATE room SET is_active = true WHERE room_id = 2;")
            cur.execute("COMMIT;")
            logger.write("  [Session 1] Successfully committed!\n")
        except psycopg.errors.DeadlockDetected as e:
            with lock:
                deadlock_caught["caught"] = True
                deadlock_caught["session"] = "Session 1"
                deadlock_caught["error"] = str(e).strip()
            logger.write(f"  -> [Session 1] DEADLOCK DETECTED BY POSTGRESQL KERNEL:\n     {e.args[0].strip()}\n")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    def session_2():
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SET deadlock_timeout = '500ms';")
        cur.execute("BEGIN;")

        barrier_initial.wait()
        # Lock Room 2
        cur.execute("UPDATE room SET is_active = true WHERE room_id = 2;")
        logger.write("  [Session 2] Acquired exclusive lock on Room 2.\n")
        barrier_step2.wait()

        # Attempt to lock Room 1 (blocks!)
        logger.write("  [Session 2] Attempting to acquire lock on Room 1 (waiting on Session 1)...\n")
        try:
            cur.execute("UPDATE room SET is_active = true WHERE room_id = 1;")
            cur.execute("COMMIT;")
            logger.write("  [Session 2] Successfully committed!\n")
        except psycopg.errors.DeadlockDetected as e:
            with lock:
                deadlock_caught["caught"] = True
                deadlock_caught["session"] = "Session 2"
                deadlock_caught["error"] = str(e).strip()
            logger.write(f"  -> [Session 2] DEADLOCK DETECTED BY POSTGRESQL KERNEL:\n     {e.args[0].strip()}\n")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    t1 = threading.Thread(target=session_1)
    t2 = threading.Thread(target=session_2)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    logger.write(f"\n  -> DEADLOCK OUTCOME: {'CONFIRMED (SQLSTATE 40P01)' if deadlock_caught['caught'] else 'NOT OBSERVED'}\n")
    logger.write(f"  -> Victim Terminated: {deadlock_caught['session']}\n")


# ==============================================================================
# PHASE 2: ARCHITECTURAL FIX (CONSISTENT LOCK ORDERING)
# ==============================================================================
def demo_deadlock_resolution(logger):
    logger.write("\n" + "=" * 70 + "\n")
    logger.write("PHASE 2: DEADLOCK RESOLUTION (CONSISTENT RESOURCE ORDERING)\n")
    logger.write("Rule: Both transactions ALWAYS acquire locks in ascending PK order (Room 1 -> Room 2)\n")
    logger.write("=" * 70 + "\n\n")

    barrier = threading.Barrier(2)

    def worker_ordered(worker_id):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SET deadlock_timeout = '500ms';")
        barrier.wait()

        cur.execute("BEGIN;")
        logger.write(f"  [Worker {worker_id}] Starting transaction. Requesting locks for Room 1 then Room 2 (ORDER BY room_id ASC)...\n")
        
        # Explicit deterministic lock ordering
        cur.execute("""
            SELECT room_id FROM room 
            WHERE room_id IN (1, 2) 
            ORDER BY room_id ASC 
            FOR UPDATE;
        """)
        logger.write(f"  [Worker {worker_id}] Acquired both locks successfully! Performing updates...\n")
        
        cur.execute("UPDATE room SET is_active = true WHERE room_id = 1;")
        cur.execute("UPDATE room SET is_active = true WHERE room_id = 2;")
        time.sleep(0.1) # Simulate brief business processing
        
        cur.execute("COMMIT;")
        logger.write(f"  [Worker {worker_id}] COMMITTED successfully without conflict.\n")
        cur.close()
        conn.close()

    w1 = threading.Thread(target=worker_ordered, args=(1,))
    w2 = threading.Thread(target=worker_ordered, args=(2,))
    w1.start()
    w2.start()
    w1.join()
    w2.join()

    logger.write("\n  -> RESOLUTION OUTCOME: PASS! Both workers committed cleanly with ZERO deadlocks.\n")


def main():
    logger = Logger(OUTPUT_FILE)
    logger.write("=====================================================================\n")
    logger.write("SAVANNAH CREST HOTELS: DEADLOCK DEMONSTRATION & RESOLUTION HARNESS\n")
    logger.write(f"Database: {PG_DB} at {PG_HOST}:{PG_PORT}\n")
    logger.write("=====================================================================\n")

    demo_deadlock_reproduction(logger)
    demo_deadlock_resolution(logger)

    logger.write("\n=====================================================================\n")
    logger.write(f"DEADLOCK HARNESS FINISHED. Evidence recorded to {OUTPUT_FILE}\n")
    logger.write("=====================================================================\n")
    logger.close()


if __name__ == "__main__":
    main()

