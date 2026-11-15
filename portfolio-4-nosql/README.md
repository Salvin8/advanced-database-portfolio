# Portfolio 4: NoSQL and Advanced Data Models

**Coursework:** Advanced Database Systems (MIT 8103)  
**System:** Savannah Crest Hotels Management System  
**Author:** Mubarak  
**Technologies:** MongoDB 7.0, Redis 7.4, PostgreSQL 16, Python 3.12 (psycopg, pymongo, redis)

---

## 1. Executive Summary

Portfolio 4 extends the Savannah Crest Hotels database architecture beyond pure relational storage into a **Polyglot Persistence** ecosystem. By combining **PostgreSQL 16** (relational system of record), **MongoDB 7.0** (document-oriented customer read model), and **Redis 7.4** (in-memory acceleration and data structures), the system addresses distinct operational profiles:

1. **Transactional Integrity (PostgreSQL):** Preserves strict ACID guarantees, GiST interval exclusion constraints, and relational audit logging for reservations and financial transactions.
2. **Customer 360 & Analytics (MongoDB):** Consolidates five normalised relational tables into a hierarchical BSON document store (`guest_profiles`), enabling single-lookup guest dossiers, atomic sub-document mutations (`$push`, `$set`), and multi-stage analytical aggregation pipelines.
3. **Low-Latency Acceleration (Redis):** Implements in-memory data structures (Strings, Hashes, Lists, Sets, Sorted Sets) and a Cache-Aside pattern, reducing room availability lookup latency from $92.9\text{ ms}$ to $1.3\text{ ms}$ ($70.8\times$ speedup).

---

## 2. Repository Structure

```
portfolio-4-nosql/
├── README.md                      # Comprehensive Portfolio 4 documentation & viva guide
├── docs/
│   ├── document-model.md          # Detailed MongoDB schema design, embedding rationale, & ACID
│   ├── redis-caching.md           # Redis data structures, Cache-Aside pattern, & invalidation
│   └── nosql-comparison.md        # Comparative evaluation (CAP, ACID vs BASE, Polyglot matrix)
├── schemas/
│   └── mongo_schema.js            # MongoDB JSON Schema ($jsonSchema) validation & index creation
├── queries/
│   └── mongo_queries.js           # Standalone MongoDB find queries and aggregation pipelines
├── scripts/
│   ├── mongo_operations.py        # Python ETL, CRUD, aggregations, & explain() benchmarks
│   └── redis_operations.py        # Python Redis data structures, Cache-Aside, & latency tests
├── evidence/
│   ├── mongo-operations-output.txt# Live execution output of MongoDB ETL, CRUD, & explain plans
│   └── redis-operations-output.txt# Live execution output of Redis data structures & latency tests
└── screenshots/
    └── README.md                  # Catalog of visual artifacts (stashed pending post-project)
```

---

## 3. MongoDB 7.0 Document Model

### 3.1 Document Architecture
The `guest_profiles` collection collapses the normalised PostgreSQL tables (`guest`, `booking`, `booking_room`, `payment`, `room`, `room_type`) into a single denormalised document:

```json
{
  "_id": ObjectId("6af97e38313c946e91ee3fdd"),
  "guest_id": 4520,
  "first_name": "Tunde",
  "last_name": "Igwe",
  "email": "tunde.igwe4520@mail.ng",
  "phone": "+2348031234567",
  "nationality": "Nigerian",
  "loyalty_tier": "Platinum",
  "bookings": [
    {
      "booking_ref": "SC-2024-0012903",
      "hotel_name": "Savannah Crest Independence Layout",
      "city": "Enugu",
      "check_in": "2024-05-10",
      "check_out": "2024-05-14",
      "room_type": "Executive Suite",
      "room_number": "402",
      "total_amount": 340000.0,
      "status": "checked_out",
      "payments": [
        {
          "amount": 340000.0,
          "method": "card",
          "status": "completed",
          "transaction_ref": "TXN-SC-2024-0012903-1",
          "date": "2024-05-02T00:00:00"
        }
      ]
    }
  ],
  "stats": {
    "total_bookings": 54,
    "total_spent": 7675250.0,
    "avg_stay_nights": 2.9,
    "preferred_hotel": "Savannah Crest Independence Layout",
    "preferred_room_type": "Executive Suite",
    "first_visit": "2020-02-14",
    "last_visit": "2026-09-18"
  },
  "created_at": "2020-01-15T00:00:00",
  "updated_at": "2026-11-15T09:41:08"
}
```

