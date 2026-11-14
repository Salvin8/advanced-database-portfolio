-- =============================================================================
-- 03_constraint_tests.sql
-- Savannah Crest Hotels: Database Constraint Verification Suite
-- Portfolio 1: Database Design and Modelling
--
-- This script validates that:
-- 1. Valid data is accepted across all primary business entities.
-- 2. Invalid data is strictly rejected by PostgreSQL constraints:
--    - Primary Key & Foreign Key (orphan records)
--    - Unique constraints (duplicate email, duplicate room within hotel)
--    - Check constraints (negative payment, invalid dates, invalid status)
--    - GiST Exclusion constraint (overlapping reservations for the same room)
--
-- Run with:
--   docker compose exec -T postgres psql -U hotel_admin -d savannah_crest \
--     < portfolio-1-database-design/sql/03_constraint_tests.sql \
--     > portfolio-1-database-design/evidence/constraint-tests.txt 2>&1
-- =============================================================================

\echo '====================================================================='
\echo 'PORTFOLIO 1: CONSTRAINT VERIFICATION TEST SUITE'
\echo '====================================================================='
\echo ''

-- Enable timing
\timing on

-- Clean up any residual test records from prior runs
DELETE FROM payment WHERE transaction_ref LIKE 'TEST-TX-%';
DELETE FROM check_in_out WHERE record_id IN (SELECT record_id FROM check_in_out JOIN booking_room br USING (booking_room_id) JOIN booking b USING (booking_id) WHERE b.booking_ref LIKE 'TEST-BK-%');
DELETE FROM booking_room WHERE booking_id IN (SELECT booking_id FROM booking WHERE booking_ref LIKE 'TEST-BK-%');
DELETE FROM booking WHERE booking_ref LIKE 'TEST-BK-%';
DELETE FROM guest WHERE email LIKE 'test.guest%@example.com';
DELETE FROM room WHERE room_number IN ('TEST-101', 'TEST-102');
DELETE FROM staff WHERE email = 'test.staff@savannahcrest.ng';
DELETE FROM seasonal_rate WHERE season_name = 'TEST-WINTER-PEAK';
DELETE FROM room_type WHERE name = 'TEST-PENTHOUSE';
DELETE FROM hotel WHERE name = 'TEST-HOTEL-ABUJA';

\echo '---------------------------------------------------------------------'
\echo 'PART 1: VALID INSERTS (SHOULD SUCCEED)'
\echo '---------------------------------------------------------------------'

-- 1.1 Insert valid hotel
INSERT INTO hotel (hotel_id, name, city, address, phone, email, star_rating)
VALUES (9999, 'TEST-HOTEL-ABUJA', 'Abuja', '10 Shehu Shagari Way, Maitama', '+2348011112222', 'abuja.test@savannahcrest.ng', 4)
RETURNING hotel_id, name, city, star_rating;

-- 1.2 Insert valid room type
INSERT INTO room_type (room_type_id, name, description, base_capacity, max_capacity)
VALUES (9999, 'TEST-PENTHOUSE', 'Luxury rooftop penthouse suite', 2, 4)
RETURNING room_type_id, name, base_capacity, max_capacity;

-- 1.3 Insert valid rooms
INSERT INTO room (room_id, hotel_id, room_type_id, room_number, floor, is_active)
VALUES 
    (9998, 9999, 9999, 'TEST-101', 1, true),
    (9999, 9999, 9999, 'TEST-102', 1, true)
RETURNING room_id, hotel_id, room_number, floor;

-- 1.4 Insert valid guests
INSERT INTO guest (guest_id, first_name, last_name, email, phone, id_type, id_number, nationality, date_of_birth)
VALUES 
    (9998, 'Amaka', 'Okonkwo', 'test.guest1@example.com', '+2348022223333', 'passport', 'A01234567', 'Nigerian', '1988-06-15'),
    (9999, 'Tunde', 'Adeyemi', 'test.guest2@example.com', '+2348033334444', 'national_id', 'NIN987654321', 'Nigerian', '1992-11-03')
RETURNING guest_id, first_name, last_name, email;

-- 1.5 Insert valid staff
INSERT INTO staff (staff_id, hotel_id, first_name, last_name, email, role, hired_date)
VALUES (9999, 9999, 'Chidi', 'Eze', 'test.staff@savannahcrest.ng', 'receptionist', '2023-01-10')
RETURNING staff_id, first_name, last_name, role;

-- 1.6 Insert valid booking 1
INSERT INTO booking (booking_id, guest_id, hotel_id, booking_ref, status, total_amount)
VALUES (9998, 9998, 9999, 'TEST-BK-2026-001', 'confirmed', 150000.00)
RETURNING booking_id, booking_ref, status, total_amount;

