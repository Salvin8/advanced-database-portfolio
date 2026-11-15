# Final Coursework Documentation & Executive Summary

**MIT 8103 Advanced Database Systems**  
**Individual Technical Portfolio**  
**Student:** Tobias Salvin  
**System:** Savannah Crest Hotels Management System  
**Date:** November 2026

---

## 1. Selected Organisation & System Scope

**Savannah Crest Hotels** is a simulated chain of six mid-range and luxury hotels located across major Nigerian commercial and cultural hubs:

- **Savannah Crest Abuja** (5-star, Maitama, Federal Capital)
- **Savannah Crest Victoria Island, Lagos** (5-star, Commercial Centre)
- **Savannah Crest Port Harcourt** (4-star, GRA Phase 2, Oil & Gas Hub)
- **Savannah Crest Kano Royal** (4-star, Nassarawa, Northern Commerce)
- **Savannah Crest Independence Layout, Enugu** (4-star, Eastern Gateway)
- **Savannah Crest Bodija, Ibadan** (3-star, Historical Pacesetter)

### System Scale & Workload Profile

The central reservation, property-management, and analytical database supports web and mobile bookings, front-desk check-ins, housekeeping operations, revenue auditing, and corporate reporting:

- **Scale:** 6 hotels, 4 room categories, 600 rooms, 60 staff members.
- **Data Volume:** 50,000 guests, 500,000+ bookings, 520,000+ financial payments, and 879,000+ housekeeping status history events spanning seven operational years (2020 through 2026).
- **Core Challenge:** Ensuring mathematically zero room double bookings under extreme concurrent booking surges, achieving sub-second operational reporting across large datasets, and architecting a resilient distributed multi-tier data platform.

---

## 2. Portfolio Summaries & Headline Empirical Results

### Portfolio 1: Database Design and Modelling

- **Relational Normalisation:** Decomposed un-normalised guest reservation folios through 1NF, 2NF, 3NF to Boyce-Codd Normal Form (BCNF), isolating entities into 12 relational tables with foreign keys and cascade rules (`ON DELETE RESTRICT` for financial ledgers).
- **Storage-Level Double-Booking Prevention:** Implemented PostgreSQL's `btree_gist` extension and an **interval exclusion constraint** (`EXCLUDE USING gist (room_id WITH =, stay WITH &&)` where `status IN ('reserved', 'checked_in')`). By computing `stay` as a generated stored `daterange(check_in_date, check_out_date, '[)')` with closed-open bounds, same-day checkout/check-in is supported without scheduling overlap.
- **Audit Logging & Triggers:** Implemented automatic timestamp triggers (`updated_at`) and JSONB audit triggers capturing before/after state transitions on sensitive booking and payment mutations.
- **Empirical Validation:** 8 automated constraint tests verified that inverted dates, negative rates, invalid star ratings, and overlapping room assignments are rejected at the storage engine level.

### Portfolio 2: Query Processing and Optimisation

- **10 Enterprise Queries:** Authored a benchmark suite spanning multi-table joins, subqueries, CTEs, window functions (`ROW_NUMBER()`, `DENSE_RANK()`), and temporal daterange overlap predicates.
- **Baseline Bottlenecks:** Baseline `EXPLAIN (ANALYZE, BUFFERS)` plans revealed massive Sequential Scans on 500,000 rows. Correlated subquery Q06 took $32,341\text{ ms}$ due to quadratic $\mathcal{O}(N^2)$ tuple comparisons.
- **Query Rewrite vs. Indexing:** Rewriting Q06 into window functions (Q07) reduced execution time from $32,341\text{ ms}$ to $1,233\text{ ms}$ ($26.2\times$ speedup) without adding a single index, proving that structural query algebra often outperforms raw indexing.
- **Targeted Index Engineering:** Designed 6 strategic indexes:
  - **Composite B-Tree Indexes:** Enabled Index-Only Scans.
  - **Covering Indexes (`INCLUDE`):** Eliminating heap fetches.
  - **BRIN (Block Range Index):** On physical append-only `booking_date`, consuming only **24 kB** compared to **11.5 MB** for equivalent B-trees ($99.8\%$ storage reduction).
  - **Overall Speedups:** Achieved speedups across all queries, with Q10 accelerating from $219.4\text{ ms}$ to $0.7\text{ ms}$ ($313.4\times$ speedup).

