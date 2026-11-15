# Portfolio 4 Screenshots Catalog

This directory contains visual artifacts and screenshots demonstrating the operational execution of NoSQL data models in MongoDB 7.0 and Redis 7.4.

> [!NOTE]
> Per project configuration, live interactive screenshots are deferred/stashed for final post-project capture after all coursework code implementation is verified. All underlying empirical evidence is captured directly from live database runs in `portfolio-4-nosql/evidence/`.

---

## Screenshot Inventory & Pending Captures

| Screenshot ID | Filename | Description / Target Screen | Source Command / Tool | Status |
| :--- | :--- | :--- | :--- | :---: |
| **SS-4.1** | `01_mongodb_guest_profiles_document.png` | MongoDB Compass / `mongosh` displaying an expanded `guest_profiles` BSON document with nested `bookings` and `payments` arrays | `mongosh localhost:27017/savannah_crest_nosql` | *Pending post-project* |
| **SS-4.2** | `02_mongodb_aggregation_pipeline.png` | Execution of Aggregation Pipeline 1 (Revenue by Hotel City) showing unwound grouping and sorted results | `portfolio-4-nosql/queries/mongo_queries.js` | *Pending post-project* |
| **SS-4.3** | `03_mongodb_index_explain_comparison.png` | Terminal output showing `explain("executionStats")` comparing `COLLSCAN` (200 docs examined) vs `IXSCAN` (1 key examined) | `portfolio-4-nosql/scripts/mongo_operations.py` | *Pending post-project* |
| **SS-4.4** | `04_redis_five_data_structures.png` | Redis Insight / `redis-cli` keyspace showing active String, Hash, List, Set, and Sorted Set structures | `redis-cli KEYS "*"` | *Pending post-project* |
| **SS-4.5** | `05_redis_cache_aside_benchmark.png` | Terminal benchmark output showing Cache-Aside cold start ($92.9\text{ ms}$) vs warm cache hit ($1.3\text{ ms}$) | `portfolio-4-nosql/scripts/redis_operations.py` | *Pending post-project* |

---

## Instructions for Capturing Screenshots (Post-Project)

1. **MongoDB GUI / mongosh:**
   ```bash
   docker compose exec -it mongo mongosh -u mongo_admin -p changeme_mongo_2024 --authenticationDatabase admin savannah_crest_nosql
   db.guest_profiles.findOne({ loyalty_tier: "Platinum" })
   ```
2. **Redis CLI / Redis Insight:**
   ```bash
   docker compose exec -it redis redis-cli
   KEYS *
   ZREVRANGE leaderboard:guest_spend 0 4 WITHSCORES
   HGETALL session:guest:usr_98234a
   ```
3. **Execution Scripts:**
   ```bash
   make p4
   ```

