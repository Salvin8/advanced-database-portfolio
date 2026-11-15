# Portfolio 5: Distributed and Cloud Database Exercise

**Coursework:** Advanced Database Systems (MIT 8103)  
**System:** Savannah Crest Hotels Management System  
**Author:** Mubarak  
**Technologies:** PostgreSQL 16 (Declarative Partitioning, Streaming Replication), MongoDB 7.0, Redis 7.4, Python 3.12 (psycopg, Saga Orchestration)

---

## 1. Executive Summary

As Savannah Crest Hotels expands across six Nigerian metropolitan cities (Abuja, Lagos, Port Harcourt, Kano, Enugu, and Ibadan), operating on a centralized monolithic database server introduces significant latency penalties ($40\text{--}60\text{ ms}$ inter-city round-trips), single-point-of-failure vulnerabilities, and vertical scalability limits.

Portfolio 5 investigates, designs, and validates the **Distributed and Cloud Database Architecture** required for multi-region hospitality operations:
1. **CAP & PACELC Trade-Off Analysis:** Classifies system capabilities into **Consistency-first (CP / PC/EC)** for room reservations and financial ledgers versus **Availability-first (AP / PA/EL)** for guest reviews and public hotel browsing.
2. **Horizontal Sharding & Table Partitioning:** Implements native PostgreSQL 16 declarative LIST partitioning on `hotel_id` across 500,000+ bookings, empirically proving **Partition Pruning** ($83.3\%$ reduction in scanned buffer pages for single-property queries).
3. **Multi-Region Replication & Disaster Recovery:** Establishes a two-tier replication topology with synchronous local replication in Lagos ($\text{RPO} = 0$) and asynchronous cross-region replication to Abuja, protected against split-brain via Raft consensus (Patroni).
4. **Distributed Saga Pattern Orchestrator:** Implements an automated state machine in Python coordinating multi-service transactions across Inventory, Payment, and Notification services, demonstrating backward compensating rollbacks on payment declines.

---

## 2. Repository Structure

```
portfolio-5-distributed-cloud/
├── README.md                      # Comprehensive Portfolio 5 documentation & viva guide
├── docs/
│   ├── cap-and-pacelc.md          # CAP/PACELC theoretical framework & Lagos-Abuja WAN failure scenario
│   ├── sharding-strategy.md       # Shard key evaluation, data skew management, & partition pruning
│   ├── replication-topology.md    # Multi-region HA, sync/async trade-offs, & Patroni Raft failover
│   └── distributed-transactions.md# 2PC analysis, Saga Orchestrator mechanics, & Outbox pattern
├── sql/
│   └── 01_partitioning.sql        # Native declarative LIST partitioning DDL, migration, & EXPLAIN tests
├── scripts/
│   └── saga_orchestrator.py       # Distributed Saga state machine with compensating rollbacks & retries
├── infra/
│   └── distributed_cluster_example.yml # Production multi-node Docker Compose blueprint (PG HA + Mongo RS + Redis Sentinel)
├── evidence/
│   ├── partitioning_output.txt    # Live execution log showing partition creation, row distribution, & pruning
│   └── saga-orchestrator-output.txt# Live execution log of Happy Path, Compensating Rollback, & Idempotent Retry
└── screenshots/
    └── README.md                  # Catalog of visual artifacts (stashed pending post-project)
```

---

## 3. Core Architectural Implementations

### 3.1 Declarative Horizontal Table Partitioning
In `sql/01_partitioning.sql`, the 500,000-row `booking` table is decomposed into six dedicated physical partitions based on `hotel_id`:

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

### 3.2 Empirical Validation of Partition Pruning
Querying for reservations at Savannah Crest Victoria Island (`hotel_id = 2`):

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*), sum(total_amount), avg(total_amount)
FROM booking_partitioned
WHERE hotel_id = 2;
```

**Observed Query Execution Plan (from `evidence/partitioning_output.txt`):**
```
Aggregate (cost=2571.51..2571.52 rows=1 width=72) (actual time=285.403..285.405 rows=1 loops=1)
  Buffers: shared hit=1112
  ->  Seq Scan on booking_part_lagos booking_partitioned (cost=0.00..2154.50 rows=83400 width=6)
        Filter: (hotel_id = 2)
        Buffers: shared hit=1112
