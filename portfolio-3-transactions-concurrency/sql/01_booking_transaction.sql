-- =============================================================================
-- 01_booking_transaction.sql
-- Savannah Crest Hotels: Complete ACID Booking Transaction & Stored Procedure
-- Portfolio 3: Transactions and Concurrency
--
-- Demonstrates:
--   1. An atomic, multi-step booking transaction that COMMITS successfully.
--   2. Explicit row locking (SELECT ... FOR UPDATE) to prevent race conditions.
--   3. Cross-table consistency: booking header, booking_room, payment, and audit.
--   4. An enterprise PL/pgSQL stored procedure with robust EXCEPTION handling.
--
-- Run with:
--   docker compose exec -T postgres psql -U hotel_admin -d savannah_crest \
--     < portfolio-3-transactions-concurrency/sql/01_booking_transaction.sql \
--     > portfolio-3-transactions-concurrency/evidence/01_booking_transaction_output.txt 2>&1
-- =============================================================================

\echo '====================================================================='
\echo 'PORTFOLIO 3: COMPLETE ATOMIC BOOKING TRANSACTION (COMMIT)'
\echo '====================================================================='
\echo ''

\timing on

-- -----------------------------------------------------------------------------
-- Pre-Transaction State Check
-- -----------------------------------------------------------------------------
\echo '--- 1. VERIFY PRE-TRANSACTION STATE ---'
SELECT COUNT(*) AS existing_target_bookings 
FROM booking 
WHERE booking_ref = 'TX-CONFIRMED-2027';

-- -----------------------------------------------------------------------------
-- ATOMIC TRANSACTION: Complete Multi-Table Booking Flow
-- -----------------------------------------------------------------------------
\echo ''
\echo '--- 2. EXECUTING ATOMIC TRANSACTION (BEGIN ... COMMIT) ---'

BEGIN;

-- Step 2.1: Check room existence and lock the room row against concurrent modification
-- Room 1 is Room 101 at Savannah Crest Abuja
SELECT room_id, hotel_id, room_number, floor, is_active
FROM room
WHERE room_id = 1 AND is_active = true
FOR UPDATE;

-- Step 2.2: Verify room has no overlapping active booking for target stay: 2027-03-01 to 2027-03-05
-- If COUNT > 0, application would roll back; exclusion constraint acts as the kernel-level safety net.
SELECT COUNT(*) AS conflict_count
FROM booking_room
WHERE room_id = 1
  AND status IN ('reserved', 'checked_in')
  AND stay && daterange('2027-03-01', '2027-03-05', '[)');

-- Step 2.3: Insert booking header (Total: 4 nights @ ₦45,000 = ₦180,000)
INSERT INTO booking (
    booking_id, guest_id, hotel_id, booking_ref, status, 
    booking_date, total_amount, notes
) VALUES (
    700001, 1, 1, 'TX-CONFIRMED-2027', 'pending', 
    now(), 180000.00, 'VIP Corporate Booking via Web Portal'
) RETURNING booking_id, booking_ref, status, total_amount;

-- Step 2.4: Insert booking_room stay assignment
INSERT INTO booking_room (
    booking_room_id, booking_id, room_id, check_in_date, check_out_date, 
    rate_per_night, num_guests, status
) VALUES (
    700001, 700001, 1, '2027-03-01', '2027-03-05', 
    45000.00, 2, 'reserved'
) RETURNING booking_room_id, booking_id, room_id, check_in_date, check_out_date, stay, status;

-- Step 2.5: Process and record completed financial transaction
INSERT INTO payment (
    payment_id, booking_id, amount, payment_method, 
    payment_status, transaction_ref, payment_date
) VALUES (
    700001, 700001, 180000.00, 'card', 
    'completed', 'TXN-CARD-2027-001', now()
) RETURNING payment_id, booking_id, amount, payment_method, payment_status, transaction_ref;

-- Step 2.6: Confirm booking status (fires audit trigger)
UPDATE booking 
SET status = 'confirmed', updated_at = now() 
WHERE booking_id = 700001
RETURNING booking_id, booking_ref, status;

-- Step 2.7: Record housekeeping status reservation flag
INSERT INTO room_status_history (
    room_id, status, changed_by, changed_at, notes
) VALUES (
    1, 'inspected', 1, now(), 'Pre-stay inspection confirmed for TX-CONFIRMED-2027'
) RETURNING status_id, room_id, status, notes;

COMMIT;

\echo ''
\echo '--- 3. VERIFY POST-TRANSACTION PERSISTED STATE ---'

SELECT 
    b.booking_id,
    b.booking_ref,
    b.status AS booking_status,
    b.total_amount,
    br.room_id,
    br.check_in_date,
    br.check_out_date,
    br.stay,
    p.amount AS amount_paid,
    p.payment_status,
    p.transaction_ref
FROM booking b
JOIN booking_room br ON b.booking_id = br.booking_id
JOIN payment p ON b.booking_id = p.booking_id
WHERE b.booking_ref = 'TX-CONFIRMED-2027';

\echo ''
\echo '--- 4. VERIFY AUTOMATIC AUDIT TRIGGER CAPTURE ---'
SELECT log_id, table_name, record_id, action, 
       old_values->>'status' AS old_status, 
       new_values->>'status' AS new_status, 
       changed_by, changed_at
FROM audit_log
WHERE table_name = 'booking' AND record_id = 700001;


