-- =============================================================================
-- 10_queries.sql
-- Savannah Crest Hotels: Query Suite for Performance & Execution Plan Analysis
-- Portfolio 2: Query Processing and Optimisation
--
-- Contains 10 analytical, operational, and reporting queries covering:
--   - Multi-table joins (Q01)
--   - Multi-table aggregation with GROUP BY & HAVING (Q02)
--   - Window functions: running totals & lags (Q03)
--   - Window functions: dense ranking & partitioning (Q04)
--   - Common Table Expressions (CTE) (Q05)
--   - Correlated subquery (Q06)
--   - Query rewrite of correlated subquery using window functions (Q07)
--   - Temporal room availability search using range operators (Q08)
--   - Comprehensive guest dossier / booking history lookup (Q09)
--   - Date-range financial & operational reporting (Q10)
--
-- Each query includes:
--   1. Business Question
--   2. Expected Result Shape
-- =============================================================================

-- =============================================================================
-- Q01: Multi-Table Operational Join (Front Desk Arrival & Check-In Roster)
-- =============================================================================
-- Business Question:
--   Retrieve the front desk arrival roster for Savannah Crest Abuja (hotel_id = 1)
--   for check-in on '2026-12-20'. Returns guest names, contact details, room number,
--   room category, stay dates, nightly tariff, total booking value, and payment status.
-- Expected Shape:
--   Tabular roster of individual room check-ins ordered by room number.
SELECT 
    b.booking_ref,
    g.first_name || ' ' || g.last_name AS guest_name,
    g.phone AS guest_phone,
    r.room_number,
    rt.name AS room_category,
    br.check_in_date,
    br.check_out_date,
    (br.check_out_date - br.check_in_date) AS nights,
    br.rate_per_night,
    b.total_amount,
    COALESCE(p.payment_status, 'unpaid') AS payment_status
FROM booking b
JOIN guest g ON b.guest_id = g.guest_id
JOIN hotel h ON b.hotel_id = h.hotel_id
JOIN booking_room br ON b.booking_id = br.booking_id
JOIN room r ON br.room_id = r.room_id
JOIN room_type rt ON r.room_type_id = rt.room_type_id
LEFT JOIN payment p ON b.booking_id = p.booking_id AND p.payment_status = 'completed'
WHERE b.hotel_id = 1
  AND br.check_in_date = '2026-12-20'
  AND br.status != 'cancelled'
ORDER BY r.room_number;


-- =============================================================================
-- Q02: Multi-Table Aggregation with GROUP BY and HAVING (High-Value VIP Guests)
-- =============================================================================
-- Business Question:
--   Identify high-value VIP guests who have completed at least 8 separate bookings
--   and accumulated over ₦1,200,000 in completed payments across the chain.
-- Expected Shape:
--   Aggregated summary per guest (guest_id, name, email, booking count, total spend, avg spend),
--   sorted by total spend descending.
SELECT 
    g.guest_id,
    g.first_name || ' ' || g.last_name AS guest_name,
    g.email,
    g.nationality,
    COUNT(DISTINCT b.booking_id) AS total_bookings,
    SUM(p.amount) AS total_amount_paid,
    ROUND(AVG(p.amount), 2) AS avg_payment_per_booking
FROM guest g
JOIN booking b ON g.guest_id = b.guest_id
JOIN payment p ON b.booking_id = p.booking_id
WHERE p.payment_status = 'completed'
  AND b.status = 'checked_out'
GROUP BY g.guest_id, g.first_name, g.last_name, g.email, g.nationality
HAVING COUNT(DISTINCT b.booking_id) >= 8
   AND SUM(p.amount) >= 1200000.00
ORDER BY total_amount_paid DESC
LIMIT 50;