### Portfolio 3: Transactions and Concurrency Control

- **ACID & Stored Procedures:** Built atomic multi-table reservation transactions in PL/pgSQL (`sp_make_reservation`) with structured exception handlers intercepting exclusion constraint violations.
- **Rollback & Savepoints:** Demonstrated application-initiated rollbacks on card decline (leaving zero orphan records) and partial rollback via nested `SAVEPOINT` (reverting an optional failed airport transfer while committing the room booking).
- **Isolation Levels & Anomalies:** Empirical multi-session testing proved dirty reads are impossible in PostgreSQL (MVCC), captured non-repeatable reads under `READ COMMITTED`, and demonstrated automated retry loops intercepting `SQLSTATE 40001` Serialization Failures under `SERIALIZABLE` Snapshot Isolation (SSI).
- **The 4-Way Concurrency Shootout (Double-Booking Prevention):**
  Under 20 concurrent threads attempting to book the exact same room:
  1. _Unsafe (TOCTOU):_ Suffered 20 double bookings.
  2. _Pessimistic Locking (`FOR UPDATE`):_ 1 confirmed, 19 blocked/rejected.
  3. _GiST Exclusion Constraint:_ **1 confirmed, 19 rejected at kernel level** (Zero application lock overhead).
  4. _Optimistic Concurrency Control (OCC / CAS):_ 1 confirmed, 19 aborted via version mismatch.
- **Deadlock Resolution:** Reproduced `SQLSTATE 40P01` deadlocks via inverted locking order and eliminated them using strict canonical sorting (`ORDER BY room_id ASC`).

### Portfolio 4: NoSQL and Advanced Data Models

- **MongoDB 7.0 Document Model:** Denormalised 5 relational tables into `guest_profiles`, embedding bounded booking and payment histories with pre-aggregated statistics. Enforced strict typing and regex via MongoDB JSON Schema Validation (`$jsonSchema`).
- **Aggregation Framework:** Deployed 5 analytical pipelines ($unwind $\rightarrow$ $group $\rightarrow$ $sort) evaluating city revenue (Lagos leading at ₦222.89M) and room type yield (Presidential Suites averaging ₦410,072.73 per stay).
- **Index Plan Proof:** Benchmarked `find({ email: ... })` via `.explain("executionStats")`: `COLLSCAN` examined 200 documents, whereas `IXSCAN` examined exactly 1 document ($99.5\%$ reduction).
- **Redis 7.4 In-Memory Acceleration:** Deployed 5 data structures (Strings, Hashes, Lists, Sets, Sorted Sets). Implemented the **Cache-Aside Pattern**, slashing room availability search latency from $29.66\text{ ms}$ to $1.55\text{ ms}$ ($19.1\times$ speedup).

### Portfolio 5: Distributed and Cloud Database Exercise

- **CAP & PACELC Analysis:** Formulated a workload-segmented strategy: **Consistency-first (CP / PC/EC)** for core room reservations and payments versus **Availability-first (AP / PA/EL)** for public catalog browsing and guest reviews during regional WAN fibre disruptions.
- **Horizontal Table Partitioning:** Decomposed the 500,000-row `booking` table into 6 dedicated physical partitions based on `hotel_id`. Empirical `EXPLAIN` tests proved **Static Partition Pruning** (scanning only `booking_part_lagos` touching 1,112 buffers and pruning the other 5 partitions, achieving an **$83.3\%$ I/O reduction**).
- **High Availability & Replication:** Designed a multi-region topology combining synchronous local streaming replication in Lagos ($\text{RPO} = 0$) and asynchronous cross-region DR in Abuja, with Patroni Raft consensus for automated failover without Split-Brain.
- **Distributed Saga Orchestration:** Implemented a Python state machine coordinating Inventory, Payment, and Notification services, demonstrating automated backward compensating actions that cleanly cancel provisional holds upon credit card decline.

---

