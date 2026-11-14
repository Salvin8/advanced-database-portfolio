-- =============================================================================
-- 02_rollback_scenarios.sql
-- Savannah Crest Hotels: Transaction Rollback & SAVEPOINT Failure Scenarios
-- Portfolio 3: Transactions and Concurrency
--
-- Demonstrates:
--   Scenario A: Payment failure mid-transaction triggering application ROLLBACK.
--               Proves ATOMICITY: zero partial or orphan booking records survive.
--   Scenario B: Database constraint violation inside an open transaction.
--               Shows PostgreSQL error recovery and mandatory transaction abort.
--   Scenario C: Nested transactions via SAVEPOINT and ROLLBACK TO SAVEPOINT.
--               Demonstrates partial failure recovery (optional add-on fails,
--               core room booking is preserved and committed).
--
-- Run with:
--   docker compose exec -T postgres psql -U hotel_admin -d savannah_crest \
--     < portfolio-3-transactions-concurrency/sql/02_rollback_scenarios.sql \
--     > portfolio-3-transactions-concurrency/evidence/02_rollback_scenarios_output.txt 2>&1
-- =============================================================================

\echo '====================================================================='
\echo 'PORTFOLIO 3: TRANSACTION ROLLBACK & SAVEPOINT SCENARIOS'
\echo '====================================================================='
\echo ''

\timing on

-- =============================================================================
-- SCENARIO A: Payment Failure Mid-Transaction (Application-Triggered ROLLBACK)
-- =============================================================================
-- Business Context:
--   Guest Amaka attempts to book Room 102 for Easter 2027.
--   The booking header and room assignment are prepared in the database.
--   When attempting to charge the credit card, the payment gateway returns
--   'DECLINED_INSUFFICIENT_FUNDS'.
--   The application issues an explicit ROLLBACK.
-- Expected Result:
--   Atomicity guarantees that NO partial booking or booking_room record survives.
-- =============================================================================
\echo '---------------------------------------------------------------------'
\echo 'SCENARIO A: PAYMENT FAILURE MID-TRANSACTION (APPLICATION ROLLBACK)'
\echo '---------------------------------------------------------------------'

-- Pre-verification: Ensure reference does not exist
SELECT COUNT(*) AS count_before 
FROM booking 
WHERE booking_ref = 'TX-FAIL-PAYMENT';

BEGIN;

-- Step A.1: Insert booking header
INSERT INTO booking (
    booking_id, guest_id, hotel_id, booking_ref, status, total_amount, notes
) VALUES (
    700002, 1, 1, 'TX-FAIL-PAYMENT', 'pending', 90000.00, 'Attempting card payment'
);

-- Step A.2: Insert booking_room assignment
INSERT INTO booking_room (
    booking_room_id, booking_id, room_id, check_in_date, check_out_date, 
    rate_per_night, num_guests, status
) VALUES (
    700002, 700002, 2, '2027-04-01', '2027-04-03', 45000.00, 1, 'reserved'
);

-- Step A.3: Simulate Payment Gateway Interaction
-- The external payment gateway declines the card transaction.
-- The application receives HTTP 402 Payment Required and aborts the flow.
\echo '>> External Payment Gateway Error: Card declined (insufficient funds).'
\echo '>> Application issuing explicit ROLLBACK...'

ROLLBACK;

-- Post-verification: Confirm zero records were written
\echo ''
\echo '--- VERIFYING SCENARIO A: ZERO PARTIAL RECORDS PERSISTED ---'
SELECT 
    (SELECT COUNT(*) FROM booking WHERE booking_ref = 'TX-FAIL-PAYMENT') AS booking_header_count,
    (SELECT COUNT(*) FROM booking_room WHERE booking_id = 700002) AS booking_room_count,
    (SELECT COUNT(*) FROM payment WHERE booking_id = 700002) AS payment_count;


-- =============================================================================
-- SCENARIO B: Constraint Violation Inside Transaction (PostgreSQL Abort)
-- =============================================================================
-- Business Context:
--   An application initiates a transaction to book room 3.
--   Step B.2 attempts to violate a CHECK constraint (negative payment amount).
--   PostgreSQL invalidates the transaction state.
--   Subsequent commands are rejected until ROLLBACK cleanses the session.
-- =============================================================================
\echo ''
\echo '---------------------------------------------------------------------'
\echo 'SCENARIO B: CONSTRAINT VIOLATION INSIDE TRANSACTION'
\echo '---------------------------------------------------------------------'

BEGIN;

-- Step B.1: Valid insert of booking header
INSERT INTO booking (
    booking_id, guest_id, hotel_id, booking_ref, status, total_amount
) VALUES (
    700003, 1, 1, 'TX-FAIL-CONSTRAINT', 'pending', 100000.00
);

