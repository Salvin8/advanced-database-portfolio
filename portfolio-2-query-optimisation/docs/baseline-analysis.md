# Baseline Query Performance Analysis: Savannah Crest Hotels

**Environment:** PostgreSQL 16.4 running in Docker  
**Dataset Scale:** Scale 1.0 (500,000 bookings, 500,000 room assignments, 520,202 payments, 50,000 guests, 600 rooms)  
**Configuration:** Default PostgreSQL settings (`work_mem = 4MB`, `shared_buffers = 128MB`), P1 primary key, unique, and foreign key indexes only.  
**Measurement Method:** `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` executed on live database.

---

## 1. Baseline Performance Summary (All 10 Queries)

| Query ID | Business Focus | Planning Time | Execution Time | Buffer Hits | Buffer Reads | Temp Disk Spill | Dominant Plan Node |
|---|---|---|---|---|---|---|---|
| **Q01** | Arrival roster by date & room | 124.17 ms | 5.43 ms | 2,754 | 2 | None | Nested Loop / Index Scan |
| **Q02** | High-spending VIP guests (HAVING) | 10.63 ms | **8,112.59 ms** | 5,966 | 10,203 | **10,616 kB (Disk)** | GroupAggregate / External Sort |
| **Q03** | Monthly revenue trend & running total | 86.13 ms | **1,663.92 ms** | 3,489 | 9,819 | None | WindowAgg / Hash Join |
| **Q04** | Quarterly hotel ranking (DENSE_RANK) | 65.83 ms | **1,266.47 ms** | 70,396 | 8,774 | None | Incremental Sort / WindowAgg |
| **Q05** | Length-of-stay segmentation (CTE) | 5.44 ms | 577.84 ms | 17,219 | 1,844 | None | Hash Aggregate / Hash Join |
| **Q06** | Correlated subquery (above-avg bookings) | 0.76 ms | **32,341.72 ms** | 779,301 | 9,883 | None | **SubPlan (409 iterations)** |
| **Q07** | Window rewrite of Q06 | 0.26 ms | **1,424.09 ms** | 9,883 | 0 | None | WindowAgg / CTE Scan |
| **Q08** | Room availability search (daterange) | 9.25 ms | 32.98 ms | 1,460 | 4 | None | Nested Loop / Bitmap Scan |
| **Q09** | Complete guest dossier lookup | 6.22 ms | 7.04 ms | 1,829 | 0 | None | Nested Loop / Index Scan |
| **Q10** | December financial & cancellation summary | 4.48 ms | 134.57 ms | 3,482 | 4,210 | None | GroupAggregate / Hash Join |

---

## 2. In-Depth Analysis of the Slowest & Most Expensive Queries

### 1. Q06: Correlated Subquery (32,341.7 ms / 789,184 buffer hits)
- **What the query does:** Identifies individual bookings in the second half of 2026 whose transaction total is 80% higher than the average booking for that specific hotel.
- **Why it is exceptionally slow:**
  - In standard SQL, a correlated subquery in the `WHERE` clause:
    ```sql
    WHERE b1.total_amount > 1.8 * (SELECT AVG(b2.total_amount) FROM booking b2 WHERE b2.hotel_id = b1.hotel_id)
    ```
    is treated by PostgreSQL as an independent sub-plan (`SubPlan 2`).
  - Because `hotel_id` varies per candidate row, PostgreSQL cannot flatten this expression into an initial constant. The outer query finds candidate rows from `booking b1` and invokes `SubPlan 2` **in a tight loop for 409 separate qualifying rows**.
  - In each of those 409 iterations, PostgreSQL executes a `Bitmap Index Scan` on `idx_booking_hotel` followed by a `Bitmap Heap Scan` on `booking b2`, scanning **76,630 rows per iteration**!
  - 409 iterations $\times$ 76,630 rows inspected $\approx 31.3 \text{ million}$ tuple visits, consuming **789,184 8KB page buffer hits** and locking the CPU core for **32.3 seconds**.
- **Pathological flaw:** Algorithmic complexity is $\mathcal{O}(N \times M)$ where $N$ is candidate rows and $M$ is property volume.

---

### 2. Q02: Multi-Table Aggregation with GROUP BY & HAVING (8,112.6 ms / 10,616 kB Disk Spill)
- **What the query does:** Aggregates guest lifetime statistics across 50,000 guests, 500,000 bookings, and 520,202 payments, filtering for guests with $\ge 8$ bookings and $\ge ₦1,200,000$ in total spend.
- **Why it is slow:**
  1. **Full Sequential Scans:** It sequentially scans all 520,202 rows of `payment` and all 500,000 rows of `booking` because there is no composite index filtering `(status = 'checked_out')` or `(payment_status = 'completed')`.
  2. **Hash Join Memory:** The two tables are joined via an in-memory hash table across 439,550 joined tuples.
  3. **External Merge Sort (Disk Spill):** To perform `GroupAggregate` with `COUNT(DISTINCT b.booking_id)`, PostgreSQL must sort the joined stream by `(g.guest_id, b.booking_id)`. The volume of intermediate tuples (439,550 rows $\times$ 63 bytes $\approx 28 \text{ MB}$) far exceeds PostgreSQL's default `work_mem = 4MB`.
  4. Consequently, PostgreSQL aborts in-memory quicksort and spills to temporary disk files:
     ```text
     Sort Method: external merge  Disk: 10616kB
     Buffers: shared hit=5966 read=10203, temp read=4069 written=4081
     ```
     Writing and reading back 10.6 MB of temp files from disk introduces substantial I/O latency, extending execution time to **8.11 seconds**.