-- =============================================================================
-- Q03: Window Function (Monthly Revenue Trend, Running Total & MoM Growth)
-- =============================================================================
-- Business Question:
--   For the year 2026, compute monthly realized revenue per hotel property, alongside
--   a running cumulative year-to-date total, and the percentage growth compared to the
--   previous month (using LAG).
-- Expected Shape:
--   One row per hotel and month (hotel_id, hotel_name, month, monthly_revenue,
--   ytd_running_total, mom_growth_pct).
WITH monthly_sales AS (
    SELECT 
        h.hotel_id,
        h.name AS hotel_name,
        DATE_TRUNC('month', b.booking_date)::DATE AS sales_month,
        SUM(p.amount) AS monthly_revenue
    FROM hotel h
    JOIN booking b ON h.hotel_id = b.hotel_id
    JOIN payment p ON b.booking_id = p.booking_id
    WHERE b.booking_date >= '2026-01-01'
      AND b.booking_date < '2027-01-01'
      AND p.payment_status = 'completed'
    GROUP BY h.hotel_id, h.name, DATE_TRUNC('month', b.booking_date)
)
SELECT 
    hotel_id,
    hotel_name,
    sales_month,
    monthly_revenue,
    SUM(monthly_revenue) OVER (
        PARTITION BY hotel_id 
        ORDER BY sales_month
    ) AS ytd_running_total,
    ROUND(
        100.0 * (monthly_revenue - LAG(monthly_revenue) OVER (PARTITION BY hotel_id ORDER BY sales_month)) 
        / NULLIF(LAG(monthly_revenue) OVER (PARTITION BY hotel_id ORDER BY sales_month), 0),
        2
    ) AS mom_growth_pct
FROM monthly_sales
ORDER BY hotel_id, sales_month;


-- =============================================================================
-- Q04: Window Function (Hotel Performance Ranking by Quarterly Revenue)
-- =============================================================================
-- Business Question:
--   Rank all 6 hotel properties by quarter for the year 2026 based on their total
--   completed revenue, assigning a dense rank (1 to 6) per quarter.
-- Expected Shape:
--   Quarterly hotel rankings (quarter, rank, hotel_name, revenue, room_nights_sold).
WITH quarterly_metrics AS (
    SELECT 
        h.name AS hotel_name,
        EXTRACT(QUARTER FROM b.booking_date) AS booking_quarter,
        SUM(p.amount) AS total_revenue,
        COUNT(DISTINCT br.booking_room_id) AS total_room_stays
    FROM hotel h
    JOIN booking b ON h.hotel_id = b.hotel_id
    JOIN booking_room br ON b.booking_id = br.booking_id
    JOIN payment p ON b.booking_id = p.booking_id
    WHERE b.booking_date >= '2026-01-01' AND b.booking_date < '2027-01-01'
      AND p.payment_status = 'completed'
      AND b.status = 'checked_out'
    GROUP BY h.name, EXTRACT(QUARTER FROM b.booking_date)
)
SELECT 
    booking_quarter,
    DENSE_RANK() OVER (
        PARTITION BY booking_quarter 
        ORDER BY total_revenue DESC
    ) AS revenue_rank,
    hotel_name,
    total_revenue,
    total_room_stays
FROM quarterly_metrics
ORDER BY booking_quarter, revenue_rank;


-- =============================================================================
-- Q05: Common Table Expression (Length-of-Stay Segmentation & Yield Analysis)
-- =============================================================================
-- Business Question:
--   Segment all completed stays in 2026 into length-of-stay duration tiers:
--   '1-2 Nights' (Short/Business), '3-5 Nights' (Medium/Leisure), '6+ Nights' (Extended),
--   evaluating the total revenue contribution, average nightly rate, and total volume per tier.
-- Expected Shape:
--   One summary row per hotel and duration tier.
WITH stay_segments AS (
    SELECT 
        b.hotel_id,
        h.name AS hotel_name,
        (br.check_out_date - br.check_in_date) AS stay_length,
        CASE 
            WHEN (br.check_out_date - br.check_in_date) <= 2 THEN '1-2 Nights (Short)'
            WHEN (br.check_out_date - br.check_in_date) <= 5 THEN '3-5 Nights (Medium)'
            ELSE '6+ Nights (Extended)'
        END AS stay_tier,
        br.rate_per_night,
        (br.rate_per_night * (br.check_out_date - br.check_in_date)) AS stay_revenue
    FROM booking b
    JOIN hotel h ON b.hotel_id = h.hotel_id
    JOIN booking_room br ON b.booking_id = br.booking_id
    WHERE b.status = 'checked_out'
      AND br.check_in_date >= '2026-01-01' 
      AND br.check_in_date < '2027-01-01'
)
SELECT 
    hotel_name,
    stay_tier,
    COUNT(*) AS total_stays,
    ROUND(AVG(stay_length), 2) AS avg_nights,
    ROUND(AVG(rate_per_night), 2) AS avg_rate_per_night,
    SUM(stay_revenue) AS total_tier_revenue