### 3.2 Schema Validation & Indexing
- Enforced via **MongoDB JSON Schema Validation** (`$jsonSchema`) with strict typing, enum validation (`loyalty_tier` $\in$ {Bronze, Silver, Gold, Platinum}), and email regex checking.
- Indexed with five strategic indexes:
  - `idx_guest_id`: Unique B-tree index on `guest_id`.
  - `idx_email`: Unique index on `email`.
  - `idx_bookings_hotel_name`: **Multikey Index** indexing every element in the nested `bookings` array.
  - `idx_stats_total_spent`: Descending index for rapid VIP spend lookups.
  - `idx_nat_tier`: Compound index on `{ nationality: 1, loyalty_tier: 1 }`.

### 3.3 Empirical Index Performance
Comparing query execution plans via `.explain("executionStats")` for `find({ email: 'fatima.eze6331@mail.ng' })`:

| Metric | Without Index (`COLLSCAN`) | With Index (`IXSCAN` + `FETCH`) | Impact |
| :--- | :---: | :---: | :--- |
| **Stage** | `COLLSCAN` | `FETCH` $\leftarrow$ `IXSCAN` | Direct B-tree key traversal |
| **Documents Examined** | **200** | **1** | **99.5% reduction** |
| **Keys Examined** | 0 | 1 | Exact match |
| **Execution Time** | $2\text{ ms}$ | $0\text{ ms}$ | Immediate in-memory resolution |

---

## 4. Redis 7.4 In-Memory Caching & Data Structures

### 4.1 Five Core Data Structures
1. **Strings (`room:101:available`, `hotel:1:available_rooms`):** Transient flags with 300s TTL and atomic integer counters (`INCR`/`DECR`) for race-free inventory updates.
2. **Hashes (`session:guest:usr_98234a`):** Field-level session storage with 24-hour expiration (`EXPIRE 86400`).
3. **Lists (`hotel:1:recent_bookings`):** Real-time booking audit log capped at 50 events using `LPUSH` and `LTRIM`.
4. **Sets (`pool:available_rooms:hotel:1`):** Unordered pool of active rooms supporting `SADD`, `SREM`, `SISMEMBER`, and property-wide intersection (`SINTER`).
5. **Sorted Sets (`leaderboard:guest_spend`):** Skip-list-backed $\mathcal{O}(\log N)$ guest ranking based on lifetime expenditure.

### 4.2 Cache-Aside Pattern Benchmark
Implemented for room availability search across dates (`2026-12-01` to `2026-12-05`):

```
Call 1 (Cold Start): [MISS] -> 20 rooms returned | Latency: 29.664 ms (PostgreSQL)
Call 2 (Cached Hit): [HIT]  -> 20 rooms returned | Latency: 1.550 ms (Redis)
⚡ Performance Differential: 19.1x Speedup via Redis in-memory lookup
```

---

## 5. Execution & Verification Guide

All targets are fully automated within the root `Makefile`:

```bash
# Ensure Docker services (postgres, mongo, redis) are running
make up-all

# Execute full Portfolio 4 workflow (MongoDB + Redis)
make p4

# Execute individual components
make p4-mongo   # Runs ETL, CRUD, aggregations, and explain() benchmarks
make p4-redis   # Runs 5 data structures, Cache-Aside, invalidation, & benchmarks
```

---

## 6. Viva Voce Defense Preparation: Questions & Detailed Answers

### Q1: Why did you choose an embedded document model for guest bookings rather than referencing? Under what conditions would this decision break down?
> **Answer:**  
> In Savannah Crest Hotels, bookings and payments have a **contained, bounded 1:N relationship** with the guest. Guests accumulate between 1 and 70 bookings over several years. Embedding bookings directly within `guest_profiles` provides **data co-locality**: a single query fetches the guest's profile, full stay history, and lifetime statistics in $\mathcal{O}(1)$ time without expensive multi-table joins.  
> 
> **Breakdown Conditions:** This design would break down if:
> 1. The relationship were **unbounded** (e.g., IoT sensor telemetry or clickstream tracking), where documents would rapidly approach MongoDB's hard **16 MB BSON document size ceiling**.
> 2. Bookings were frequently updated by concurrent external processes, causing **write amplification** and document relocation in WiredTiger. In our architecture, high-frequency updates land in PostgreSQL first, and only stable/committed records project into MongoDB.

---

### Q2: How does MongoDB ensure atomicity during updates, and what happens when an embedded array modification exceeds the allocated document space?
> **Answer:**  
> MongoDB guarantees **strict ACID atomicity at the single-document level**. When modifying a document using operators such as `$push` (to append a booking), `$inc` (to increment spend counters), and `$set` (to update loyalty tier), all operations execute atomically within WiredTiger. Other readers never observe an inconsistent partial state where the booking was appended but the spend was not updated.  
> 
> Under the WiredTiger storage engine, documents do not use static padding factors. Instead, when an in-place update exceeds available space, WiredTiger allocates a new unfragmented memory buffer, writes the enlarged BSON document, updates the internal B-tree leaf pointer, and marks the old disk space for reclamation during checkpointing. If the document exceeds the hard **16 MB limit**, MongoDB raises `BSONObjectTooLarge` (`code 10334`) and rejects the write.

