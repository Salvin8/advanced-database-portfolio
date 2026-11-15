-- =============================================================================
-- 03_isolation_session_b.sql
-- Savannah Crest Hotels: Interactive Two-Terminal Isolation Demonstration (SESSION B)
-- Portfolio 3: Transactions and Concurrency
--
-- Run this in Terminal 2 side-by-side with 03_isolation_session_a.sql in Terminal 1.
-- Follow the numbered step sequence [Step 1, Step 2, Step 3...]
-- =============================================================================

-- =============================================================================
-- PART 1: READ COMMITTED INTERFERENCE
-- =============================================================================

-- [Step 3 - Terminal 2]: Update rate and commit
BEGIN;
UPDATE seasonal_rate 
SET price_per_night = price_per_night + 10000.00 
WHERE hotel_id = 1 AND room_type_id = 2;
COMMIT;
-- >>> NOW SWITCH BACK TO TERMINAL 1 AND RUN [Step 4] <<<


-- =============================================================================
-- PART 2: REPEATABLE READ CONFLICT TRIGGER
-- =============================================================================

-- [Step 7 - Terminal 2]: Update rate under concurrent transaction
BEGIN;
UPDATE seasonal_rate 
SET price_per_night = price_per_night + 5000.00 
WHERE hotel_id = 1 AND room_type_id = 2;
COMMIT;
-- >>> NOW SWITCH BACK TO TERMINAL 1 AND RUN [Step 8 and 9] <<<


-- =============================================================================
-- PART 3: SERIALIZABLE WRITE SKEW CONCURRENT WORKFLOW
-- =============================================================================

-- [Step 12 - Terminal 2]: Start transaction at SERIALIZABLE
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

-- Read emergency available rooms
SELECT COUNT(*) AS emergency_rooms_available 
FROM room 
WHERE hotel_id = 1 AND floor = 5 AND is_active = true;

-- Reserve room 82 (assigning second emergency room concurrently)
UPDATE room SET is_active = false WHERE room_id = 82;

COMMIT;
-- >>> NOW SWITCH BACK TO TERMINAL 1 AND RUN [Step 13 and 14] <<<

