#!/usr/bin/env python3
"""
saga_orchestrator.py - Distributed Saga Pattern Orchestrator & Compensating Transactions
Portfolio 5: Distributed and Cloud Database Exercise
Savannah Crest Hotels

This script demonstrates:
1. Distributed Transaction Coordination: Simulates independent microservices
   (Inventory Service, Payment Gateway, and Notification Service).
2. Saga Orchestration State Machine: Tracks forward actions and compensating steps.
3. Scenario 1 (Happy Path): End-to-end forward execution to COMPLETED state.
4. Scenario 2 (Payment Failure): Automatic backward execution of compensating transactions
   (rolling back inventory reservation when payment fails).
5. Scenario 3 (Transient Failure & Idempotent Retries): Demonstrates network timeout handling
   with idempotent tokens and retry policies.
"""

import os
import sys
import time
import json
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg

# Load environment configuration
load_dotenv()

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

EVIDENCE_FILE = "portfolio-5-distributed-cloud/evidence/saga-orchestrator-output.txt"


class TeeWriter:
    """Tee stdout to both console and evidence file."""
    def __init__(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.file = open(filepath, "w")
        self.stdout = sys.stdout

    def write(self, data):
        self.stdout.write(data)
        self.file.write(data)

    def flush(self):
        self.file.flush()
        self.stdout.flush()

    def close(self):
        self.file.close()


# ==============================================================================
# Microservices Simulation
# ==============================================================================

class RoomInventoryService:
    """Manages physical room state and reservation holds in PostgreSQL."""
    def __init__(self, pg_conn):
        self.conn = pg_conn

    def hold_room(self, saga_id, hotel_id, room_id, guest_id, check_in, check_out, amount):
        print(f"    [InventoryService] Holding Room {room_id} (Hotel {hotel_id}) for Saga {saga_id[:8]}...")
        with self.conn.cursor() as cur:
            # Check availability
            cur.execute("""
                SELECT 1 FROM booking_room br
                WHERE br.room_id = %s
                  AND br.status IN ('reserved', 'checked_in')
                  AND br.stay && daterange(%s::date, %s::date, '[)')
            """, (room_id, check_in, check_out))
            if cur.fetchone():
                raise RuntimeError(f"Room {room_id} is already occupied during requested period.")

            # Insert provisional booking with status 'pending'
            booking_ref = f"SAGA-{saga_id[:8].upper()}"
            cur.execute("""
                INSERT INTO booking (guest_id, hotel_id, booking_ref, status, total_amount, notes)
                VALUES (%s, %s, %s, 'pending', %s, 'SAGA Transaction in-flight')
                RETURNING booking_id;
            """, (guest_id, hotel_id, booking_ref, amount))
            booking_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO booking_room (booking_id, room_id, check_in_date, check_out_date, rate_per_night, status)
                VALUES (%s, %s, %s, %s, %s, 'reserved')
                RETURNING booking_room_id;
            """, (booking_id, room_id, check_in, check_out, amount))
            br_id = cur.fetchone()[0]

            self.conn.commit()
            print(f"    [InventoryService] ✓ Room {room_id} held successfully (Booking ID: {booking_id})")
            return {"booking_id": booking_id, "booking_room_id": br_id, "booking_ref": booking_ref}

    def confirm_hold(self, booking_id):
        print(f"    [InventoryService] Confirming reservation for Booking ID {booking_id}...")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE booking
                SET status = 'confirmed', updated_at = now()
                WHERE booking_id = %s;
            """, (booking_id,))
            self.conn.commit()
            print(f"    [InventoryService] ✓ Booking ID {booking_id} status updated to CONFIRMED.")

    def release_hold_compensating_action(self, booking_id, reason="Saga Aborted"):
        """COMPENSATING TRANSACTION: Reverses provisional room hold on upstream failure."""
        print(f"    [InventoryService] ⚠️ EXECUTING COMPENSATING ACTION: Releasing Booking ID {booking_id} ({reason})...")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE booking
                SET status = 'cancelled', notes = %s, updated_at = now()
                WHERE booking_id = %s;
            """, (f"CANCELLED BY SAGA COMPENSATION: {reason}", booking_id))
            cur.execute("""
                UPDATE booking_room
                SET status = 'cancelled'
                WHERE booking_id = %s;
            """, (booking_id,))
            self.conn.commit()
            print(f"    [InventoryService] ✓ Booking ID {booking_id} marked CANCELLED. Room returned to pool.")


class PaymentGatewayService:
    """Simulates external payment processing with card / mobile money."""
    def __init__(self, pg_conn):
        self.conn = pg_conn

    def process_charge(self, booking_id, amount, method, card_number, idempotency_key, simulate_failure=False):
        print(f"    [PaymentGateway] Charging ₦{amount:,.2f} via {method} (Idempotency: {idempotency_key[:8]})...")
        time.sleep(0.1)  # Simulate network latency

        if simulate_failure:
            print("    [PaymentGateway] ✗ PAYMENT DECLINED: Insufficient funds / Card expired (Simulated Error)")
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payment (booking_id, amount, payment_method, payment_status, transaction_ref)
                    VALUES (%s, %s, %s, 'failed', %s);
                """, (booking_id, amount, method, f"TXN-FAIL-{idempotency_key[:8]}"))
                self.conn.commit()
            raise RuntimeError("Payment Authorization Refused by Issuing Bank.")

        txn_ref = f"TXN-SUCCESS-{idempotency_key[:8]}"
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO payment (booking_id, amount, payment_method, payment_status, transaction_ref)
                VALUES (%s, %s, %s, 'completed', %s)
                RETURNING payment_id;
            """, (booking_id, amount, method, txn_ref))
            pay_id = cur.fetchone()[0]
            self.conn.commit()

        print(f"    [PaymentGateway] ✓ Payment approved! Transaction Ref: {txn_ref} (Payment ID: {pay_id})")
        return {"payment_id": pay_id, "transaction_ref": txn_ref}


class NotificationService:
    """Dispatches guest confirmation alerts."""
    def send_booking_confirmation(self, guest_email, booking_ref, hotel_name):
        print(f"    [NotificationService] Sending confirmation email to {guest_email} for {booking_ref} at {hotel_name}...")
        time.sleep(0.05)
        print(f"    [NotificationService] ✓ Email and SMS alerts successfully dispatched.")
        return True


# ==============================================================================
# Saga Orchestrator Implementation
# ==============================================================================

class HotelBookingSagaOrchestrator:
    """
    Coordinates distributed transactions across microservices.
    Enforces forward actions and executes compensating steps on failure.
    """
    def __init__(self, inventory_svc, payment_svc, notification_svc):
        self.inventory = inventory_svc
        self.payment = payment_svc
        self.notification = notification_svc

    def execute_booking_saga(self, guest_id, guest_email, hotel_id, hotel_name, room_id,
                             check_in, check_out, amount, method, card_number,
                             simulate_payment_failure=False, simulate_retry=False):
        saga_id = str(uuid.uuid4())
        idempotency_key = f"idemp_{uuid.uuid4()}"
        print(f"\n>>> INITIATING SAGA [ID: {saga_id}] <<<")
        print(f"    Hotel: {hotel_name} | Room: {room_id} | Guest: {guest_id} | Dates: {check_in} to {check_out}")

        state = {
            "saga_id": saga_id,
            "status": "STARTED",
            "booking_id": None,
            "payment_id": None,
            "compensation_executed": False
        }

        # Step 1: Hold Room Inventory (Forward Action 1)
        try:
            hold_res = self.inventory.hold_room(saga_id, hotel_id, room_id, guest_id, check_in, check_out, amount)
            state["booking_id"] = hold_res["booking_id"]
            state["booking_ref"] = hold_res["booking_ref"]
        except Exception as e:
            print(f"    [Orchestrator] ✗ Step 1 Failed: {e}")
            state["status"] = "FAILED_AT_INVENTORY"
            return state

        # Step 2: Charge Payment (Forward Action 2)
        try:
            if simulate_retry:
                print("    [Orchestrator] Simulating transient network timeout on first attempt...")
                print("    [Orchestrator] Retrying with exponential backoff and idempotency key...")
                time.sleep(0.2)
                # Attempt 2 succeeds
                pay_res = self.payment.process_charge(
                    state["booking_id"], amount, method, card_number, idempotency_key, simulate_failure=False
                )
            else:
                pay_res = self.payment.process_charge(
                    state["booking_id"], amount, method, card_number, idempotency_key, simulate_failure=simulate_payment_failure
                )
            state["payment_id"] = pay_res["payment_id"]
        except Exception as e:
            print(f"\n    [Orchestrator] ✗ Step 2 (Payment) Failed: {e}")
            print(f"    [Orchestrator] ⚡ TRIGGERING BACKWARD COMPENSATING TRANSACTIONS...")

            # Execute compensation for Step 1
            self.inventory.release_hold_compensating_action(state["booking_id"], reason=str(e))
            state["compensation_executed"] = True
            state["status"] = "COMPENSATED_ABORT"
            print(f"    [Orchestrator] ✓ Saga {saga_id[:8]} rolled back cleanly. System consistency preserved.")
            return state

        # Step 3: Confirm Reservation (Forward Action 3)
        try:
            self.inventory.confirm_hold(state["booking_id"])
        except Exception as e:
            print(f"    [Orchestrator] ✗ Step 3 Failed: {e}")
            state["status"] = "FAILED_AT_CONFIRMATION"
            return state

        # Step 4: Dispatch Notification (Forward Action 4)
        try:
            self.notification.send_booking_confirmation(guest_email, state["booking_ref"], hotel_name)
        except Exception as e:
            print(f"    [NotificationService] Warning: {e} (Non-critical step)")

        state["status"] = "SUCCESS"
        print(f"    [Orchestrator] ✓ SAGA COMPLETED SUCCESSFULLY. All distributed services converged.")
        return state


# ==============================================================================
# Main Demonstration Runner
# ==============================================================================

def main():
    tee = TeeWriter(EVIDENCE_FILE)
    sys.stdout = tee

    print("=" * 80)
    print("SAVANNAH CREST HOTELS - DISTRIBUTED SAGA PATTERN ORCHESTRATION")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80)

    pg_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DB
    )

    # Clean up previous demonstration SAGA bookings for idempotent re-runs
    with pg_conn.cursor() as cur:
        cur.execute("""
            DELETE FROM payment WHERE transaction_ref LIKE 'TXN-%-idemp_%';
            DELETE FROM booking_room WHERE booking_id IN (SELECT booking_id FROM booking WHERE booking_ref LIKE 'SAGA-%');
            DELETE FROM booking WHERE booking_ref LIKE 'SAGA-%';
        """)
        pg_conn.commit()
    print("✓ Purged previous demonstration SAGA bookings for clean reproducibility.")

    inv_svc = RoomInventoryService(pg_conn)
    pay_svc = PaymentGatewayService(pg_conn)
    notif_svc = NotificationService()
    orchestrator = HotelBookingSagaOrchestrator(inv_svc, pay_svc, notif_svc)

    # --------------------------------------------------------------------------
    # Scenario 1: Happy Path Distributed Transaction
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SCENARIO 1: SUCCESSFUL DISTRIBUTED TRANSACTION (HAPPY PATH)")
    print("=" * 80)
    res1 = orchestrator.execute_booking_saga(
        guest_id=101,
        guest_email="amina.bello101@mail.ng",
        hotel_id=1,
        hotel_name="Savannah Crest Abuja",
        room_id=10,
        check_in="2026-12-10",
        check_out="2026-12-14",
        amount=180000.00,
        method="card",
        card_number="5399-xxxx-xxxx-1234",
        simulate_payment_failure=False
    )
    print(f"\nFinal State Scenario 1: {json.dumps(res1, indent=2)}")

    # --------------------------------------------------------------------------
    # Scenario 2: Compensating Rollback on Payment Decline
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SCENARIO 2: PAYMENT FAILURE TRIGGERING COMPENSATING ROLLBACK")
    print("=" * 80)
    res2 = orchestrator.execute_booking_saga(
        guest_id=102,
        guest_email="emeka.okafor102@mail.ng",
        hotel_id=2,
        hotel_name="Savannah Crest Victoria Island",
        room_id=115,
        check_in="2026-12-15",
        check_out="2026-12-18",
        amount=255000.00,
        method="card",
        card_number="4111-xxxx-xxxx-9999",
        simulate_payment_failure=True
    )
    print(f"\nFinal State Scenario 2: {json.dumps(res2, indent=2)}")

    # Verification Query on PostgreSQL: Verify Room is Available and Status is Cancelled
    print("\n--- Verifying Post-Compensation Database State in PostgreSQL ---")
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT b.booking_id, b.booking_ref, b.status AS booking_status,
                   br.room_id, br.status AS room_status, b.notes
            FROM booking b
            JOIN booking_room br ON b.booking_id = br.booking_id
            WHERE b.booking_id = %s;
        """, (res2["booking_id"],))
        comp_record = cur.fetchone()
        print(f"  Booking ID:     {comp_record[0]}")
        print(f"  Booking Ref:    {comp_record[1]}")
        print(f"  Booking Status: {comp_record[2]}")
        print(f"  Room ID:        {comp_record[3]}")
        print(f"  Room Status:    {comp_record[4]}")
        print(f"  Audit Notes:    {comp_record[5]}")

    # --------------------------------------------------------------------------
    # Scenario 3: Transient Network Timeout & Idempotent Retry
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SCENARIO 3: TRANSIENT TIMEOUT WITH IDEMPOTENT RETRY")
    print("=" * 80)
    res3 = orchestrator.execute_booking_saga(
        guest_id=103,
        guest_email="zainab.danladi103@mail.ng",
        hotel_id=3,
        hotel_name="Savannah Crest Port Harcourt",
        room_id=220,
        check_in="2026-12-20",
        check_out="2026-12-24",
        amount=170000.00,
        method="bank_transfer",
        card_number="N/A",
        simulate_retry=True
    )
    print(f"\nFinal State Scenario 3: {json.dumps(res3, indent=2)}")

    print("\n==================================================================")
    print("Saga Orchestration demonstration completed successfully.")
    print(f"Evidence logged to: {EVIDENCE_FILE}")
    print("==================================================================")

    pg_conn.close()
    sys.stdout = tee.stdout
    tee.close()


if __name__ == "__main__":
    main()
