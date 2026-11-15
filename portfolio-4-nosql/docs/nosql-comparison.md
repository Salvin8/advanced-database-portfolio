# Comparative Database Paradigms: Relational vs. Document vs. Key-Value

**Portfolio 4: NoSQL and Advanced Data Models**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Overview

Modern enterprise database architectures have shifted away from "one-size-fits-all" monolithic persistence toward **Polyglot Persistence**—matching specific storage engines to the distinct operational, transactional, and analytical requirements of individual business capabilities.

Within Savannah Crest Hotels, three database paradigms are deployed in concert:
1. **Relational Database Management System (RDBMS) — PostgreSQL 16:** The authoritative system of record for inventory consistency, double-booking prevention, financial ledgers, and complex relational reporting.
2. **Document-Oriented NoSQL Store — MongoDB 7.0:** The operational read model and Customer 360 repository, storing hierarchical, denormalised guest dossiers with embedded reservation histories for mobile applications and CRM analytics.
3. **In-Memory Key-Value / Data-Structure Store — Redis 7.4:** The ultra-low-latency acceleration tier for volatile session state, room availability caches, and atomic inventory counters.

This document provides a rigorous comparative evaluation of these paradigms across theoretical foundations, operational trade-offs, and empirical benchmarks.

---

## 2. Multi-Dimensional Comparison Matrix

| Architectural Dimension | PostgreSQL 16 (Relational) | MongoDB 7.0 (Document) | Redis 7.4 (Key-Value) |
| :--- | :--- | :--- | :--- |
| **Primary Data Model** | Normalised relations (tables, tuples, attributes) conforming to 3NF/BCNF | Hierarchical, semi-structured BSON documents with embedded sub-documents/arrays | In-memory key-value mappings with rich data structures (Strings, Hashes, Sets, ZSets) |
| **Storage Engine & Media** | Page-based buffer pool on persistent block storage; write-ahead logging (WAL) | WiredTiger engine with B-tree/LSM indexes, memory-mapped cache, checkpointing | In-memory RAM storage; optional persistence via RDB point-in-time snapshots and append-only file (AOF) |
| **CAP Theorem Classification** | **CA / CP** (Consistent, Partition-tolerant within managed cluster) | **CP** (Consistent under network partition with configurable read concerns) | **CP / AP** (Configurable: asynchronous replication favours AP; Redis Raft favours CP) |
| **Consistency Model** | Strict Serializability / Read Committed / Repeatable Read (ANSI SQL) | Strong consistency for single documents; causal consistency across replica sets | Eventual consistency across replicas; strong single-thread consistency on primary |
| **Transaction Scope** | Multi-table, multi-row ACID transactions with arbitrary SQL operations | ACID per single document; multi-document ACID transactions available via two-phase commit | Atomic single-command execution; multi-command transactions via `MULTI`/`EXEC` (no rollbacks) |
| **Concurrency Control** | Multiversion Concurrency Control (MVCC) + strict row/table lock manager | WiredTiger ticket-based optimistic concurrency control + document-level locking | Single-threaded multiplexed event loop (`epoll`/`kqueue`); lock-free in-memory execution |
| **Constraint Enforcement** | Declarative PKs, FKs, CHECK constraints, and exclusion constraints (`EXCLUDE USING gist`) | JSON Schema validation (`$jsonSchema`) at database boundary; no declarative foreign keys | None natively; application logic must validate data types and integrity |
| **Query Expressiveness** | Declarative SQL (ANSI SQL:2016) with window functions, recursive CTEs, and lateral joins | MongoDB Query Language (MQL) and multi-stage Aggregation Pipeline (`$unwind`, `$group`) | Imperative command set tailored to data structure primitives (e.g., `HGETALL`, `ZREVRANGE`) |
| **Schema Evolution** | Rigid; requires DDL (`ALTER TABLE`) which can incur metadata locks | Dynamic / polymorphic; fields can be introduced without downtime or table rewrites | Schemaless; key namespace conventions enforced solely by client applications |
| **Horizontal Scalability** | Challenging; read replicas natively supported, but sharding requires extensions (e.g. Citus) | First-class native horizontal sharding based on shard keys across config servers and routers | Sharding via Redis Cluster (16,384 hash slots); partitioning across master nodes |
| **Typical Read Latency** | $\approx 2.0 - 30.0\text{ ms}$ (depending on buffer cache hit ratio and disk I/O) | $\approx 1.0 - 10.0\text{ ms}$ (depending on document size and index selectivity) | $\approx 0.1 - 1.5\text{ ms}$ (pure in-memory memory bus traversal) |