-- =============================================================================
-- PL/pgSQL STORED PROCEDURE: Enterprise Booking Flow with Exception Handling
-- =============================================================================
\echo ''
\echo '====================================================================='
\echo 'PART 2: ENTERPRISE STORED PROCEDURE WITH EXCEPTION HANDLING'
\echo '====================================================================='

CREATE OR REPLACE PROCEDURE sp_make_reservation(
    p_guest_id        INT,
    p_hotel_id        INT,
    p_room_id         INT,
    p_check_in        DATE,
    p_check_out       DATE,
    p_rate_per_night  NUMERIC(12,2),
    p_num_guests      INT,
    p_payment_method  VARCHAR(20),
    p_booking_ref     VARCHAR(20),
    INOUT p_booking_id INT DEFAULT NULL,
    INOUT p_status    TEXT DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_nights INT;
    v_total_amount NUMERIC(12,2);
    v_payment_id INT;
BEGIN
    -- Validate date sequence
    IF p_check_out <= p_check_in THEN
        RAISE EXCEPTION 'INVALID_DATES: Check-out date (%) must be after check-in date (%)', p_check_out, p_check_in
            USING ERRCODE = '22023';
    END IF;

    -- Calculate total duration and charge
    v_nights := p_check_out - p_check_in;
    v_total_amount := p_rate_per_night * v_nights;

    -- Validate room belongs to specified hotel
    PERFORM 1 FROM room WHERE room_id = p_room_id AND hotel_id = p_hotel_id AND is_active = true;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ROOM_UNAVAILABLE: Room % does not exist at Hotel % or is inactive', p_room_id, p_hotel_id
            USING ERRCODE = '22000';
    END IF;

    -- Insert Booking Header
    INSERT INTO booking (guest_id, hotel_id, booking_ref, status, total_amount, notes)
    VALUES (p_guest_id, p_hotel_id, p_booking_ref, 'pending', v_total_amount, 'Booked via stored procedure')
    RETURNING booking_id INTO p_booking_id;

    -- Insert Room Assignment (Subject to Exclusion Constraint)
    INSERT INTO booking_room (booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
    VALUES (p_booking_id, p_room_id, p_check_in, p_check_out, p_rate_per_night, p_num_guests, 'reserved');

    -- Insert Payment Transaction
    INSERT INTO payment (booking_id, amount, payment_method, payment_status, transaction_ref)
    VALUES (p_booking_id, v_total_amount, p_payment_method, 'completed', 'TXN-SP-' || p_booking_ref)
    RETURNING payment_id INTO v_payment_id;

    -- Update Booking to confirmed (fires audit trigger)
    UPDATE booking SET status = 'confirmed' WHERE booking_id = p_booking_id;

    p_status := 'SUCCESS: Booking Confirmed';
    RAISE NOTICE 'Booking % created successfully for room % (Total: ₦%)', p_booking_ref, p_room_id, v_total_amount;

EXCEPTION
    WHEN exclusion_violation THEN
        p_status := 'FAILED: Room already booked for requested dates (Exclusion Violation)';
        RAISE NOTICE 'Conflict detected: Room % is occupied between % and %', p_room_id, p_check_in, p_check_out;
        p_booking_id := NULL;
    WHEN check_violation THEN
        p_status := 'FAILED: Business rule violation (' || SQLERRM || ')';
        RAISE NOTICE 'Check constraint failed: %', SQLERRM;
        p_booking_id := NULL;
    WHEN OTHERS THEN
        p_status := 'FAILED: Unexpected error (' || SQLERRM || ')';
        RAISE NOTICE 'Transaction aborted: % (SQLSTATE: %)', SQLERRM, SQLSTATE;
        p_booking_id := NULL;
END;
$$;

\echo ''
\echo '--- 5. TESTING STORED PROCEDURE (VALID EXECUTION) ---'
DO $$
DECLARE
    v_b_id INT;
    v_msg TEXT;
BEGIN
    CALL sp_make_reservation(
        p_guest_id        => 2,
        p_hotel_id        => 1,
        p_room_id         => 2,
        p_check_in        => '2027-04-10',
        p_check_out       => '2027-04-14',
        p_rate_per_night  => 45000.00,
        p_num_guests      => 2,
        p_payment_method  => 'bank_transfer',
        p_booking_ref     => 'TX-SP-2027-001',
        p_booking_id      => v_b_id,
        p_status          => v_msg
    );
    RAISE NOTICE 'Procedure Return -> ID: %, Result: %', v_b_id, v_msg;
END $$;

\echo ''
\echo '--- 6. TESTING STORED PROCEDURE CONFLICT HANDLING (OVERLAPPING DATES) ---'
DO $$
DECLARE
    v_b_id INT;
    v_msg TEXT;
BEGIN
    -- Attempting to book room 2 on overlapping dates 2027-04-12 to 2027-04-16
    CALL sp_make_reservation(
        p_guest_id        => 3,
        p_hotel_id        => 1,
        p_room_id         => 2,
        p_check_in        => '2027-04-12',
        p_check_out       => '2027-04-16',
        p_rate_per_night  => 45000.00,
        p_num_guests      => 1,
        p_payment_method  => 'card',
        p_booking_ref     => 'TX-SP-CONFLICT',
        p_booking_id      => v_b_id,
        p_status          => v_msg
    );
    RAISE NOTICE 'Procedure Return -> ID: %, Result: %', v_b_id, v_msg;
END $$;
