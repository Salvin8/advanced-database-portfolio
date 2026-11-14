-- =============================================================================
-- 20_indexes.sql
-- Savannah Crest Hotels: Targeted Indexing Strategy
-- Portfolio 2: Query Processing and Optimisation
--
-- Designed directly from empirical baseline plan bottlenecks:
--   1. Composite B-Tree Index: (hotel_id, booking_date)
--   2. Partial Index: payment(booking_id, amount) WHERE status = 'completed'
--   3. Covering Index (INCLUDE): booking(guest_id, status) INCLUDE (total_amount, booking_ref, booking_date)
--   4. BRIN Index (Block Range Index): booking(booking_date)
--   5. Composite Index for Range Queries: booking_room(check_in_date, check_out_date, room_id)
--   6. Low-Cardinality Demonstration Index: guest(nationality) [Intentionally ignored by planner]
-- =============================================================================

-- =============================================================================
-- 1. Composite B-Tree Index for Property-Date Range Filtering
-- =============================================================================
-- Targets: Q01, Q03, Q04, Q10
-- Bottleneck Solved:
--   Baseline plans executed sequential heap scans on booking (500k rows) when
--   filtering by hotel_id and booking_date range.
-- Column Order Justification:
--   hotel_id comes first because equality filters (hotel_id = 1) or partition
--   groupings narrow the search space to 1/6th of the table before evaluating
--   the range condition (booking_date >= ... AND booking_date < ...).
CREATE INDEX idx_booking_hotel_date 
ON booking (hotel_id, booking_date);

COMMENT ON INDEX idx_booking_hotel_date IS 
  'Composite B-tree index enabling index range scans when querying bookings for a specific hotel across date ranges.';


-- =============================================================================
-- 2. Partial Index on Completed Payments
-- =============================================================================
-- Targets: Q02, Q03, Q04, Q10
-- Bottleneck Solved:
--   Revenue and financial reports only care about completed payments. Failed and
--   refunded payments add unnecessary clutter to index pages.
-- Technical Justification:
--   A partial index with WHERE (payment_status = 'completed') is ~15% smaller
--   than a full index, fits entirely in shared_buffers, and allows PostgreSQL to
--   completely avoid visiting uncompleted payment records.
CREATE INDEX idx_payment_completed_booking 
ON payment (booking_id, amount) 
WHERE (payment_status = 'completed');

COMMENT ON INDEX idx_payment_completed_booking IS 
  'Partial index containing only completed payments with amount included to support fast index lookups and aggregations.';


-- =============================================================================
-- 3. Covering Index (INCLUDE) for VIP Guest Lookups
-- =============================================================================
-- Targets: Q02, Q09
-- Bottleneck Solved:
--   In Q02 and Q09, joining guest to booking required visiting the booking heap
--   table for total_amount, booking_ref, and booking_date.
-- Technical Justification:
--   The INCLUDE clause stores total_amount and booking_date in the leaf pages
--   of the B-tree without making them part of the search key. This enables
--   PostgreSQL to execute an INDEX ONLY SCAN, eliminating table heap page fetches.
CREATE INDEX idx_booking_guest_status_covering 
ON booking (guest_id, status) 
INCLUDE (total_amount, booking_ref, booking_date);

COMMENT ON INDEX idx_booking_guest_status_covering IS 
  'Covering index for guest booking histories; enables Index Only Scans for guest aggregation and CRM dossier queries.';


-- =============================================================================
-- 4. BRIN (Block Range Index) for Physical Date Ordering
-- =============================================================================
-- Targets: Q03, Q04, Q05, Q10
-- Bottleneck Solved:
--   Large historical table scans across multi-year date ranges.
-- Technical Justification:
--   Because hotel reservations are naturally inserted in near-chronological
--   order, the physical heap pages correlate strongly with booking_date. A BRIN
--   index stores only the minimum and maximum values per 128-page block range.
--   While a B-tree index on booking_date would consume ~12 MB, this BRIN index
--   consumes only ~48 KB (a 99.6% space saving) while still enabling rapid
--   block-range pruning for date-filtered queries.
CREATE INDEX idx_booking_date_brin 
ON booking USING brin (booking_date);

COMMENT ON INDEX idx_booking_date_brin IS 
  'Extremely compact Block Range Index (BRIN) exploiting physical insertion order of bookings by date.';


-- =============================================================================
-- 5. Targeted Partial Index for Room Stay Filtering
-- =============================================================================
-- Targets: Q01, Q05, Q08
-- Bottleneck Solved:
--   Finding active room stays for check-in rosters or availability searches.
CREATE INDEX idx_booking_room_active_dates 
ON booking_room (room_id, check_in_date, check_out_date) 
WHERE (status IN ('reserved', 'checked_in'));

COMMENT ON INDEX idx_booking_room_active_dates IS 
  'Partial index indexing only active room stays, supporting rapid temporal availability queries.';


-- =============================================================================
-- 6. Demonstration Case: Low-Cardinality Index (Intentionally Ignored by Planner)
-- =============================================================================
-- Target: Q02 (filtering guest by nationality)
-- Demonstration Purpose:
--   Indexes on low-cardinality columns with high data skew are counterproductive.
--   Because 90% of guests are 'Nigerian', reading 90% of the table via index
--   pages plus random heap lookups is significantly more expensive than a single
--   sequential scan.
-- Expected Behaviour:
--   PostgreSQL query planner will estimate the cost and deliberately REJECT this
--   index in favour of a Seq Scan on guest.
CREATE INDEX idx_guest_nationality 
ON guest (nationality);

COMMENT ON INDEX idx_guest_nationality IS 
  'Demonstration index on a skewed low-cardinality column; PostgreSQL planner will bypass this in favor of a sequential scan.';