FROM stay_segments
GROUP BY hotel_name, stay_tier
ORDER BY hotel_name, stay_tier;


-- =============================================================================
-- Q06: Correlated Subquery (High-Value Bookings Above Hotel-Specific Average)
-- =============================================================================
-- Business Question:
--   Identify individual bookings in 2026 whose total transaction value exceeds
--   the overall average booking value for that specific hotel by at least 80%.
-- Expected Shape:
--   List of premium bookings (booking_ref, hotel_id, total_amount, hotel_avg_amount),
--   computed via a correlated subquery in the WHERE clause.
SELECT 
    b1.booking_id,
    b1.booking_ref,
    b1.hotel_id,
    b1.booking_date,
    b1.total_amount,
    ROUND(
        (SELECT AVG(b2.total_amount) 
         FROM booking b2 
         WHERE b2.hotel_id = b1.hotel_id 
           AND b2.status != 'cancelled'
        ), 2
    ) AS hotel_avg_amount
FROM booking b1
WHERE b1.booking_date >= '2026-06-01' 
  AND b1.booking_date < '2026-12-31'
  AND b1.status != 'cancelled'
  AND b1.total_amount > 1.8 * (
      SELECT AVG(b2.total_amount)
      FROM booking b2
      WHERE b2.hotel_id = b1.hotel_id
        AND b2.status != 'cancelled'
  )
ORDER BY b1.total_amount DESC
LIMIT 50;


-- =============================================================================
-- Q07: Query Rewrite of Q06 (Window Function / CTE Instead of Correlated Subquery)
-- =============================================================================
-- Business Question:
--   Identical business requirement as Q06, but rewritten using a window analytical
--   aggregation (AVG() OVER (PARTITION BY hotel_id)) inside a CTE to eliminate the
--   repetitive SubPlan execution of the correlated subquery.
-- Expected Shape:
--   Same output as Q06, contrasting execution plan structure and buffer consumption.
WITH booking_benchmarks AS (
    SELECT 
        b.booking_id,
        b.booking_ref,
        b.hotel_id,
        b.booking_date,
        b.total_amount,
        b.status,
        ROUND(AVG(b.total_amount) OVER (PARTITION BY b.hotel_id), 2) AS hotel_avg_amount
    FROM booking b
    WHERE b.status != 'cancelled'
)
SELECT 
    booking_id,
    booking_ref,
    hotel_id,
    booking_date,
    total_amount,
    hotel_avg_amount
FROM booking_benchmarks
WHERE booking_date >= '2026-06-01' 
  AND booking_date < '2026-12-31'
  AND total_amount > 1.8 * hotel_avg_amount
ORDER BY total_amount DESC
LIMIT 50;


-- =============================================================================
-- Q08: Room Availability Search (Vacant Rooms for Specific Period & Category)
-- =============================================================================
-- Business Question:
--   Find all available 'Deluxe Room' units at Savannah Crest Abuja (hotel_id = 1)
--   for a proposed stay during the Christmas festive week from '2026-12-24' to '2026-12-31'.
--   A room is available if it has no overlapping active booking ('reserved' or 'checked_in').
-- Expected Shape:
--   List of free rooms (room_id, room_number, floor) ready for reservation.
SELECT 
    r.room_id,
    r.room_number,
    r.floor,
    rt.name AS room_type,
    rt.base_capacity,
    rt.max_capacity
