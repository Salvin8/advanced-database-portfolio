# Individual Technical Reflection

**MIT 8103 Advanced Database Systems**  
**Student:** Tobias Salvin  
**Project:** Savannah Crest Hotels Management System

---

## 1. Design Choices I Made

Throughout this project, I deliberately avoided generic, one-size-fits-all architectures in favour of targeted technical decisions grounded in the operational reality of a multi-city Nigerian hotel chain:

1. **Storage-Level Double-Booking Prevention (PostgreSQL GiST):**  
   Rather than relying on application-level locks or standard SQL `CHECK` constraints (which cannot inspect other rows), I leveraged PostgreSQL's `btree_gist` extension to enforce an interval exclusion constraint (`EXCLUDE USING gist (room_id WITH =, stay WITH &&)`). Defining `stay` as a generated stored `daterange` with closed-open `[)` bounds mathematically eliminates overlapping reservations at the kernel storage level, supporting same-day turnaround while completely shielding the system from Time-of-Check to Time-of-Use (TOCTOU) race conditions.

2. **Index Engineering over Blind Indexing:**  
   In Portfolio 2, I resisted indexing every foreign key indiscriminately. Instead, I analyzed query execution plans (`EXPLAIN (ANALYZE, BUFFERS)`). Recognizing that physical booking records are inserted sequentially by date, I deployed a **BRIN (Block Range Index)** on `booking_date`. This achieved an astonishing **$99.8\%$ space reduction** compared to a conventional B-tree (24 kB vs. 11.5 MB) while accelerating chronological range queries. Furthermore, rewriting the correlated subquery Q06 into window functions (Q07) yielded a **$26.2\times$ speedup** without any new index, cementing my understanding that structural query algebra often outperforms brute-force indexing.

3. **Polyglot Three-Tier Architecture:**  
   I selected **MongoDB 7.0** specifically for read-heavy Customer 360 dossiers. Collapsing five normalised tables into a single `guest_profiles` document eliminated multi-table joins for mobile applications. Concurrently, I deployed **Redis 7.4** under a Cache-Aside pattern for room availability lookups, accelerating response times from $29.7\text{ ms}$ to $1.5\text{ ms}$ ($19.1\times$ speedup).

4. **Geographic Horizontal Partitioning & Saga Orchestration:**  
   In Portfolio 5, I partitioned the 500,000-row `booking` table by `LIST (hotel_id)`. Because hotel rooms and front-desk terminals are strictly localized, this allowed single-shard directed routing and empirical partition pruning ($83.3\%$ I/O reduction). Across distributed microservices, I implemented the **Saga Pattern with Orchestration**, replacing rigid, blocking Two-Phase Commit (2PC) protocols with flexible forward actions and automated compensating rollbacks.

---

## 2. Challenges I Faced and How I Solved Them

Building and testing this system against live Docker containers surfaced several non-trivial technical challenges that forced me to delve deeply into database engine internals:

1. **Inverted Date Constraint vs. Generated Column Conflict:**  
   In Portfolio 1, my automated constraint tests attempted to insert an invalid booking with `check_in = 2026-12-10` and `check_out = 2026-12-05`. The test initially failed because it caught only `check_violation`. However, PostgreSQL threw a `data_exception` (_"range lower bound must be less than or equal to range upper bound"_). I realized that PostgreSQL evaluates the generated stored `daterange` column _before_ evaluating table-level `CHECK` constraints. I resolved this by updating the PL/pgSQL test harness exception handler to trap `check_violation OR data_exception`.

2. **Stored Procedure Variable Length Truncation:**  
   When writing the enterprise stored procedure `sp_make_reservation` in Portfolio 3, testing the exclusion constraint violation caused PostgreSQL to raise `ERROR: value too long for type character varying(50)` on the output parameter `p_status`. The auto-generated constraint violation message exceeded 50 characters. I resolved this by expanding the output parameter to unbounded `TEXT`, ensuring diagnostic clarity without runtime truncation.