Planning Time: 20.631 ms
Execution Time: 285.572 ms
```
- **Pruning Verification:** The PostgreSQL planner inspected the `WHERE hotel_id = 2` clause during planning and completely excluded `booking_part_abuja`, `booking_part_ph`, `booking_part_kano`, `booking_part_enugu`, and `booking_part_ibadan`.
- **Result:** Read operations touched only 1,112 pages instead of scanning 6,685 pages across the unpartitioned relation ($83.3\%$ I/O reduction).

### 3.3 Distributed Saga Orchestration
Because modern distributed architectures cannot hold distributed locks across external microservices (Payment Gateway, SMS Dispatcher), `scripts/saga_orchestrator.py` coordinates multi-service bookings via forward transactions and compensating actions:

```
[ Happy Path (Scenario 1) ]
  Hold Room (Pending) ──► Charge Payment (Success) ──► Confirm Room (Confirmed) ──► Send Email/SMS

[ Compensating Rollback (Scenario 2) ]
  Hold Room (Pending) ──► Charge Payment (DECLINED) 
                               │
                               ▼
        Execute Compensating Action: Release Room Hold
        (Room marked CANCELLED; freed in inventory; audit notes logged)
```

Live database audit query confirms that after payment refusal, the room hold was cleanly cancelled with note:  
`CANCELLED BY SAGA COMPENSATION: Payment Authorization Refused by Issuing Bank.`

---

## 4. Execution & Verification Guide

All targets are automated in the root `Makefile`:

```bash
# Execute full Portfolio 5 workflow
make p5

