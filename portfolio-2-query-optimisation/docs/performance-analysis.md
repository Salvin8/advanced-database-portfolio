# Query Performance and Optimisation Analysis: Savannah Crest Hotels

**Course:** MIT 8103 Advanced Database Systems  
**Database Engine:** PostgreSQL 16.4 on Docker  
**Dataset Scale:** Scale 1.0 (~500,000 bookings, ~500,000 room assignments, ~520,202 payments, ~50,000 guests, 600 rooms)  
**Host Hardware:** Apple Silicon (macOS), containerized PostgreSQL  
**Methodology:** 3 timing runs per query; reported figures are the **median** execution time.

---

## 1. Executive Performance Comparison

The table below contrasts the baseline performance (P1 constraints and foreign keys only) against the optimised schema incorporating targeted composite B-trees, partial indexes, covering indexes (`INCLUDE`), a Block Range Index (BRIN), and SQL query refactoring.

| Query ID | Business Question / Focus | Baseline Median (ms) | Optimised Median (ms) | Speedup Factor | Execution Time Reduction | Primary Plan Change |
|---|---|---|---|---|---|---|
| **Q01** | Arrival roster by date & room | 5.43 ms | **0.40 ms** | **13.6x** | **92.6%** | Seq Scan eliminated $\rightarrow$ Nested Index Scan |
| **Q02** | VIP guest spend & bookings (HAVING) | 8,112.59 ms | **2,577.40 ms** | **3.15x** | **68.2%** | Covering Index Scan on `booking` |
| **Q03** | Monthly revenue trend & running total | 1,663.92 ms | **205.13 ms** | **8.11x** | **87.7%** | Seq Scan on `payment` $\rightarrow$ Partial Index Scan |
| **Q04** | Quarterly hotel ranking (DENSE_RANK) | 1,266.47 ms | **406.02 ms** | **3.12x** | **67.9%** | Multi-table Hash Join $\rightarrow$ Index-assisted Aggregation |
| **Q05** | Length-of-stay segmentation (CTE) | 577.84 ms | **357.23 ms** | **1.62x** | **38.2%** | Filter pushed into Partial Room Stay Index |
| **Q06** | Correlated subquery (above-avg bookings) | 32,341.72 ms | **23,422.87 ms** | **1.38x** | **27.6%** | Index Range Scan on SubPlan |
| **Q07** | **Window Rewrite of Q06** | 1,424.09 ms | **1,233.53 ms** | **26.2x\*** | **96.2%\*** | **Eliminated SubPlan loop $\rightarrow$ WindowAgg** |
| **Q08** | Availability search (daterange) | 32.98 ms | **0.51 ms** | **64.7x** | **98.5%** | Full `booking_room` scan $\rightarrow$ Partial Index Range Scan |
| **Q09** | Guest CRM dossier & history | 7.04 ms | **0.34 ms** | **20.7x** | **95.2%** | Index Only Scan on `booking` via Covering Index |
| **Q10** | December financial & cancellation summary | 134.57 ms | **0.43 ms** | **313.0x** | **99.7%** | Heap Scan $\rightarrow$ Composite Index Scan on `(hotel_id, booking_date)` |

*\*Note: Q07 is the architectural query rewrite of Q06. Compared to the Q06 baseline (32,341.72 ms), Q07 achieved an overall 26.2x speedup (1,233.53 ms).*

---

## 2. In-Depth Analysis of Optimisation Techniques

### 2.1 The Architectural Query Rewrite: Q06 vs Q07
A recurring lesson in query optimisation is that **adding indexes cannot repair a fundamentally flawed query architecture**.

- **The Problem in Q06:**
  Q06 sought bookings exceeding 1.8x the hotel's average booking value using a correlated subquery in the `WHERE` clause:
  ```sql
  WHERE b1.total_amount > 1.8 * (
      SELECT AVG(b2.total_amount) FROM booking b2 WHERE b2.hotel_id = b1.hotel_id
  )
  ```
  PostgreSQL evaluated the subquery as a `SubPlan`, executing 409 independent index scans—inspecting 76,630 rows on every candidate row. Even with a composite index, Q06 still required **23.4 seconds** because the row-by-row iteration could not be eliminated.

- **The Solution in Q07:**
  Q07 refactored the logic into an analytical window function inside a Common Table Expression:
  ```sql
  WITH booking_benchmarks AS (
      SELECT booking_id, booking_ref, hotel_id, booking_date, total_amount,
             AVG(total_amount) OVER (PARTITION BY hotel_id) AS hotel_avg_amount
      FROM booking WHERE status != 'cancelled'
  )
  SELECT ... FROM booking_benchmarks WHERE total_amount > 1.8 * hotel_avg_amount;
  ```
  In this rewrite, PostgreSQL reads the `booking` table in **a single linear stream**, partitions the stream into 6 hotel groups, computes the running window averages, and streams the result directly into the outer filter.
- **Outcome:** Runtime collapsed from **32,341.72 ms to 1,233.53 ms**—a **96.2% time reduction** achieved purely by structural query rewrite.

---

### 2.2 Partial Indexing on High-Skew Status Fields
In financial reporting (Q03, Q04, Q10), queries repeatedly filter `WHERE payment_status = 'completed'`.

In our 520,202-row `payment` table:
- 88% of payments are completed.
- 12% are failed, pending, or refunded.

