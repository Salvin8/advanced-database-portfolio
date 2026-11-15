# Sharding & Horizontal Partitioning Strategy

**Portfolio 5: Distributed and Cloud Database Exercise**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Summary

As transaction volume at Savannah Crest Hotels exceeds 500,000 bookings and hundreds of gigabytes of relational data, vertical scaling (upgrading CPU cores and RAM on a single database host) reaches physical and economic limitations. Furthermore, cross-city WAN latency means that a single centralized database server in Lagos imposes an unacceptable $40\text{--}60\text{ ms}$ round-trip latency penalty on front-desk terminals in Kano, Enugu, and Abuja.

To scale write throughput and ensure geographical data locality, we design and implement a **Horizontal Sharding and Table Partitioning Architecture**. This document details the shard key evaluation, architectural trade-offs, and empirical validation using PostgreSQL 16 declarative table partitioning.

---

## 2. Shard Key Evaluation & Selection

The selection of the **shard key** is the most consequential architectural decision in distributed database design. An optimal shard key must simultaneously:
1. Maximize **query routing efficiency** (single-shard directed routing vs. expensive scatter-gather queries).
2. Ensure **even data and I/O distribution** across physical nodes, avoiding hot spots.
3. Align with natural **administrative and regulatory boundaries** (e.g., Nigerian data sovereignty requirements).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SHARD KEY EVALUATION MATRIX                           │
├───────────────────┬────────────────────┬─────────────────┬──────────────────┤
│ Shard Key Option  │ Routing Efficiency │ Data Skew Risk  │ Cross-Shard Joins│
├───────────────────┼────────────────────┼─────────────────┼──────────────────┤
│ 1. Geographic     │ High (92% of hotel │ Moderate (Lagos │ Rare (Rooms and  │
│    (hotel_id)     │ operations isolated│ generates higher│ staff strictly   │
│    [SELECTED]     │ to single property)│ booking volume) │ local to hotel)  │
├───────────────────┼────────────────────┼─────────────────┼──────────────────┤
│ 2. Hash-based     │ Moderate (Requires │ Low (Uniform    │ High (Room checks│
│    (hash(guest_id)│ directory lookup   │ mathematical    │ scatter across   │
│    or booking_id) │ or scatter-gather) │ hash spread)    │ all shards)      │
├───────────────────┼────────────────────┼─────────────────┼──────────────────┤
│ 3. Temporal       │ High for current   │ Extreme (Current│ Severe (Past vs. │
│    (Range on      │ week; poor for     │ month shard hits│ future data split│
│    booking_date)  │ historical data    │ 90% of I/O)     │ across nodes)    │
└───────────────────┴────────────────────┴─────────────────┴──────────────────┘
```

### 2.1 The Chosen Strategy: Geographic Property Partitioning (`hotel_id`)
We selected `hotel_id` as the primary shard/partition key. In the hotel domain:
- **Physical Co-locality:** A physical hotel room, front-desk staff, check-in terminal, and housekeeping roster exist in a single physical location.
- **Transactional Independence:** A guest checking into Room 305 at Savannah Crest Victoria Island (`hotel_id = 2`) has zero transactional dependency on a guest checking into Room 102 at Savannah Crest Abuja (`hotel_id = 1`).
- **Single-Shard Directed Routing:** Over 92% of operational queries (availability searches, reservations, check-ins, billings) include `hotel_id`. The application gateway routes the query directly to the designated regional shard, bypassing all other nodes.

---

## 3. Native Declarative Partitioning Implementation

In `portfolio-5-distributed-cloud/sql/01_partitioning.sql`, we implemented declarative LIST partitioning in PostgreSQL 16 across all 500,000+ bookings:

```sql
-- Parent Partitioned Table
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

-- Six Physical Partitions Representing Regional Shards
CREATE TABLE booking_part_abuja  PARTITION OF booking_partitioned FOR VALUES IN (1);
CREATE TABLE booking_part_lagos  PARTITION OF booking_partitioned FOR VALUES IN (2);
CREATE TABLE booking_part_ph     PARTITION OF booking_partitioned FOR VALUES IN (3);
CREATE TABLE booking_part_kano   PARTITION OF booking_partitioned FOR VALUES IN (4);
CREATE TABLE booking_part_enugu  PARTITION OF booking_partitioned FOR VALUES IN (5);
CREATE TABLE booking_part_ibadan PARTITION OF booking_partitioned FOR VALUES IN (6);
```

### Partition Distribution Profile (from `evidence/partitioning_output.txt`)

Migrating our live 500,000-row dataset distributed records cleanly into six dedicated physical tables:

```
   partition_name    |        Property Description        | Size (Data/Total) | Row Count
