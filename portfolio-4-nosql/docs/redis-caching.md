# Redis In-Memory Caching Architecture & Data Structures

**Portfolio 4: NoSQL and Advanced Data Models**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Summary & Caching Philosophy

In high-concurrency hospitality systems, relational databases face severe I/O bottlenecks when handling repetitive read queries. At Savannah Crest Hotels, two query workloads create substantial database load:
1. **Room Availability Searches:** Prospective guests searching for available rooms across date ranges (`stay && daterange(...)`) require evaluation of GiST exclusion predicates and table scans across 500,000+ booking records.
2. **Session & Guest Lookups:** Active front-desk staff and authenticated mobile users frequently query guest dossiers, loyalty statuses, and current room assignments.

To decouple high-frequency read traffic from the persistent storage engine, we integrate **Redis 7.4** as an in-memory caching and data-structure tier. Operating entirely in RAM with single-threaded asynchronous event looping (`epoll`), Redis provides predictable sub-millisecond latencies ($\mathcal{O}(1)$ or $\mathcal{O}(\log N)$), offloading up to 95% of read volume from PostgreSQL.

---

## 2. Five Core Redis Data Structures in Hotel Operations

Redis is not merely a key-value cache; it is a versatile data-structure server. We leveraged five core structures for distinct operational needs:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          REDIS 7.4 DATA STRUCTURES                          │
├─────────────────┬─────────────────┬─────────────────┬───────────────────────┤
│  Data Structure │ Key Pattern     │ Time Complexity │ Hotel Business Case   │
├─────────────────┼─────────────────┼─────────────────┼───────────────────────┤
│ 1. Strings      │ room:{id}:avail │ O(1)            │ Availability flags &  │
│                 │ hotel:{id}:cnt  │                 │ atomic counters (INCR)│
├─────────────────┼─────────────────┼─────────────────┼───────────────────────┤
│ 2. Hashes       │ session:guest:* │ O(1) field ops  │ Staff / guest active  │
│                 │                 │                 │ session store         │
├─────────────────┼─────────────────┼─────────────────┼───────────────────────┤
│ 3. Lists        │ hotel:{id}:feed │ O(1) push/pop   │ Capped live booking   │
│                 │                 │                 │ event queue (LTRIM)   │
├─────────────────┼─────────────────┼─────────────────┼───────────────────────┤
│ 4. Sets         │ pool:avail:h{id}│ O(1) add/rem    │ Active room inventory │
│                 │                 │ O(N) intersect  │ & property SINTER     │
├─────────────────┼─────────────────┼─────────────────┼───────────────────────┤
│ 5. Sorted Sets  │ leaderboard:*   │ O(log N)        │ Chain-wide VIP spend  │
│    (ZSET)       │                 │                 │ rank & percentile     │
└─────────────────┴─────────────────┴─────────────────┴───────────────────────┘
```

### 2.1 Strings: Availability Flags & Atomic Inventory Counters
- **Key Pattern:** `room:101:available`, `hotel:1:available_rooms`
- **Semantics:** Strings store raw text, binary payloads, or 64-bit integers.
- **Operations:**
  - `SET room:101:available "true" EX 300`: Sets a transient availability flag with a 5-minute Time-To-Live (TTL).
  - `DECR hotel:1:available_rooms` and `INCR hotel:1:available_rooms`: Atomic integer operations executing inside Redis's single-threaded event loop. They provide race-condition-free inventory tracking without relational row-level locking.

### 2.2 Hashes: Front-Desk Active Guest Sessions
- **Key Pattern:** `session:guest:usr_98234a`
- **Semantics:** Hashes represent objects with string field-value pairs, perfectly matching relational rows without serialization overhead.
- **Operations:**
  - `HSET session:guest:... guest_id 4520 role VIP_Gold hotel_id 1`: Stores session state.
  - `HGET session:guest:... active_room_assigned`: Reads a specific attribute in $\mathcal{O}(1)$ time without deserializing the entire session payload.
  - `EXPIRE session:guest:... 86400`: Enforces a sliding 24-hour expiration window.

### 2.3 Lists: Live Reservation Event Stream
- **Key Pattern:** `hotel:1:recent_bookings`
- **Semantics:** Linked lists supporting head/tail pushes and range slicing.
- **Operations:**
  - `LPUSH hotel:1:recent_bookings <json_payload>`: Prepends new booking events as they occur.
  - `LTRIM hotel:1:recent_bookings 0 49`: Automatically truncates the list, retaining strictly the 50 most recent events. This provides a lightweight in-memory audit log for front-desk monitoring dashboards without database writes.

### 2.4 Sets: Available Room Pools & Multi-Property Set Algebra
- **Key Pattern:** `pool:available_rooms:hotel:1`
- **Semantics:** Unordered collections of unique strings supporting mathematical set operations.
- **Operations:**
  - `SADD pool:available_rooms:hotel:1 101 102 103 104`: Adds clean, unreserved room numbers.
  - `SREM pool:available_rooms:hotel:1 103`: Atomically checks out or assigns room 103.
  - `SINTER pool:available_rooms:hotel:1 pool:available_rooms:hotel:2`: Computes set intersection across luxury suite room configurations, identifying standard room identifiers shared across properties.

### 2.5 Sorted Sets (ZSET): Chain-Wide Guest Loyalty Leaderboard
- **Key Pattern:** `leaderboard:guest_spend`
- **Semantics:** Every element is mapped to a floating-point score and ordered via a skip list and hash table ($\mathcal{O}(\log N)$ insertion and lookup).
- **Operations:**
  - `ZADD leaderboard:guest_spend 7934250.0 "guest:1235"`: Records lifetime guest expenditure.
  - `ZREVRANGE leaderboard:guest_spend 0 4 WITHSCORES`: Retrieves the top 5 spenders chain-wide in descending order.
  - `ZREVRANK leaderboard:guest_spend "guest:4520"`: Instantly discovers any guest's exact chain-wide ranking (e.g., Rank #3) in $\mathcal{O}(\log N)$ time, avoiding costly SQL `RANK() OVER (ORDER BY SUM(amount) DESC)` table scans.

---

## 3. The Cache-Aside (Lazy Loading) Pattern

In our implementation (`scripts/redis_operations.py`), the primary caching pattern deployed is **Cache-Aside** (Lazy Loading). The application directly coordinates between Redis and PostgreSQL:

```
                  ┌────────────────────────┐
                  │   Application Worker   │
                  └─────┬────────────▲─────┘
                        │            │
       1. Check Cache   │            │  4. Return Payload
     ┌──────────────────┘            └─────────────────┐
     │                                                 │