---

### 3. Q03: Monthly Revenue Trend & Cumulative Total (1,663.9 ms / 13,308 buffers)
- **What the query does:** Groups 2026 completed transactions by month and hotel, calculating running totals and month-over-month growth using `SUM(...) OVER` and `LAG(...) OVER`.
- **Why it is slow:**
  - Filtering by `b.booking_date >= '2026-01-01' AND b.booking_date < '2027-01-01'` requires scanning the entire 500,000-row `booking` table because `booking_date` only possesses baseline constraints and lacks a targeted index.
  - The query performs a `Seq Scan` on `booking` (reading 9,819 buffer pages from disk) and a `Seq Scan` on `payment`, followed by a `Hash Join` on `b.booking_id = p.booking_id`.
  - While the final window function calculation (`WindowAgg`) takes only 10 ms, **99% of total execution time is spent reading unindexed heap pages from disk**.

---

### 4. Q07: Window Rewrite of Q06 (1,424.1 ms vs 32,341.7 ms)
- **What the query does:** Achieves the identical result as Q06, but substitutes the nested subquery with an analytical window function inside a Common Table Expression:
  ```sql
  WITH booking_benchmarks AS (
      SELECT ..., AVG(total_amount) OVER (PARTITION BY hotel_id) AS hotel_avg_amount
      FROM booking WHERE status != 'cancelled'
  )
  ```
- **Why this rewrite demonstrates immediate optimisation:**
  - By replacing the row-by-row `SubPlan` with `AVG(...) OVER (PARTITION BY hotel_id)`, PostgreSQL computes the average for each hotel in **a single pass** over the `booking` table.
  - Rather than running 409 repeated scans over 76,000 rows, the engine performs one scan, partitions into 6 groups, and streams the window aggregate directly into the outer filter.
  - **Result:** Execution time immediately collapses from **32,341.7 ms down to 1,424.1 ms — a 22.7x speedup (95.6% time reduction) achieved purely via SQL query refactoring without adding any physical indexes.**

---

### 5. Q04: Quarterly Hotel Performance Ranking (1,266.5 ms / 79,170 buffers)
- **What the query does:** Calculates quarterly revenue and room stays across 6 properties, applying `DENSE_RANK() OVER (PARTITION BY quarter ORDER BY total_revenue DESC)`.
- **Why it is slow:**
  - Joins 4 tables: `hotel`, `booking`, `booking_room`, and `payment`.
  - Without composite indexes on `booking(booking_date, status)` and `payment(booking_id, payment_status)`, PostgreSQL executes multiple hash joins, inspecting 79,170 buffer pages.
  - Multiple sorting steps (`Sort Key: booking_quarter, total_revenue DESC` followed by `Incremental Sort`) consume CPU cycles before the window function can assign ranks.

---

## 3. Targeted Optimisation Plan for Milestone 2.3

Based on the empirical evidence gathered above, our indexing and query optimisation strategy will target the exact bottlenecks identified:

1. **Composite & Covering Index on Bookings for Date Filtering:**
   - Target queries: Q01, Q03, Q04, Q05, Q06, Q07, Q10.
   - Design: Composite B-tree index on `(hotel_id, booking_date) INCLUDE (total_amount, status)`.
2. **Partial Index on Active Payments:**
   - Target queries: Q02, Q03, Q04, Q10.
   - Design: `CREATE INDEX idx_payment_completed ON payment (booking_id, amount) WHERE (payment_status = 'completed')`.
   - Justification: Filters out pending/failed payments at the index level, reducing index size and avoiding heap access for uncompleted transactions.
3. **Partial Index on Non-Cancelled Bookings:**
   - Target queries: Q05, Q06, Q07.
   - Design: `CREATE INDEX idx_booking_active ON booking (hotel_id, total_amount) WHERE (status != 'cancelled')`.
4. **Targeted Room Availability Index:**
   - Target queries: Q08.
   - Design: GiST or BRIN on `booking_room (room_id, check_in_date, check_out_date)`.
5. **Memory Configuration Adjustment:**
   - Set local session `work_mem = 64MB` for Q02 to eliminate the 10.6 MB disk spill and enable in-memory sorting.

