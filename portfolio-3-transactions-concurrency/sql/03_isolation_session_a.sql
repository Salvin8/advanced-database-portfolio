-- =============================================================================
-- 03_isolation_session_a.sql
-- Savannah Crest Hotels: Interactive Two-Terminal Isolation Demonstration (SESSION A)
-- Portfolio 3: Transactions and Concurrency
--
-- Run this in Terminal 1 side-by-side with 03_isolation_session_b.sql in Terminal 2.
-- Follow the numbered step sequence [Step 1, Step 2, Step 3...]
-- =============================================================================

-- =============================================================================
-- PART 1: READ COMMITTED -> NON-REPEATABLE READ DEMONSTRATION
-- =============================================================================

-- [Step 1 - Terminal 1]: Start transaction at READ COMMITTED
BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- [Step 2 - Terminal 1]: Read initial seasonal rate for Deluxe Room at Hotel 1
SELECT rate_id, season_name, price_per_night 
FROM seasonal_rate 
WHERE hotel_id = 1 AND room_type_id = 2 
LIMIT 1;
-- Take note of the price_per_night value.

-- >>> NOW SWITCH TO TERMINAL 2 AND RUN [Step 3] <<<

-- [Step 4 - Terminal 1]: Re-read the exact same row inside the SAME transaction
SELECT rate_id, season_name, price_per_night 
FROM seasonal_rate 
WHERE hotel_id = 1 AND room_type_id = 2 
LIMIT 1;
-- OBSERVATION: In READ COMMITTED, each statement takes a new snapshot.
-- The price_per_night value has CHANGED within the same transaction!
-- This demonstrates a NON-REPEATABLE READ.

COMMIT;


-- =============================================================================
-- PART 2: REPEATABLE READ -> SNAPSHOT ISOLATION & CONCURRENT UPDATE CONFLICT
-- =============================================================================

-- [Step 5 - Terminal 1]: Start transaction at REPEATABLE READ
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;

-- [Step 6 - Terminal 1]: Read initial rate
SELECT rate_id, season_name, price_per_night 
FROM seasonal_rate 
WHERE hotel_id = 1 AND room_type_id = 2 
LIMIT 1;

-- >>> NOW SWITCH TO TERMINAL 2 AND RUN [Step 7] <<<

-- [Step 8 - Terminal 1]: Re-read inside the same transaction
SELECT rate_id, season_name, price_per_night 
FROM seasonal_rate 
WHERE hotel_id = 1 AND room_type_id = 2 
LIMIT 1;
-- OBSERVATION: The rate remains unchanged because REPEATABLE READ freezes
-- the snapshot at transaction start. Non-repeatable read is eliminated!

-- [Step 9 - Terminal 1]: Attempt to update the row modified by Terminal 2
UPDATE seasonal_rate 
SET price_per_night = price_per_night + 1000.00 
WHERE hotel_id = 1 AND room_type_id = 2;
-- OBSERVATION: PostgreSQL detects concurrent modification and raises:
-- ERROR: could not serialize access due to concurrent update (SQLSTATE 40001)

ROLLBACK;


-- =============================================================================
-- PART 3: SERIALIZABLE -> WRITE SKEW DETECTION
-- =============================================================================

-- [Step 10 - Terminal 1]: Start transaction at SERIALIZABLE
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

-- [Step 11 - Terminal 1]: Check emergency available rooms (must keep at least 1)
SELECT COUNT(*) AS emergency_rooms_available 
FROM room 
WHERE hotel_id = 1 AND floor = 5 AND is_active = true;

-- >>> NOW SWITCH TO TERMINAL 2 AND RUN [Step 12] <<<

-- [Step 13 - Terminal 1]: Reserve room 81 (simulate assigning emergency room)
UPDATE room SET is_active = false WHERE room_id = 81;

-- [Step 14 - Terminal 1]: Commit
COMMIT;
-- If Terminal 2 commits concurrently, one session will be aborted with SQLSTATE 40001!