┌────▼──────────────┐                         ┌────────┴────────┐
│     REDIS 7.4     │                         │  POSTGRESQL 16  │
│  (In-Memory L1)   │                         │  (Relational L2)│
└────┬──────────────┘                         └────────▲────────┘
     │                                                 │
     │ 2. Cache MISS                                   │ 3. Execute SQL Query
     └─────────────────────────────────────────────────┘    (Range overlap check)
```

### Execution Flow:
1. **Query Dispatch:** The application requests room availability for a hotel and date range (`cache:avail:h1:2026-12-01:2026-12-05`).
2. **Cache Hit:** If the key exists in Redis, it is deserialized and returned immediately ($\approx 1.3\text{ ms}$). PostgreSQL is never contacted.
3. **Cache Miss:** If the key does not exist (`None`):
   - The application falls back to PostgreSQL.
   - It executes the complex `NOT EXISTS` query checking the GiST index and active reservations ($\approx 92.9\text{ ms}$).
   - The query result is serialized to JSON and stored in Redis with an explicit TTL (`EX 300`, 5 minutes).
   - The result is returned to the client.

### Empirical Latency Differential
Captured from live execution in `evidence/redis-operations-output.txt`:
- **Cold Start (PostgreSQL Query):** `92.920 ms`
- **Cached Hit (Redis Memory Lookup):** `1.312 ms`
- **Empirical Speedup:** **$70.8\times$ faster** via Redis in-memory resolution.

---

## 4. Cache Invalidation Strategies

Maintaining cache consistency with the underlying database is a critical distributed systems challenge. We demonstrated three invalidation strategies:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       CACHE INVALIDATION STRATEGIES                         │
├─────────────────────┬───────────────────┬───────────────────────────────────┤
│ Strategy            │ Mechanism         │ Operational Trade-off             │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ 1. TTL Expiration   │ Passive / Time    │ Simple, bounded staleness, zero   │
│                     │ (e.g., EX 300)    │ application coordination overhead │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ 2. Explicit Eviction│ Active Purge      │ Guarantees immediate consistency, │
│                     │ (DEL key)         │ requires hook on write endpoints  │
├─────────────────────┼───────────────────┼───────────────────────────────────┤
│ 3. Write-Through    │ Synchronous Write │ Strongest consistency, incurs dual│
│                     │ (DB write + SET)  │ write latency on update path      │
└─────────────────────┴───────────────────┴───────────────────────────────────┘
```