FROM room r
JOIN room_type rt ON r.room_type_id = rt.room_type_id
WHERE r.hotel_id = 1
  AND r.is_active = true
  AND rt.name = 'Deluxe Room'
  AND NOT EXISTS (
      SELECT 1 
      FROM booking_room br
      WHERE br.room_id = r.room_id
        AND br.status IN ('reserved', 'checked_in')
        AND br.stay && daterange('2026-12-24', '2026-12-31', '[)')
  )
ORDER BY r.floor, r.room_number;


-- =============================================================================
-- Q09: Comprehensive Guest Dossier / History Lookup
-- =============================================================================
-- Business Question:
--   Retrieve the comprehensive profile and chronological stay history for guest
--   email 'chinedu.okonkwo1@mail.ng'. Fetches booking references, hotel stayed at,
--   room number, stay dates, amount billed, and payment records.
-- Expected Shape:
--   Chronological booking history for customer service / front desk CRM lookup.
SELECT 
    g.guest_id,
    g.first_name || ' ' || g.last_name AS guest_name,
    g.email,
    g.phone,
    b.booking_ref,
    b.booking_date,
    b.status AS booking_status,
    h.name AS hotel_name,
    r.room_number,
    br.check_in_date,
    br.check_out_date,
    b.total_amount,
    p.payment_method,
    p.payment_status,
    p.amount AS payment_amount
FROM guest g
JOIN booking b ON g.guest_id = b.guest_id
JOIN hotel h ON b.hotel_id = h.hotel_id
JOIN booking_room br ON b.booking_id = br.booking_id
JOIN room r ON br.room_id = r.room_id
LEFT JOIN payment p ON b.booking_id = p.booking_id
WHERE g.email = 'chinedu.okonkwo1@mail.ng'
ORDER BY b.booking_date DESC, br.check_in_date DESC;


-- =============================================================================
-- Q10: Date-Range Financial & Operational Report (December Peak Summary)
-- =============================================================================
-- Business Question:
--   Generate a comprehensive December 2026 performance summary for all hotels:
--   total room-nights occupied, gross revenue collected, average daily booking value,
--   and count of cancellations vs completed stays.
-- Expected Shape:
--   One performance summary row per hotel for December 2026.
SELECT 
    h.hotel_id,
    h.name AS hotel_name,
    h.city,
    COUNT(DISTINCT b.booking_id) FILTER (WHERE b.status = 'checked_out') AS completed_bookings,
    COUNT(DISTINCT b.booking_id) FILTER (WHERE b.status = 'cancelled') AS cancelled_bookings,
    ROUND(
        100.0 * COUNT(DISTINCT b.booking_id) FILTER (WHERE b.status = 'cancelled') 
        / NULLIF(COUNT(DISTINCT b.booking_id), 0), 
        1
    ) AS cancellation_rate_pct,
    SUM(br.check_out_date - br.check_in_date) FILTER (WHERE b.status = 'checked_out') AS total_room_nights_sold,
    COALESCE(SUM(p.amount) FILTER (WHERE p.payment_status = 'completed'), 0) AS total_gross_revenue,
    ROUND(
        AVG(b.total_amount) FILTER (WHERE b.status = 'checked_out'), 
        2
    ) AS avg_booking_value
FROM hotel h
LEFT JOIN booking b 
    ON h.hotel_id = b.hotel_id 
    AND b.booking_date >= '2026-12-01' 
    AND b.booking_date < '2027-01-01'
LEFT JOIN booking_room br 
    ON b.booking_id = br.booking_id
LEFT JOIN payment p 
    ON b.booking_id = p.booking_id
GROUP BY h.hotel_id, h.name, h.city
ORDER BY total_gross_revenue DESC;

