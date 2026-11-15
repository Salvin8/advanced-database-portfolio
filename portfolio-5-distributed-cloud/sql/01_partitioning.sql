-- =============================================================================
-- 01_partitioning.sql
-- Savannah Crest Hotels: Native Declarative Table Partitioning & Pruning
-- Portfolio 5: Distributed and Cloud Database Exercise
--
-- Demonstrates:
-- 1. Declarative LIST partitioning by hotel_id (horizontal geographic sharding simulation)
-- 2. Creation of 6 dedicated hotel partitions (Abuja, Lagos, Port Harcourt, Kano, Enugu, Ibadan)
-- 3. Data migration from monolithic booking table into partitioned structure
-- 4. Empirical EXPLAIN (ANALYZE, BUFFERS) proof of Partition Pruning (skipping 5 of 6 partitions)
-- 5. Cross-partition distributed aggregation comparison
-- =============================================================================

\set ON_ERROR_STOP on
\timing on

-- Drop previous partitioned objects if re-running
DROP TABLE IF EXISTS booking_partitioned CASCADE;

-- -----------------------------------------------------------------------------
-- 1. Create Parent Partitioned Table
-- -----------------------------------------------------------------------------
-- In PostgreSQL 16, partitioned tables declare PARTITION BY clause.
-- Primary key on partitioned table MUST include the partition key (hotel_id).
CREATE TABLE booking_partitioned (
    booking_id   INT            NOT NULL,
    hotel_id     INT            NOT NULL,
    guest_id     INT            NOT NULL,
    booking_ref  VARCHAR(20)    NOT NULL,
    status       VARCHAR(20)    NOT NULL,
    booking_date TIMESTAMPTZ    NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    notes        TEXT,
    created_at   TIMESTAMPTZ    NOT NULL,
    updated_at   TIMESTAMPTZ    NOT NULL,
    PRIMARY KEY (booking_id, hotel_id)
) PARTITION BY LIST (hotel_id);

-- -----------------------------------------------------------------------------
-- 2. Create 6 Physical Hotel Partitions (Simulating Geographic Shards)
-- -----------------------------------------------------------------------------
CREATE TABLE booking_part_abuja PARTITION OF booking_partitioned
    FOR VALUES IN (1);

CREATE TABLE booking_part_lagos PARTITION OF booking_partitioned
    FOR VALUES IN (2);

CREATE TABLE booking_part_ph PARTITION OF booking_partitioned
    FOR VALUES IN (3);

CREATE TABLE booking_part_kano PARTITION OF booking_partitioned
    FOR VALUES IN (4);

CREATE TABLE booking_part_enugu PARTITION OF booking_partitioned
    FOR VALUES IN (5);

CREATE TABLE booking_part_ibadan PARTITION OF booking_partitioned
    FOR VALUES IN (6);

-- Create partition-local secondary indexes
CREATE INDEX idx_part_abuja_date  ON booking_part_abuja (booking_date);
CREATE INDEX idx_part_lagos_date  ON booking_part_lagos (booking_date);
CREATE INDEX idx_part_ph_date     ON booking_part_ph (booking_date);
CREATE INDEX idx_part_kano_date   ON booking_part_kano (booking_date);
CREATE INDEX idx_part_enugu_date  ON booking_part_enugu (booking_date);
CREATE INDEX idx_part_ibadan_date ON booking_part_ibadan (booking_date);

CREATE INDEX idx_part_abuja_guest ON booking_part_abuja (guest_id);
CREATE INDEX idx_part_lagos_guest ON booking_part_lagos (guest_id);
CREATE INDEX idx_part_ph_guest    ON booking_part_ph (guest_id);
CREATE INDEX idx_part_kano_guest  ON booking_part_kano (guest_id);
CREATE INDEX idx_part_enugu_guest ON booking_part_enugu (guest_id);
CREATE INDEX idx_part_ibadan_guest ON booking_part_ibadan (guest_id);

-- -----------------------------------------------------------------------------
-- 3. Populate Partitioned Table from Monolithic Booking Table
-- -----------------------------------------------------------------------------
\echo '=== Migrating data from booking into booking_partitioned ==='
INSERT INTO booking_partitioned (
    booking_id, hotel_id, guest_id, booking_ref, status, booking_date, total_amount, notes, created_at, updated_at
)
SELECT 
    booking_id, hotel_id, guest_id, booking_ref, status, booking_date, total_amount, notes, created_at, updated_at
FROM booking;

-- Analyze parent and all partitions to update planner statistics
ANALYZE booking_partitioned;

-- -----------------------------------------------------------------------------
-- 4. Verify Row Counts Across Partitions
-- -----------------------------------------------------------------------------
\echo '=== Row Counts Across Geographic Partitions ==='
SELECT 
    pt.relname AS partition_name,
    CASE 
        WHEN pt.relname = 'booking_part_abuja'  THEN 'Hotel 1 - Abuja (Capital)'
        WHEN pt.relname = 'booking_part_lagos'  THEN 'Hotel 2 - Lagos (Commercial Hub)'
        WHEN pt.relname = 'booking_part_ph'     THEN 'Hotel 3 - Port Harcourt (Oil & Gas)'
        WHEN pt.relname = 'booking_part_kano'   THEN 'Hotel 4 - Kano (Northern Commerce)'
        WHEN pt.relname = 'booking_part_enugu'  THEN 'Hotel 5 - Enugu (Coal City)'
        WHEN pt.relname = 'booking_part_ibadan' THEN 'Hotel 6 - Ibadan (Pacesetter)'
        ELSE 'Other'
    END AS property_description,
    pg_size_pretty(pg_relation_size(pt.oid)) AS partition_data_size,
    pg_size_pretty(pg_total_relation_size(pt.oid)) AS partition_total_size,
    pt.reltuples::bigint AS estimated_rows
FROM pg_class pt
JOIN pg_inherits inh ON pt.oid = inh.inhrelid
JOIN pg_class prt ON inh.inhparent = prt.oid
WHERE prt.relname = 'booking_partitioned'
ORDER BY pt.relname;

-- -----------------------------------------------------------------------------
-- 5. Empirical Proof of Partition Pruning
-- -----------------------------------------------------------------------------
\echo '=== TEST 1: Single-Partition Query with Static Partition Pruning ==='
\echo 'Query filter: WHERE hotel_id = 2 (Lagos property only)'
\echo 'Expected: Planner prunes Abuja, Port Harcourt, Kano, Enugu, and Ibadan entirely.'

EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT count(*), sum(total_amount), avg(total_amount)
FROM booking_partitioned
WHERE hotel_id = 2;

\echo '=== TEST 2: Multi-Partition Query Touching Two Properties ==='
\echo 'Query filter: WHERE hotel_id IN (1, 2) (Abuja and Lagos only)'
\echo 'Expected: Planner scans ONLY booking_part_abuja and booking_part_lagos, pruning remaining 4.'

EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT hotel_id, count(*), sum(total_amount)
FROM booking_partitioned
WHERE hotel_id IN (1, 2)
GROUP BY hotel_id;

\echo '=== TEST 3: Scatter-Gather Cross-Partition Analytics ==='
\echo 'Query filter: None (Global query across all hotels)'
\echo 'Expected: Planner fans out (Append) across all 6 partitions and aggregates results.'

EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT 
    hotel_id,
    count(*) AS total_bookings,
    sum(total_amount) AS gross_revenue,
    round(avg(total_amount), 2) AS avg_booking_value
FROM booking_partitioned
GROUP BY hotel_id
ORDER BY gross_revenue DESC;