-- Step B.2: Insert invalid negative payment (Violates payment_amount_check)
\echo '>> Attempting invalid INSERT with negative payment (-50000)...'
INSERT INTO payment (
    payment_id, booking_id, amount, payment_method, payment_status, transaction_ref
) VALUES (
    700003, 700003, -50000.00, 'card', 'completed', 'TXN-FAIL-001'
);

-- Step B.3: Attempting any further command inside an aborted transaction
\echo '>> Attempting to execute another statement in the aborted transaction block...'
SELECT 1;

-- Step B.4: Cleanse the transaction state
\echo '>> Issuing ROLLBACK to exit aborted transaction state...'
ROLLBACK;

-- Post-verification: Confirm entire transaction was rolled back
\echo ''
\echo '--- VERIFYING SCENARIO B: TRANSACTION WAS COMPLETELY REVERTED ---'
SELECT COUNT(*) AS booking_after_constraint_failure 
FROM booking 
WHERE booking_ref = 'TX-FAIL-CONSTRAINT';


-- =============================================================================
-- SCENARIO C: Partial Failure Recovery with SAVEPOINT & ROLLBACK TO SAVEPOINT
-- =============================================================================
-- Business Context:
--   Guest Tunde books a room for 2027-05-10 to 2027-05-14 (Core Booking).
--   Guest also requests an optional luxury airport shuttle add-on.
--   We establish a SAVEPOINT after the core booking.
--   The airport shuttle sub-operation fails (simulated constraint violation).
--   The application rolls back to the savepoint, discarding the failed shuttle,
--   while preserving and committing the core room reservation!
-- =============================================================================
\echo ''
\echo '---------------------------------------------------------------------'
\echo 'SCENARIO C: PARTIAL RECOVERY WITH SAVEPOINT'
\echo '---------------------------------------------------------------------'

BEGIN;

-- Step C.1: Core Room Reservation
INSERT INTO booking (
    booking_id, guest_id, hotel_id, booking_ref, status, total_amount, notes
) VALUES (
    700004, 2, 1, 'TX-SAVEPOINT-CORE', 'pending', 180000.00, 'Core reservation'
);

INSERT INTO booking_room (
    booking_room_id, booking_id, room_id, check_in_date, check_out_date, 
    rate_per_night, num_guests, status
) VALUES (
    700004, 700004, 3, '2027-05-10', '2027-05-14', 45000.00, 2, 'reserved'
);

INSERT INTO payment (
    payment_id, booking_id, amount, payment_method, payment_status, transaction_ref
) VALUES (
    700004, 700004, 180000.00, 'bank_transfer', 'completed', 'TXN-CORE-PAID'
);

\echo '>> Core room booking succeeded. Establishing SAVEPOINT sp_core_booking...'
SAVEPOINT sp_core_booking;

-- Step C.2: Attempt Optional Add-On (Simulate invalid add-on service)
\echo '>> Attempting to add optional service with invalid check constraint...'
DO $$
BEGIN
    -- Sub-block attempting invalid add-on payment
    INSERT INTO payment (
        booking_id, amount, payment_method, payment_status, transaction_ref
    ) VALUES (
        700004, -15000.00, 'cash', 'completed', 'TXN-SHUTTLE-FAIL'
    );
EXCEPTION
    WHEN check_violation THEN
        RAISE NOTICE 'Caught expected add-on check violation: %', SQLERRM;
END $$;

-- If an unhandled sub-operation fails, we can rollback directly to savepoint:
-- (Let's demonstrate explicit savepoint rollback)
SAVEPOINT sp_optional_service;

-- Simulated application rollback of optional service
\echo '>> Airport shuttle driver unavailable. Rolling back to SAVEPOINT sp_core_booking...'
ROLLBACK TO SAVEPOINT sp_core_booking;

-- Step C.3: Confirm core booking
UPDATE booking SET status = 'confirmed' WHERE booking_id = 700004;

\echo '>> Committing core booking...'
COMMIT;

-- Post-verification: Confirm core booking is persisted
\echo ''
\echo '--- VERIFYING SCENARIO C: CORE BOOKING COMMITTED, ADD-ON ROLLED BACK ---'
SELECT 
    b.booking_id,
    b.booking_ref,
    b.status,
    b.total_amount,
    br.room_id,
    br.check_in_date,
    br.check_out_date,
    p.amount AS amount_paid,
    p.transaction_ref
FROM booking b
JOIN booking_room br ON b.booking_id = br.booking_id
JOIN payment p ON b.booking_id = p.booking_id
WHERE b.booking_ref = 'TX-SAVEPOINT-CORE';