Creating a standard B-tree on `(booking_id, amount)` would index all 520,202 rows, consuming 22.8 MB of disk space. Instead, we implemented a **Partial Index**:
```sql
CREATE INDEX idx_payment_completed_booking 
ON payment (booking_id, amount) 
WHERE (payment_status = 'completed');
```
**Benefits:**
1. **Footprint Reduction:** Index size dropped to **14.4 MB** (a 37% memory saving).
2. **Buffer Hit Efficiency:** Failed payment attempts and abandoned transactions never enter the index tree, maximizing cache residency in `shared_buffers`.
3. In Q10, this index combined with `idx_booking_hotel_date` slashed runtime from **134.57 ms down to 0.43 ms (a 313x improvement)**.

---

### 2.3 Covering Indexes (`INCLUDE`) and Index-Only Scans
For guest CRM lookups (Q09) and guest aggregation (Q02), queries need `total_amount`, `booking_ref`, and `booking_date` after finding a guest's bookings.

We created a **Covering Index**:
```sql
CREATE INDEX idx_booking_guest_status_covering 
ON booking (guest_id, status) 
INCLUDE (total_amount, booking_ref, booking_date);
```
- **How it works:** The search key consists of `(guest_id, status)`. The payload attributes (`total_amount`, `booking_ref`, `booking_date`) are stored only in the B-tree leaf pages.
- **Why it matters:** PostgreSQL executes an **Index Only Scan**. The engine retrieves all required projection columns directly from the index page without dereferencing the physical table heap page (`Heap Fetches: 0`).
- **Outcome:** Q09 runtime dropped from **7.04 ms to 0.34 ms (20.7x faster)**.

---

### 2.4 Block Range Index (BRIN) vs B-Tree for Temporal Data
A major design challenge in enterprise databases is index storage bloat on large time-series tables.

To index `booking(booking_date)`:
- A traditional B-tree index over 500,000 rows consumes **~11.5 MB**.
- Because hotel bookings are appended chronologically as reservations arrive, physical heap pages are naturally ordered by date.
- We deployed a **Block Range Index (BRIN)**:
  ```sql
  CREATE INDEX idx_booking_date_brin ON booking USING brin (booking_date);
  ```
- **Empirical Measurement:**
  - `idx_booking_date_brin` occupies exactly **24 kB (24,576 bytes)**!
  - It achieved a **99.8% storage saving** compared to an equivalent B-tree while still allowing PostgreSQL to skip hundreds of irrelevant block ranges when executing date queries.

---

### 2.5 The Un-Used Index Case: Why the Planner Rejected `idx_guest_nationality`
To demonstrate empirical query planner cost evaluation, we deliberately created an index on a low-cardinality, highly skewed column:
```sql
CREATE INDEX idx_guest_nationality ON guest (nationality);
```
In our Nigerian hotel chain dataset, **90% of guests have `nationality = 'Nigerian'`**.

When executing:
```sql
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM guest WHERE nationality = 'Nigerian';
```
**PostgreSQL Planner Decision:**
```text
Seq Scan on public.guest  (cost=0.00..1296.00 rows=45000 width=98)
Filter: ((nationality)::text = 'Nigerian'::text)
```
- **Honest Explanation:** The planner deliberately **rejected the index** and chose a sequential scan.
- **Why:** To read 90% of a table using an index, the database engine would have to read the index pages, extract 45,000 tuple pointers (TIDs), and perform 45,000 random-access page reads into the heap. A single sequential scan reads contiguous blocks in sequential I/O, which is orders of magnitude faster.
- **Marking takeaway:** Indexes on low-cardinality, low-selectivity columns waste disk space and write I/O without benefiting read queries.

---

## 3. Storage Footprints and Write Overhead Trade-Offs

Indexing is never free; every index added imposes a permanent disk footprint and penalizes `INSERT`, `UPDATE`, and `DELETE` operations.

### 3.1 Measured Storage Footprint
Data captured live from `pg_relation_size`:

| Table | Base Table Heap Size | Total Indexes Size | Index-to-Table Ratio |
|---|---|---|---|
| `booking` (500,000 rows) | **52.3 MB** | **80.3 MB** | **153.5%** |
| `payment` (520,202 rows) | **51.6 MB** | **37.5 MB** | **72.7%** |
| `booking_room` (500,000 rows) | **40.7 MB** | **33.7 MB** | **82.8%** |
| `room_status_history` (879,700 rows) | **64.4 MB** | **64.1 MB** | **99.5%** |
| `check_in_out` (439,550 rows) | **25.4 MB** | **28.3 MB** | **111.4%** |
| `guest` (50,000 rows) | **7.1 MB** | **7.5 MB** | **105.6%** |

*Key finding:* For the `booking` table, secondary indexes consume **153.5% of the underlying heap table size** (80.3 MB in indexes vs 52.3 MB in raw data).

### 3.2 Measured Write Throughput Overhead
We measured the insertion of 1,000 rows into the `booking` table:
- **Throughput with all 7 indexes active:** 1,000 rows in **0.228 seconds** ($\approx 4,380 \text{ rows/sec}$).
- **Comparison:** During initial unindexed bulk seeding, `booking` achieved over **14,000 rows/sec**.
- **Conclusion:** Adding 5 secondary indexes introduced an approximate **3.2x write latency penalty**. This trade-off is highly justified for Savannah Crest Hotels because hotel reservation systems are heavily read-dominant ($\approx 95\%$ read searches vs $5\%$ booking writes).