3. **Synchronizing Concurrent Threads for Serializable Write Skew:**  
   Reproducing Write Skew under Serializable Snapshot Isolation (SSI) in Python proved challenging. My initial test used a single thread barrier; however, Agent B began reading _after_ Agent A had already committed, causing B to observe A's write and abort gracefully rather than triggering a true concurrent conflict. I resolved this by architecting a dual synchronization mechanism: two `threading.Barrier(2)` rendezvous points forcing both agents to enter their transactions and execute their concurrent reads in parallel snapshots, followed by a `threading.Event()` coordinating simultaneous commits. This reliably forced PostgreSQL's SSI predicate lock manager to identify a rw-antidependency cycle and abort Agent B with `SQLSTATE 40001` (_Reason code: Canceled on identification as a pivot_).

4. **Idempotency in Distributed Saga Orchestration:**  
   In Portfolio 5, repeated runs of `saga_orchestrator.py` caused downstream room conflicts because previously committed demo bookings held room availability. I solved this by implementing an idempotent setup step that systematically purges `SAGA-%` booking references and tokens before starting, ensuring 100% automated repeatability.

---

## 3. What I Learned

This coursework transformed theoretical database concepts into tangible, empirical engineering instincts:

- **PostgreSQL Internals:** I developed a concrete understanding of Write-Ahead Logging (WAL), tuple visibility via MVCC commit logs (CLOG/pg_xact), and how predicate locks (`SIREAD`) detect serialization anomalies without physically locking rows.
- **Index Mechanics:** I learned how covering indexes (`INCLUDE`) enable pure Index-Only Scans by storing non-key attributes in leaf pages, and how BRIN indexes summarize page ranges with minimal memory footprint.
- **NoSQL Boundaries:** I discovered that MongoDB's single-document atomicity is exceptionally powerful for bounded nested hierarchies, but cannot replace relational interval exclusion constraints when managing global, shared resource pools.
- **Distributed Realities:** Implementing the Saga pattern clarified that in cloud environments, achieving absolute consistency across independent networks is an illusion; systems must embrace eventual consistency and graceful semantic compensation.

---

## 4. What I Would Do Differently

If I were to start this project again from scratch:

1. **Live Change Data Capture (CDC):** Instead of using a Python ETL script to project relational data into MongoDB, I would configure a live **Debezium** connector reading PostgreSQL's logical replication stream (`pgoutput`) through an Apache Kafka message broker to stream real-time document updates.
2. **Multi-Host Sharding with Citus:** I would deploy a multi-node cluster using the **Citus** extension to demonstrate true distributed sharding across separate physical container IP addresses, rather than single-engine declarative table partitioning.
3. **Probabilistic Caching:** In Redis, I would implement the **XFetch probabilistic early expiration algorithm** to benchmark automated cache recomputation under simulated high-concurrency traffic.

---

## 5. Connection to Course Concepts

Every component of this coursework directly reflects the theoretical core of **MIT 8103**:

- **Relational Design & Normalisation:** The decomposition of guest folios into BCNF reinforced the functional dependency theory and Armstrong's axioms covered in Lecture 2.
- **Query Trees & Cost-Based Optimisation:** Examining `EXPLAIN (ANALYZE, BUFFERS)` plans brought textbook query trees, relational algebra pushdown predicates, and join algorithm trade-offs (Nested Loop vs. Hash Join vs. Merge Join) to life.
- **Concurrency & Serializability:** Demonstrating the impossibility of Dirty Reads under MVCC and reproducing Write Skew grounded textbook concepts of Conflict Serializability, View Serializability, and Snapshot Isolation in concrete code.
- **Distributed Consensus & CAP:** The trade-offs between 2PC blocking hazards, Raft consensus in Patroni, and Saga compensating transactions directly validated the CAP and PACELC theorems studied in distributed database architectures.