# Run individual components
make p5-partitioning   # Applies declarative partitioning, migrates data, & runs pruning EXPLAIN
make p5-saga           # Executes the Python Saga Orchestrator across all 3 scenarios
```

---

## 5. Viva Voce Defense Preparation: Questions & Detailed Answers

### Q1: How does the CAP theorem apply to Savannah Crest Hotels during an inter-city fibre severance between Lagos and Abuja?
> **Answer:**  
> In any distributed network, physical partitions ($P$) are inevitable due to terrestrial fibre cuts or domestic ISP downtime. According to the CAP theorem ($P \implies C \oplus A$), during a partition, a system must choose between Consistency ($C$) and Availability ($A$).  
> 
> At Savannah Crest Hotels, we apply a **workload-segmented consistency model**:
> 1. **Core Reservation Engine (CP):** If the Abuja regional node cannot reach the primary cluster in Lagos to verify room availability and acquire locks, it **rejects the reservation with an explicit error**. Under CP semantics, refusing a transaction is preferable to allowing two guests in different cities to book the same Presidential Suite for the same dates.
> 2. **Guest Reviews & Catalog Browsing (AP):** Mobile users in Abuja can still browse hotel descriptions, view photographs, and submit guest reviews. Reviews are committed locally to MongoDB and synchronized to Lagos once the WAN connection restores, guaranteeing 100% user-facing availability.

---

### Q2: Why did you choose `hotel_id` as the partition key rather than `guest_id` or `booking_date`? What are the trade-offs?
> **Answer:**  
> We selected `hotel_id` (geographic property partitioning) because in the hotel domain, **physical resources and operational workflows are strictly co-located**:
> - Rooms, front-desk staff, check-in terminals, and housekeeping shifts belong to a single physical property.
> - Over $92\%$ of transaction volume (room searches, check-ins, guest folios) includes `hotel_id`. Partitioning by `hotel_id` enables **single-shard directed routing**, ensuring that transactions execute entirely on the local partition without cross-partition locks.  
> 
> **Trade-offs:**
> - *Disadvantage:* Querying a VIP guest's global booking history across all six properties requires a **scatter-gather query** (`Parallel Append` across all partitions). We mitigate this by projecting unified guest dossiers into our MongoDB `guest_profiles` read model.
> - *Why not `booking_date`?* Range partitioning on date creates severe **data skew**: current-month partitions absorb $90\%$ of active write traffic, leaving older partitions cold.

---

### Q3: Explain how PostgreSQL implements partition pruning. What empirical evidence proves that your partitioned table improved query efficiency?
> **Answer:**  
> **Partition Pruning** occurs during query planning or execution. The planner compares `WHERE` clause filter constants against the declared boundary expressions of each partition (in our case, `FOR VALUES IN (hotel_id)`). If the clause contradicts the partition boundary (e.g., `hotel_id = 2` contradicts `VALUES IN (1)`), the planner prunes that sub-table from the execution plan tree.  
> 
> **Empirical Evidence (from `evidence/partitioning_output.txt`):**
> - In `01_partitioning.sql`, executing `EXPLAIN (ANALYZE, BUFFERS) ... WHERE hotel_id = 2` produced a query plan containing strictly `Seq Scan on booking_part_lagos` touching **1,112 shared buffer hits**.
> - Partitions for Abuja, Port Harcourt, Kano, Enugu, and Ibadan were completely omitted from the plan.
> - Compared to scanning all 6 partitions (which requires 6,685 buffer page hits during global aggregations), static partition pruning achieved an **$83.3\%$ reduction in buffer I/O**, dramatically reducing CPU and memory bus contention.

---

### Q4: What is the difference between physical streaming replication and logical replication, and how are both used in your architecture?
> **Answer:**  
> - **Physical Streaming Replication:** Streams exact byte-for-byte binary Write-Ahead Log (WAL) records from primary to standby. The standby is a bitwise physical replica running in `Hot Standby` mode (read-only). It must run identical PostgreSQL versions and hardware architectures. In Savannah Crest Hotels, physical streaming replication powers our **High Availability and Disaster Recovery** strategy (synchronous replica in Lagos for $\text{RPO} = 0$, asynchronous replica in Abuja for regional DR).
> - **Logical Replication:** Employs the `pgoutput` plugin to decode WAL records into logical row-level DML events (`INSERT`, `UPDATE`, `DELETE`). It allows replicating selective tables, individual columns, and cross-version/cross-engine targets. In Savannah Crest Hotels, logical replication acts as our **Change Data Capture (CDC)** pipeline, streaming committed booking rows from PostgreSQL into the MongoDB `guest_profiles` collection.

---

### Q5: Why is Two-Phase Commit (2PC) considered anti-scalable in cloud microservices, and how does the Saga pattern solve this?
> **Answer:**  
> **Why 2PC Fails in Cloud Environments:**
> 1. **Blocking Protocol:** In 2PC, during the *Prepare* phase, participants acquire local database locks and vote `VOTE_COMMIT`. If the coordinator crashes before issuing `GLOBAL_COMMIT`, participants must hold locks indefinitely, blocking other transactions.
> 2. **Availability Degradation:** Compound availability equals the product of all service availabilities ($A_{\text{total}} = A_1 \times A_2 \times \dots$). If the external payment processor is slow or down, the entire database transaction blocks.
> 3. **Non-Transactional APIs:** External payment gateways (card issuers, Paystack) cannot participate in SQL prepare/commit protocols.  
> 
> **How the Saga Pattern Solves This:**
> A Saga breaks the distributed transaction into a sequence of **local transactions**. Each service commits its local transaction immediately without holding global locks. If a downstream step fails (e.g. card decline in Step 2), the Saga Orchestrator executes backward **Compensating Transactions** (e.g. `release_hold_compensating_action`) to semantically undo earlier steps, ensuring **eventual consistency** without distributed blocking locks.

---

### Q6: How does your architecture prevent Split-Brain during an automated failover event?
> **Answer:**  
> A **Split-Brain anomaly** occurs when a network partition causes a standby node to believe the primary is dead and promote itself, while the original primary continues accepting writes, causing diverged data sets.  
> 
> In Savannah Crest Hotels, split-brain is prevented using **Patroni with Raft Distributed Consensus (etcd)**:
> 1. **Odd-Numbered Majority Quorum:** The consensus cluster comprises 3 voting nodes (Lagos Node 1, Lagos Node 2, and an AWS Cape Town witness). A primary can only operate if it maintains a heartbeat with a strict majority ($> 50\%$) of voting nodes.
> 2. **Ephemeral Leader Lease:** The primary must renew a 10-second leader lock in etcd. If isolated, its lease expires.
> 3. **Fencing (STONITH):** Standby nodes verify with the majority before promoting. When an isolated former primary reconnects, Patroni detects that its lease was lost and uses `pg_rewind` to roll back any un-replicated local WAL blocks and demote it to a replica, ensuring strictly **one primary exists at any point in time**.