-- 1.7 Insert valid room assignment for room 9998: Dec 10 to Dec 15, 2026
INSERT INTO booking_room (booking_room_id, booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
VALUES (9998, 9998, 9998, '2026-12-10', '2026-12-15', 30000.00, 2, 'reserved')
RETURNING booking_room_id, booking_id, room_id, check_in_date, check_out_date, stay, status;

-- 1.8 Insert non-overlapping booking for the SAME room (adjacent checkout day = checkin day [) semantics)
-- Dec 15 to Dec 20, 2026. This MUST succeed because checkout on Dec 15 frees the room for checkin on Dec 15.
INSERT INTO booking (booking_id, guest_id, hotel_id, booking_ref, status, total_amount)
VALUES (9999, 9999, 9999, 'TEST-BK-2026-002', 'confirmed', 150000.00);

INSERT INTO booking_room (booking_room_id, booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
VALUES (9999, 9999, 9998, '2026-12-15', '2026-12-20', 30000.00, 2, 'reserved')
RETURNING booking_room_id, booking_id, room_id, check_in_date, check_out_date, stay, status;

-- 1.9 Insert valid payment
INSERT INTO payment (payment_id, booking_id, amount, payment_method, payment_status, transaction_ref)
VALUES (9999, 9998, 150000.00, 'card', 'completed', 'TEST-TX-2026-999')
RETURNING payment_id, booking_id, amount, payment_method, payment_status;

-- 1.10 Trigger test: update booking status and verify audit_log
UPDATE booking SET status = 'checked_in' WHERE booking_id = 9998;
SELECT log_id, table_name, record_id, action, old_values->>'status' AS old_status, new_values->>'status' AS new_status, changed_by 
FROM audit_log 
WHERE table_name = 'booking' AND record_id = 9998;

\echo ''
\echo '---------------------------------------------------------------------'
\echo 'PART 2: NEGATIVE TESTS (CONSTRAINTS THAT MUST REJECT INVALID DATA)'
\echo '---------------------------------------------------------------------'

-- Test Helper: wraps statement in DO block to catch exception and print formatted outcome
-- This ensures the test runner does not abort early and all assertions run.

-- TEST 2.1: Exclusion constraint violation (overlapping dates on same room)
-- Room 9998 is booked Dec 10-15. Attempting to book Dec 12-17 MUST FAIL.
\echo 'TEST 2.1: Exclusion constraint test (double booking attempt for room 9998, Dec 12 to 17)...'
DO $$
BEGIN
    INSERT INTO booking_room (booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
    VALUES (9999, 9998, '2026-12-12', '2026-12-17', 30000.00, 1, 'reserved');
    RAISE EXCEPTION 'TEST FAILED: Overlapping booking was unexpectedly allowed!';
EXCEPTION
    WHEN exclusion_violation THEN
        RAISE NOTICE 'SUCCESS: Caught expected exclusion_violation: %', SQLERRM;
END $$;

-- TEST 2.2: Negative payment amount (CHECK constraint violation)
\echo 'TEST 2.2: Negative payment check constraint (amount = -5000)...'
DO $$
BEGIN
    INSERT INTO payment (booking_id, amount, payment_method, payment_status, transaction_ref)
    VALUES (9998, -5000.00, 'card', 'completed', 'TEST-TX-FAIL-1');
    RAISE EXCEPTION 'TEST FAILED: Negative payment was unexpectedly accepted!';
EXCEPTION
    WHEN check_violation THEN
        RAISE NOTICE 'SUCCESS: Caught expected check_violation: %', SQLERRM;
END $$;

-- TEST 2.3: Check-out before check-in date (CHECK constraint & daterange domain violation)
\echo 'TEST 2.3: Date sequence check constraint (checkout 2026-12-05 < checkin 2026-12-10)...'
DO $$
BEGIN
    INSERT INTO booking_room (booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
    VALUES (9998, 9999, '2026-12-10', '2026-12-05', 25000.00, 1, 'reserved');
    RAISE EXCEPTION 'TEST FAILED: Inverted stay dates were unexpectedly accepted!';
EXCEPTION
    WHEN check_violation OR data_exception THEN
        RAISE NOTICE 'SUCCESS: Caught expected date check/domain violation: %', SQLERRM;
END $$;

-- TEST 2.4: Foreign key constraint violation (Orphan record - invalid guest_id)
\echo 'TEST 2.4: Foreign key constraint test (non-existent guest_id 999999)...'
DO $$
BEGIN
    INSERT INTO booking (guest_id, hotel_id, booking_ref, status, total_amount)
    VALUES (999999, 9999, 'TEST-BK-ORPHAN', 'pending', 50000.00);
    RAISE EXCEPTION 'TEST FAILED: Orphan booking with non-existent guest was accepted!';
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE NOTICE 'SUCCESS: Caught expected foreign_key_violation: %', SQLERRM;
END $$;

-- TEST 2.5: Unique constraint violation (duplicate guest email)
\echo 'TEST 2.5: Unique constraint test (duplicate guest email: test.guest1@example.com)...'
DO $$
BEGIN
    INSERT INTO guest (first_name, last_name, email)
    VALUES ('Duplicate', 'User', 'test.guest1@example.com');
    RAISE EXCEPTION 'TEST FAILED: Duplicate email was unexpectedly allowed!';
EXCEPTION
    WHEN unique_violation THEN
        RAISE NOTICE 'SUCCESS: Caught expected unique_violation: %', SQLERRM;
END $$;

-- TEST 2.6: Unique constraint violation (duplicate room_number within the same hotel)
\echo 'TEST 2.6: Unique constraint test (duplicate room TEST-101 in hotel 9999)...'
DO $$
BEGIN
    INSERT INTO room (hotel_id, room_type_id, room_number, floor)
    VALUES (9999, 9999, 'TEST-101', 2);
    RAISE EXCEPTION 'TEST FAILED: Duplicate room number within same hotel was allowed!';
EXCEPTION
    WHEN unique_violation THEN
        RAISE NOTICE 'SUCCESS: Caught expected unique_violation: %', SQLERRM;
END $$;

-- TEST 2.7: Invalid status enum check constraint
\echo 'TEST 2.7: Invalid enum status check constraint (status = bogus_status)...'
DO $$
BEGIN
    INSERT INTO booking (guest_id, hotel_id, booking_ref, status, total_amount)
    VALUES (9998, 9999, 'TEST-BK-BADSTATUS', 'bogus_status', 10000.00);
    RAISE EXCEPTION 'TEST FAILED: Invalid booking status was accepted!';
EXCEPTION
    WHEN check_violation THEN
        RAISE NOTICE 'SUCCESS: Caught expected check_violation: %', SQLERRM;
END $$;

-- TEST 2.8: Exclusion constraint bypass test when status is 'cancelled'
-- If a booking is cancelled, a new booking for the EXACT SAME date range MUST SUCCEED.
\echo 'TEST 2.8: Exclusion constraint status filter check (cancelled bookings do NOT block)...'
-- Create room 9999 booking Jan 10-15, then mark cancelled
INSERT INTO booking (booking_id, guest_id, hotel_id, booking_ref, status, total_amount)
VALUES (9997, 9998, 9999, 'TEST-BK-CANCELLED', 'cancelled', 60000.00);

INSERT INTO booking_room (booking_room_id, booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
VALUES (9997, 9997, 9999, '2026-01-10', '2026-01-15', 20000.00, 1, 'cancelled');

-- Now insert active booking for the exact same room and date: MUST SUCCEED
INSERT INTO booking_room (booking_room_id, booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status)
VALUES (9996, 9998, 9999, '2026-01-10', '2026-01-15', 20000.00, 1, 'reserved')
RETURNING booking_room_id, room_id, check_in_date, check_out_date, status;

\echo ''
\echo '====================================================================='
\echo 'ALL CONSTRAINT TESTS EXECUTED SUCCESSFULLY.'
\echo '====================================================================='

-- Clean up test records
DELETE FROM payment WHERE transaction_ref LIKE 'TEST-TX-%';
DELETE FROM check_in_out WHERE record_id IN (SELECT record_id FROM check_in_out JOIN booking_room br USING (booking_room_id) JOIN booking b USING (booking_id) WHERE b.booking_ref LIKE 'TEST-BK-%');
DELETE FROM booking_room WHERE booking_id IN (SELECT booking_id FROM booking WHERE booking_ref LIKE 'TEST-BK-%');
DELETE FROM booking WHERE booking_ref LIKE 'TEST-BK-%';
DELETE FROM guest WHERE email LIKE 'test.guest%@example.com';
DELETE FROM room WHERE room_number IN ('TEST-101', 'TEST-102');
DELETE FROM staff WHERE email = 'test.staff@savannahcrest.ng';
DELETE FROM seasonal_rate WHERE season_name = 'TEST-WINTER-PEAK';
DELETE FROM room_type WHERE name = 'TEST-PENTHOUSE';
DELETE FROM hotel WHERE name = 'TEST-HOTEL-ABUJA';