### 4.1 TTL-Based Passive Expiration
- Keys are assigned an expiration timestamp (e.g., promotional flash sales set to 2 seconds).
- Once the TTL reaches zero, Redis passively expires the key upon next access or actively purges it via background sampling.
- **Advantage:** Self-healing. Even if invalidation signals are lost, stale data naturally purges.

### 4.2 Explicit Eviction on State Mutation
- When a guest confirms a new reservation in PostgreSQL, the application explicitly issues `DEL cache:avail:h1:2026-12-01:2026-12-05`.
- **Advantage:** Eliminates stale availability windows immediately, preventing other users from attempting to book rooms that were just reserved.

### 4.3 Write-Through Synchronization
- On critical guest profile updates (e.g., phone number or VIP tier changes), the application writes to PostgreSQL and immediately updates the Redis key (`cache:guest:profile:501`) within the same request lifecycle.
- Subsequent reads immediately encounter warm, updated data with zero cold-start penalty.

---

## 5. Failure Modes & Mitigations

When deploying Redis at scale, three classic caching anomalies must be addressed:

### 5.1 Cache Stampede (Thundering Herd)
- **Problem:** When a popular key (e.g., Christmas holiday availability at Savannah Crest Victoria Island) expires under heavy traffic, thousands of concurrent requests miss simultaneously, overwhelming PostgreSQL.
- **Mitigation:** **Probabilistic Early Expiration (XFetch algorithm)** or **Distributed Mutex Locking (`SET key lock NX EX 10`)**. Only one worker acquires the right to recompute the PostgreSQL query; remaining requests wait or serve mildly stale cache.

### 5.2 Cache Penetration
- **Problem:** Malicious or erroneous queries for non-existent room numbers or invalid guest IDs consistently bypass Redis and hit PostgreSQL.
- **Mitigation:** **Negative Caching** (storing `"null"` with a short 30-second TTL) or a **Bloom Filter** fronting the cache.

### 5.3 Cache Avalanche
- **Problem:** Many keys initialized at system startup share the exact same TTL (e.g., 3600s) and expire at the exact same second, causing a sudden spike in database load.
- **Mitigation:** **TTL Jitter** — adding a random delta to the base TTL ($\text{TTL} = 300 + \text{random}(0, 60)$ seconds).

---

## 6. Memory Eviction Policies

Redis stores all data in physical RAM. When memory reaches the configured threshold (`maxmemory`), Redis enforces an eviction policy:

| Policy | Eviction Mechanism | Best Fit Workload |
| :--- | :--- | :--- |
| `volatile-lru` | Evicts least-recently used keys with an explicit TTL set | Recommended for mixed workloads (sessions + permanent lookup tables) |
| `allkeys-lru` | Evicts least-recently used keys across the entire keyspace | Ideal when Redis is strictly used as a pure disposable cache |
| `volatile-ttl` | Evicts keys with the shortest remaining time-to-live | Best for time-sensitive pricing and promo caches |
| `noeviction` | Returns out-of-memory errors on write commands | Mandatory when Redis holds critical queues or persistent state |

---

## 7. Polyglot Multi-Tier Architecture

Savannah Crest Hotels unifies three complementary database technologies:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                  SAVANNAH CREST THREE-TIER DATA ARCHITECTURE                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [ Tier 1: In-Memory Acceleration ]                                         │
│  REDIS 7.4                                                                  │
│  - Sub-millisecond availability caching (Cache-Aside)                       │
│  - Active user sessions & token authentication (Hashes)                     │
│  - Real-time guest loyalty leaderboards (Sorted Sets)                       │
│                                                                             │
│                           ▲                       ▲                         │
│                  Cache    │                       │ Read Sync               │
│                  Miss     │                       │                         │
│                           ▼                       ▼                         │
│  [ Tier 2: Relational System of Record ]    [ Tier 3: Document Read Model ] │
│  POSTGRESQL 16                              MONGODB 7.0                     │
│  - Normalized BCNF/3NF schema               - Denormalized Guest Profiles   │
│  - GiST exclusion constraints (No Overlap)  - Historical bookings & payments│
│  - ACID transaction isolation & WAL         - Analytics & Aggregations      │
│  - Master financial & housekeeping ledger   - Mobile app guest dossier      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
This multi-tier approach ensures that:
- **Consistency** is enforced where it matters most (PostgreSQL for room double-booking prevention and audit logs).
- **Latency** is minimized for user-facing interactive paths (Redis for availability and sessions).
- **Flexibility & Read Scalability** are optimized for customer experience and CRM intelligence (MongoDB for guest 360 profiles).