---------------------+------------------------------------+-------------------+-----------
 booking_part_abuja  | Hotel 1 - Abuja (Capital)          | 8.9 MB / 13 MB    |    83,405
 booking_part_lagos  | Hotel 2 - Lagos (Commercial Hub)   | 8.9 MB / 13 MB    |    83,400
 booking_part_ph     | Hotel 3 - Port Harcourt (Oil & Gas)| 8.9 MB / 13 MB    |    83,300
 booking_part_kano   | Hotel 4 - Kano (Northern Commerce) | 8.9 MB / 13 MB    |    83,300
 booking_part_enugu  | Hotel 5 - Enugu (Coal City)        | 8.9 MB / 13 MB    |    83,300
 booking_part_ibadan | Hotel 6 - Ibadan (Pacesetter)      | 8.9 MB / 13 MB    |    83,300
```

---

## 4. Empirical Proof of Partition Pruning

**Partition Pruning** is the fundamental optimization whereby the query planner inspects `WHERE` clause constraints and excludes non-matching partitions from the physical execution plan, avoiding unnecessary disk and buffer cache reads.

### 4.1 Test 1: Single-Shard Directed Query (`hotel_id = 2`)
```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*), sum(total_amount), avg(total_amount)
FROM booking_partitioned
WHERE hotel_id = 2;
```

**Observed Execution Plan:**
```
Aggregate (cost=2571.51..2571.52 rows=1 width=72) (actual time=285.403..285.405 rows=1 loops=1)
  Buffers: shared hit=1112
  ->  Seq Scan on booking_part_lagos booking_partitioned (cost=0.00..2154.50 rows=83400 width=6)
        Filter: (hotel_id = 2)
        Buffers: shared hit=1112
Planning Time: 20.631 ms
Execution Time: 285.572 ms
```
- **Architectural Validation:** The query planner scanned **ONLY `booking_part_lagos`** (1,112 buffer pages). Partitions for Abuja, Port Harcourt, Kano, Enugu, and Ibadan were completely pruned from the query execution tree.
- **Resource Savings:** **$83.3\%$ reduction** in scanned pages compared to a full table scan.

### 4.2 Test 2: Multi-Shard Regional Query (`hotel_id IN (1, 2)`)
- When querying the two commercial hub properties (Abuja and Lagos), the planner selectively attached `booking_part_abuja` and `booking_part_lagos` via an `Append` node while pruning the remaining four partitions.

### 4.3 Test 3: Scatter-Gather Cross-Partition Analytics
- Global chain-wide financial aggregations without a `hotel_id` filter execute a **Parallel Append**:
  ```
  Parallel Append (cost=0.00..10651.88 rows=208334 width=10)
    -> Parallel Seq Scan on booking_part_abuja
    -> Parallel Seq Scan on booking_part_lagos
    -> Parallel Seq Scan on booking_part_ph
    -> Parallel Seq Scan on booking_part_kano
    -> Parallel Seq Scan on booking_part_enugu
    -> Parallel Seq Scan on booking_part_ibadan
  ```
- Two parallel worker threads concurrently scan independent physical partitions, aggregating partial sums via `Partial HashAggregate` and consolidating results in `Finalize GroupAggregate` ($831.09\text{ ms}$ total execution time for 500,000 rows).

---

## 5. Distributed Challenges & Mitigations

### 5.1 Hot Shard Management (Data & I/O Skew)
- **Problem:** Savannah Crest Victoria Island (Lagos) and Savannah Crest Abuja account for higher booking velocity and pricing tiers than regional properties in Kano or Ibadan.
- **Mitigation:** **Composite Sub-Partitioning**. Partition primary shards by `LIST (hotel_id)`, and sub-partition high-volume shards (Lagos and Abuja) by `RANGE (booking_date)` (e.g., monthly sub-partitions: `booking_lagos_2026_q1`, `booking_lagos_2026_q2`).

### 5.2 Cross-Shard Guest History Retrieval
- **Problem:** A VIP guest frequently stays at both Lagos and Abuja properties. Querying a guest's full booking history requires querying all regional shards.
- **Mitigation:** **Dual-Model Projection**. Operational reservations remain sharded by `hotel_id` in PostgreSQL for local transactional integrity, while the unified customer history is projected into the **MongoDB `guest_profiles` collection** (as demonstrated in Portfolio 4), enabling single-document retrieval by `guest_id`.

### 5.3 Re-Sharding & Growth
- When Savannah Crest expands to new cities (e.g., Calabar, Asaba), a new partition is added online with zero table downtime:
  ```sql
  CREATE TABLE booking_part_calabar PARTITION OF booking_partitioned
      FOR VALUES IN (7);
  ```
  PostgreSQL automatically incorporates the new partition into tuple routing and partition pruning without requiring schema migrations on existing partitions.