## 3. High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 SAVANNAH CREST UNIFIED DATA PLATFORM ARCHITECTURE           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [ CLIENT ACCESS LAYER ]                                                    │
│  Web Guests (Booking/Browse)  • Mobile App Users  • Front-Desk Hotel Staff  │
│                                      │                                      │
│                                      ▼                                      │
│  [ API GATEWAY & APPLICATION CLUSTER ]                                      │
│  FastAPI / Python Microservices • Saga Orchestrator • Read/Write Router     │
│                    │                                   │                    │
│      Read / Cache  │               Write /             │ Read Model Sync    │
│      Lookups       │               Transactional       │ (CDC Debezium)     │
│                    ▼                                   ▼                    ▼
│  ┌──────────────────────────┐     ┌──────────────────────────┐  ┌─────────┐ │
│  │   REDIS 7.4 TIER         │     │  POSTGRESQL 16 CLUSTER   │  │ MONGODB │ │
│  │  (In-Memory Cache / L1)  │     │ (System of Record / L2)  │  │   7.0   │ │
│  │  • Availability Caching  │     │  • Normalized 3NF/BCNF   │  │(Doc /L3)│ │
│  │  • Active Guest Sessions │     │  • GiST Exclusion Rules  │  │• Guest  │ │
│  │  • VIP Spend Leaderboard │     │  • Declarative Partition │  │  360    │ │
│  │  • Latency: ~ 1.5 ms     │     │  • Physical Sync Repl    │  │• CRM &  │ │
│  └──────────────────────────┘     │  • Multi-Region DR Standby│ │  Trends │ │
│                                   └──────────────────────────┘  └─────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Key Lessons & Engineering Insights

1. **Storage-Engine Integrity Outweighs Application Logic:** Relying on application-level checks to prevent double-booking invariably fails under concurrent race conditions (Time-of-Check to Time-of-Use). Enforcing exclusion constraints at the database storage engine kernel guarantee absolute correctness regardless of application concurrency.
2. **Indexing is a Trade-Off, Not a Silver Bullet:** Every secondary index imposes write amplification during `INSERT` and `UPDATE` operations. Specialized indexes like BRIN provide extraordinary space savings ($99.8\%$) on append-only time-series data with zero maintenance overhead.
3. **Polyglot Persistence is Essential for Scale:** No single database satisfies all non-functional requirements. Combining PostgreSQL (ACID & relational constraints), MongoDB (document read models), and Redis (in-memory acceleration) allows each technology to excel in its natural architectural domain.

---

## 5. Verification & Code Execution

The complete multi-portfolio platform is containerised and fully reproducible via the root `Makefile`:

```bash
# Bring up all three containers (PostgreSQL 16, MongoDB 7.0, Redis 7.4)
make up-all

# Run entire 5-portfolio test suite sequentially
make p1 p1-test    # Schema, triggers, and constraint tests
make p2            # Apply indexes and benchmark 10 queries
make p3            # ACID, isolation levels, concurrency, & deadlocks
make p4            # MongoDB document model & Redis Cache-Aside
make p5            # Declarative partitioning, pruning, & Saga orchestrator
```

---

## 6. Project Artifacts & Directory Links

- **Repository Root:** [README.md](file:///advanced-database-portfolio/README.md)
- **Portfolio 1 (Design & Modelling):** [portfolio-1-database-design/README.md](file:///advanced-database-portfolio/portfolio-1-database-design/README.md)
- **Portfolio 2 (Query Optimisation):** [portfolio-2-query-optimisation/README.md](file:///advanced-database-portfolio/portfolio-2-query-optimisation/README.md)
- **Portfolio 3 (Transactions & Concurrency):** [portfolio-3-transactions-concurrency/README.md](file:///advanced-database-portfolio/portfolio-3-transactions-concurrency/README.md)
- **Portfolio 4 (NoSQL Data Models):** [portfolio-4-nosql/README.md](file:///advanced-database-portfolio/portfolio-4-nosql/README.md)
- **Portfolio 5 (Distributed & Cloud):** [portfolio-5-distributed-cloud/README.md](file:///advanced-database-portfolio/portfolio-5-distributed-cloud/README.md)
- **Technical Reflection:** [docs/reflection.md](file:///advanced-database-portfolio/docs/reflection.md)
- **Academic References:** [docs/references.md](file:///advanced-database-portfolio/docs/references.md)
- **AI Use Declaration:** [docs/ai-use-declaration.md](file:///advanced-database-portfolio/docs/ai-use-declaration.md)