---

### Q3: Why can't MongoDB replace PostgreSQL as the primary reservation database in your system?
> **Answer:**  
> MongoDB cannot replace PostgreSQL for our core reservation engine due to **cross-document constraint limitations**:
> 1. **Interval Exclusion Constraints:** Savannah Crest Hotels enforces room availability using PostgreSQL's `EXCLUDE USING gist (room_id WITH =, stay WITH &&)`. This mathematical exclusion guarantees that no two concurrent transactions can reserve the same room for overlapping dates at the storage engine level. MongoDB lacks declarative interval exclusion constraints.
> 2. **Multi-Document ACID Across Global State:** While MongoDB supports multi-document transactions (introduced in 4.0), they incur significant distributed lock overhead and snapshot synchronization costs compared to PostgreSQL's native MVCC and row-level locks (`SELECT ... FOR UPDATE`).
> 3. **Financial Audit Trail:** The relational schema maintains strict foreign key referential integrity (`ON DELETE RESTRICT`) preventing orphan financial ledgers, ensuring strict accounting compliance.

---

### Q4: Explain the Cache-Aside pattern implemented in Redis. What is the "Thundering Herd" problem, and how is it mitigated?
> **Answer:**  
> Under **Cache-Aside (Lazy Loading)**, the application coordinates between Redis and PostgreSQL:
> 1. The application checks Redis for key `cache:avail:h1:2026-12-01:2026-12-05`.
> 2. On a **Cache Hit**, Redis immediately returns the cached JSON string ($1.5\text{ ms}$).
> 3. On a **Cache Miss**, the application queries PostgreSQL ($30\text{--}90\text{ ms}$), populates Redis with an explicit Time-To-Live (`EX 300`), and returns the data.  
> 
> **The Thundering Herd (Cache Stampede):** When a highly requested key (e.g., peak Christmas dates) expires under heavy traffic, hundreds of concurrent requests experience a cache miss simultaneously and hammer PostgreSQL with identical expensive queries, causing CPU spikes or connection pool exhaustion.  
> **Mitigation:**
> - **Distributed Mutex (`SET lock:key token NX EX 10`):** Only the first worker acquires the lock to query PostgreSQL and refresh Redis; other requests wait or return slightly stale cache.
> - **Probabilistic Early Expiration (XFetch algorithm):** Requests probabilistically recompute and refresh the cache *before* it formally expires based on read frequency and remaining TTL.

---

### Q5: How does Redis achieve high throughput without multithreading, and what are the trade-offs of its memory eviction policies?
> **Answer:**  
> Redis achieves upwards of 100,000+ operations per second primarily because:
> 1. **In-Memory Storage:** All data structures reside entirely in physical RAM, avoiding disk I/O, page faults, and buffer cache synchronisation.
> 2. **Single-Threaded Event Multiplexing:** Redis uses an event loop built on OS I/O multiplexers (`epoll` on Linux, `kqueue` on macOS). By processing commands sequentially in a single thread, Redis completely eliminates the overhead of thread context switching, thread synchronization locks, and race conditions.  
> 
> **Memory Eviction Trade-offs:**  
> When RAM reaches `maxmemory`:
> - `volatile-lru`: Evicts least-recently used keys that have an explicit TTL set. Ideal when volatile caches coexist with persistent lookup tables.
> - `allkeys-lru`: Evicts LRU keys across the entire keyspace. Best when Redis is purely a disposable cache, but risks dropping important session tokens.
> - `noeviction`: Returns errors on write operations. Guarantees zero data loss, but causes application write failures if memory is exhausted.

---

### Q6: In a Polyglot architecture, how do you handle data consistency discrepancies across PostgreSQL, MongoDB, and Redis?
> **Answer:**  
> In Savannah Crest Hotels, we establish a strict **Hierarchy of Authority**:
> 1. **Single Source of Truth:** PostgreSQL is the sole authoritative system of record. Writes *never* originate in MongoDB or Redis independently.
> 2. **Cache Invalidation over Mutation:** For Redis, we favour **explicit cache eviction** (`DEL key`) on booking state mutations rather than complex in-memory updates. Deleting the cache forces the next read to fetch authoritative state from PostgreSQL, preventing stale availability windows.
> 3. **Asynchronous Read Model Projection:** For MongoDB `guest_profiles`, committed transactions in PostgreSQL are propagated via **Change Data Capture (CDC)** (such as Debezium reading PostgreSQL WAL or database event triggers). Even if MongoDB is momentarily a few milliseconds behind PostgreSQL (eventual consistency), the guest dossier remains functionally correct for mobile browsing, while all reservations are strictly validated against PostgreSQL before confirmation.