---

## 3. Theoretical Foundations: CAP & PACELC

### 3.1 CAP Theorem Positioning

The CAP theorem (Brewer, 2000; Gilbert & Lynch, 2002) states that a distributed data store can guarantee at most two of three properties under network failure: **Consistency (C)**, **Availability (A)**, and **Partition Tolerance (P)**.

```
                      Consistency (C)
                         /       \
                        /  RDBMS  \
                       / (Single-  \
                      /    Node)    \
                     /               \
        Availability (A) ─────────── Partition Tolerance (P)
              (Redis w/              (MongoDB Replica Sets,
               Async Repl)            PostgreSQL Citus/Patroni)
```

1. **PostgreSQL 16:** Operates as a single-node primary with synchronous/asynchronous physical streaming replication. In high-availability configurations (e.g., Patroni with Raft/etcd), it prioritises **Consistency** over Availability during network partitions, refusing writes if a quorum cannot be acknowledged.
2. **MongoDB 7.0:** Classified as a **CP system**. In a replica set with a primary and secondary nodes, if the primary is isolated from the majority during a network partition, it steps down to secondary. Write operations requiring majority write concern (`w: "majority"`) will block or fail, guaranteeing that split-brain writes never commit.
3. **Redis 7.4:** Operates by default with asynchronous master-replica replication. In the event of a network partition between master and replica, the master continues accepting writes, risking data loss upon failover (favouring **Availability** over Consistency). However, with Redis Sentinel and `min-replicas-to-write`, it can be configured toward CP.

### 3.2 PACELC Extension
The PACELC theorem (Abadi, 2012) extends CAP by describing system behavior **when there is no partition**: *If there is a Partition (P), how does the system trade off Availability (A) and Consistency (C); Else (E), how does it trade off Latency (L) and Consistency (C)?*

- **PostgreSQL:** **PC/EC** — Prioritises consistency both during partitions and during normal operations (WAL write-ahead flushes before transaction commit).
- **MongoDB:** **PC/EC** with default write concerns, or **PC/EL** when reading from secondaries (`readPreference: "secondaryPreferred"`) to trade consistency for lower read latency.
- **Redis:** **PA/EL** — Prioritises low latency and availability; reads and writes complete in RAM immediately without synchronous disk or replica synchronization.

---

## 4. ACID vs. BASE Paradigm Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       TRANSACTIONAL SPECTRUM                                │
├──────────────────────────────────────┬──────────────────────────────────────┤
│               ACID                   │                BASE                  │
│       (PostgreSQL 16)                │         (MongoDB / Redis)            │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ Atomicity: All or nothing            │ Basically Available: System remains  │
│ Consistency: Valid state to valid    │ operational despite node failures    │
│ Isolation: Concurrency anomalies     │ Soft state: State may drift over     │
│            strictly prevented        │ time without active user interaction │
│ Durability: Committed data survives  │ Eventual consistency: Data converges │
│             crashes (fsync to disk)  │ once network updates propagate       │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

### 4.1 Consistency in PostgreSQL
PostgreSQL enforces the highest standard of relational consistency:
- **Storage-Level Integrity:** Check constraints, foreign keys, unique indexes, and GiST exclusion constraints are enforced synchronously on every `INSERT` and `UPDATE`.
- **Anomalies Prevented:** Configurable from `READ COMMITTED` to `SERIALIZABLE`, eliminating dirty reads, non-repeatable reads, phantom reads, and serialization write skews (via SIREAD predicate locks).

### 4.2 Single-Document Consistency in MongoDB
MongoDB replaces multi-table normalization with single-document atomicity:
- Because all related entities (guest details, bookings, payments) reside within the same BSON document, modifications that add bookings (`$push`) and update lifetime spend (`$inc`) commit atomically within WiredTiger.
- Cross-document consistency, however, relies on application-level orchestration or heavier multi-document transactions.

### 4.3 Lock-Free Atomicity in Redis
Redis achieves atomicity without traditional database locks:
- Every Redis command executes sequentially in a single-threaded event loop. An atomic command like `INCR`, `HSET`, or `SREM` cannot be interrupted by another command.
- Transactions via `MULTI` / `EXEC` provide sequential block execution, though Redis does not support rollback on syntax or runtime data errors.

---

## 5. Workload Suitability Matrix for Savannah Crest Hotels

| Hotel System Capability | Optimal Engine | Primary Architectural Rationale |
| :--- | :---: | :--- |
| **Room Reservation Engine** | **PostgreSQL** | Requires mathematical interval exclusion constraints (`stay && daterange`) and multi-row serializability to eliminate double bookings. |
| **Financial Ledger & Billing** | **PostgreSQL** | Strict ACID durability, immutable audit triggers, and referential integrity preventing orphan payment records. |
| **Live Room Availability Search** | **Redis (Cache-Aside)** | Offloads intensive date-range queries from PostgreSQL; provides $\approx 1.5\text{ ms}$ response times for web traffic. |
| **Staff & Guest Active Sessions** | **Redis (Hashes)** | Ephemeral session data with automated sliding TTL expiration and sub-millisecond attribute reads. |
| **Live Property Booking Feed** | **Redis (Lists)** | Capped in-memory event queues (`LPUSH` + `LTRIM`) providing instant push notifications for front-desk staff. |
| **Chain-Wide VIP Leaderboard** | **Redis (Sorted Sets)** | Dynamic $\mathcal{O}(\log N)$ ranking across 50,000 guests by lifetime expenditure without expensive database sorting. |
| **Guest 360 Dossier / CRM** | **MongoDB** | Rich denormalised profiles with nested booking history; single-query retrieval without expensive multi-table SQL joins. |
| **Marketing Segmentation & LTV** | **MongoDB** | High-throughput aggregation pipelines (`$unwind`, `$group`) across unstructured and polymorphic demographic data. |

---

## 6. Synthesis: The Polyglot Enterprise Architecture

Neither relational nor NoSQL technologies are mutually exclusive; rather, they form a symbiotic data ecosystem:

```
                            ┌────────────────────────┐
                            │  Web / Mobile Clients  │
                            └───────────┬────────────┘
                                        │
                                        ▼
                            ┌────────────────────────┐
                            │    API Gateway / App   │
                            └────┬──────────┬───────┬┘
             Read / Cache        │          │       │  Profile Dossier
             Lookups             │          │       │  & CRM Analytics
       ┌─────────────────────────┘          │       └─────────────────────────┐
       ▼                                    ▼                                 ▼
┌──────────────┐                   ┌────────────────┐                  ┌──────────────┐
│  REDIS 7.4   │                   │ POSTGRESQL 16  │                  │ MONGODB 7.0  │
│ (In-Memory)  │◄── Cache Sync ────┤ (Relational)   ├── Change Data ──►│  (Document)  │
│              │                   │ Master Record  │   Capture (CDC)  │              │
└──────────────┘                   └────────────────┘                  └──────────────┘
```

1. **Transactional Ingestion:** All booking commitments, room assignments, and payments land first in **PostgreSQL**, where relational constraints guarantee zero double bookings and audit logs record every state transition.
2. **Cache Synchronization:** On write events, the application invalidates or updates **Redis** keys, ensuring subsequent availability searches hit warm RAM.
3. **Read-Model Projection:** A Change Data Capture (CDC) or asynchronous worker projects committed PostgreSQL transactions into **MongoDB** `guest_profiles`, maintaining an up-to-date document read model for high-traffic mobile applications and analytical reporting.

