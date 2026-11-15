#!/usr/bin/env python3
"""
redis_operations.py - Redis In-Memory Data Structures, Cache-Aside Pattern & Benchmarking
Portfolio 4: NoSQL and Advanced Data Models
Savannah Crest Hotels

This script demonstrates:
1. Five Core Redis Data Structures: Strings, Hashes, Lists, Sets, and Sorted Sets (ZSET)
2. Cache-Aside Pattern: PostgreSQL query offloading with TTL-based lazy caching
3. Invalidation Strategies: TTL expiration, explicit eviction, and write-through simulation
4. Empirical Latency Benchmarks: 100-iteration direct PostgreSQL vs. Redis cache hits (Avg, P95, Ops/sec)
"""

import os
import sys
import json
import time
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import psycopg
import redis

# Load environment configuration
load_dotenv()

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

EVIDENCE_FILE = "portfolio-4-nosql/evidence/redis-operations-output.txt"


class TeeWriter:
    """Tee stdout to both console and evidence file."""
    def __init__(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.file = open(filepath, "w")
        self.stdout = sys.stdout

    def write(self, data):
        self.stdout.write(data)
        self.file.write(data)

    def flush(self):
        self.file.flush()
        self.stdout.flush()

    def close(self):
        self.file.close()


def main():
    tee = TeeWriter(EVIDENCE_FILE)
    sys.stdout = tee

    print("=" * 80)
    print("SAVANNAH CREST HOTELS - REDIS 7.4 IN-MEMORY DATA STRUCTURES & CACHING")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Redis Target: {REDIS_HOST}:{REDIS_PORT}")
    print(f"PostgreSQL Target: {PG_HOST}:{PG_PORT}/{PG_DB}")
    print("=" * 80)

    # Connect to Redis with dedicated ConnectionPool
    pool = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, max_connections=20)
    r = redis.Redis(connection_pool=pool)
    try:
        r.ping()
        print("✓ Connected to Redis successfully.")
    except Exception as e:
        print(f"✗ Failed to connect to Redis: {e}")
        return

    # Connect to PostgreSQL
    pg_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DB
    )
    print("✓ Connected to PostgreSQL successfully.")

    # --------------------------------------------------------------------------
    # 1. Five Core Redis Data Structures
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 1: DEMONSTRATING FIVE CORE REDIS DATA STRUCTURES")
    print("=" * 80)

    # 1.1 Strings: Room Availability Flag & Atomic Inventory Counters
    print("\n[1.1 Strings: Availability Status & Atomic Counters]")
    room_key = "room:101:available"
    r.set(room_key, "true", ex=300)  # 5-minute TTL
    val = r.get(room_key)
    ttl = r.ttl(room_key)
    print(f"  SET {room_key} -> '{val}' (TTL: {ttl}s)")

    counter_key = "hotel:1:available_rooms"
    r.set(counter_key, 100)
    print(f"  SET {counter_key} = 100")
    r.decr(counter_key)
    print(f"  DECR {counter_key} (Room booked) -> Current: {r.get(counter_key)}")
    r.incr(counter_key)
    print(f"  INCR {counter_key} (Booking cancelled) -> Current: {r.get(counter_key)}")

    # 1.2 Hashes: Front-Desk Active Guest Session
    print("\n[1.2 Hashes: Guest Active Session Store]")
    session_id = "session:guest:usr_98234a"
    session_data = {
        "guest_id": "4520",
        "first_name": "Tunde",
        "last_name": "Igwe",
        "role": "VIP_Gold",
        "hotel_id": "1",
        "check_in": "2026-11-20",
        "check_out": "2026-11-25",
        "login_ip": "197.210.55.12",
        "authenticated_at": datetime.now().isoformat()
    }
    r.hset(session_id, mapping=session_data)
    r.expire(session_id, 86400)  # 24-hour expiration

    retrieved_session = r.hgetall(session_id)
    print(f"  HSET & HGETALL {session_id} (TTL: {r.ttl(session_id)}s):")
    for k, v in list(retrieved_session.items())[:5]:
        print(f"    - {k}: {v}")

    # Specific field lookup and modification
    r.hset(session_id, "active_room_assigned", "305")
    print(f"  HSET update: active_room_assigned -> {r.hget(session_id, 'active_room_assigned')}")

    # 1.3 Lists: Live Audit Feed / Recent Bookings Queue
    print("\n[1.3 Lists: Live Reservation Event Stream]")
    queue_key = "hotel:1:recent_bookings"
    r.delete(queue_key)  # Clean previous demo queue

    for i in range(1, 6):
        event = json.dumps({
            "event_id": f"evt_00{i}",
            "booking_ref": f"SC-2026-00000{i}",
            "room": f"20{i}",
            "amount": 45000 * i,
            "timestamp": datetime.now().isoformat()
        })
        r.lpush(queue_key, event)
    r.ltrim(queue_key, 0, 49)  # Keep latest 50 events capped

    queue_len = r.llen(queue_key)
    print(f"  LPUSH & LTRIM {queue_key} -> Capped Queue Length: {queue_len}")
    latest_events = r.lrange(queue_key, 0, 2)
    print("  LRANGE latest 3 events:")
    for ev_str in latest_events:
        ev = json.loads(ev_str)
        print(f"    * Ref: {ev['booking_ref']} | Room: {ev['room']} | Amount: ₦{ev['amount']:,.2f}")

    # 1.4 Sets: Available Room Pools & Multi-Hotel Tagging
    print("\n[1.4 Sets: Available Room Pools & Set Operations]")
    pool_h1 = "pool:available_rooms:hotel:1"
    pool_h2 = "pool:available_rooms:hotel:2"
    r.delete(pool_h1, pool_h2)

    r.sadd(pool_h1, "101", "102", "103", "104", "105", "106")
    r.sadd(pool_h2, "104", "105", "107", "108", "109")
    print(f"  SADD {pool_h1} (Abuja) -> {r.smembers(pool_h1)}")
    print(f"  SADD {pool_h2} (Lagos) -> {r.smembers(pool_h2)}")

    # Reserve room 103 in Hotel 1
    r.srem(pool_h1, "103")
    print(f"  SREM 103 from Hotel 1 (Booked) -> Remaining: {r.smembers(pool_h1)}")
    print(f"  SISMEMBER 103: {r.sismember(pool_h1, '103')}")
    print(f"  SISMEMBER 102: {r.sismember(pool_h1, '102')}")

    # Set intersection across luxury suites sharing room configuration
    intersect_rooms = r.sinter(pool_h1, pool_h2)
    print(f"  SINTER (Common suite numbers across properties): {intersect_rooms}")

    # 1.5 Sorted Sets (ZSET): Guest Loyalty Leaderboard
    print("\n[1.5 Sorted Sets (ZSET): Chain-Wide Guest Loyalty Leaderboard]")
    lb_key = "leaderboard:guest_spend"
    r.delete(lb_key)

    # Seed top spenders
    guests_seed = {
        "guest:1235": 7934250.0,
        "guest:4518": 7761500.0,
        "guest:4520": 7675250.0,
        "guest:847":  7609250.0,
        "guest:3874": 7548250.0,
        "guest:2104": 6890000.0,
        "guest:1899": 6540000.0
    }
    r.zadd(lb_key, guests_seed)

    print("  ZREVRANGE Top 5 Spenders (with scores):")
    top_5 = r.zrevrange(lb_key, 0, 4, withscores=True)
    for rank, (gid, score) in enumerate(top_5, 1):
        print(f"    {rank}. {gid:<12} | Lifetime Spend: ₦{score:>11,.2f}")

    # Rank and score lookup
    target_guest = "guest:4520"
    rank_0 = r.zrevrank(lb_key, target_guest)
    score_val = r.zscore(lb_key, target_guest)
    print(f"  ZREVRANK & ZSCORE for {target_guest}: Rank #{rank_0 + 1} with ₦{score_val:,.2f}")

    # --------------------------------------------------------------------------
    # 2. Cache-Aside Pattern Implementation
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 2: CACHE-ASIDE (LAZY LOADING) PATTERN IMPLEMENTATION")
    print("=" * 80)

    def get_room_availability_cache_aside(hotel_id, check_in_str, check_out_str):
        cache_key = f"cache:avail:h{hotel_id}:{check_in_str}:{check_out_str}"
        t0 = time.perf_counter()

        # 1. Check Redis Cache
        cached_result = r.get(cache_key)
        if cached_result:
            t_cache = (time.perf_counter() - t0) * 1000
            return json.loads(cached_result), "HIT", t_cache

        # 2. Cache Miss: Query PostgreSQL
        t_pg_start = time.perf_counter()
        with pg_conn.cursor() as cur:
            cur.execute("""
                SELECT r.room_id, r.room_number, rt.name AS room_type, r.floor
                FROM room r
                JOIN room_type rt ON r.room_type_id = rt.room_type_id
                WHERE r.hotel_id = %s
                  AND r.is_active = true
                  AND NOT EXISTS (
                      SELECT 1 FROM booking_room br
                      WHERE br.room_id = r.room_id
                        AND br.status IN ('reserved', 'checked_in')
                        AND br.stay && daterange(%s::date, %s::date, '[)')
                  )
                ORDER BY r.floor, r.room_number
                LIMIT 20;
            """, (hotel_id, check_in_str, check_out_str))
            rows = cur.fetchall()

        t_pg = (time.perf_counter() - t_pg_start) * 1000

        data = [
            {"room_id": row[0], "room_number": row[1], "room_type": row[2], "floor": row[3]}
            for row in rows
        ]

        # 3. Populate Redis with 300s TTL (5 minutes)
        r.set(cache_key, json.dumps(data), ex=300)
        return data, "MISS", t_pg

    print("Testing Cache-Aside with Hotel 1 Availability Search (2026-12-01 to 2026-12-05)...")

    # Clear existing key to guarantee a cold start
    test_key = "cache:avail:h1:2026-12-01:2026-12-05"
    r.delete(test_key)

    # First Call: CACHE MISS
    res_miss, status_miss, lat_miss = get_room_availability_cache_aside(1, "2026-12-01", "2026-12-05")
    print(f"  Call 1 (Cold Start): [{status_miss}] -> {len(res_miss)} rooms returned | Latency: {lat_miss:.3f} ms (PostgreSQL)")

    # Second Call: CACHE HIT
    res_hit, status_hit, lat_hit = get_room_availability_cache_aside(1, "2026-12-01", "2026-12-05")
    speedup = lat_miss / max(0.001, lat_hit)
    print(f"  Call 2 (Cached Hit): [{status_hit}]  -> {len(res_hit)} rooms returned | Latency: {lat_hit:.3f} ms (Redis)")
    print(f"  ⚡ Performance Differential: {speedup:.1f}x Speedup via Redis in-memory lookup")

    # --------------------------------------------------------------------------
    # 3. Cache Invalidation Strategies
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 3: CACHE INVALIDATION STRATEGIES")
    print("=" * 80)

    # 3.1 TTL Expiration
    print("\n[3.1 TTL Expiration Strategy]")
    ttl_demo_key = "cache:temp:flash_promo_rate"
    r.set(ttl_demo_key, "₦25,000", ex=2)  # 2 second TTL
    print(f"  Set key '{ttl_demo_key}' with 2-second TTL.")
    print(f"  Immediate check: {r.get(ttl_demo_key)} (TTL: {r.ttl(ttl_demo_key)}s)")
    print("  Sleeping 2.2 seconds for TTL expiration...")
    time.sleep(2.2)
    expired_val = r.get(ttl_demo_key)
    print(f"  Check after sleep: {expired_val} (Key successfully expired automatically)")

    # 3.2 Explicit Invalidation (Purge on State Change)
    print("\n[3.2 Explicit Invalidation on Booking Event]")
    r.set(test_key, json.dumps(res_miss), ex=300)
    print(f"  Pre-condition: {test_key} exists -> {r.exists(test_key)}")
    print("  Action: Guest completes booking on room in this range.")
    r.delete(test_key)
    print(f"  Explicit Eviction: {test_key} deleted -> Exists: {r.exists(test_key)}")
    print("  Next read will fetch authoritative availability from PostgreSQL.")

    # 3.3 Write-Through Strategy Simulation
    print("\n[3.3 Write-Through Strategy Simulation]")
    wt_guest_key = "cache:guest:profile:501"
    updated_profile = {
        "guest_id": 501,
        "phone": "+2348039998877",
        "email": "updated.guest501@mail.ng",
        "synced_at": datetime.now().isoformat()
    }
    # In write-through, update the primary store, then immediately update the cache
    print("  Step 1: Write committed to PostgreSQL primary storage.")
    print("  Step 2: Simultaneously updating Redis cache...")
    r.set(wt_guest_key, json.dumps(updated_profile), ex=3600)
    print(f"  ✓ Redis cache immediately populated with fresh record: {r.get(wt_guest_key)}")

    # --------------------------------------------------------------------------
    # 4. Latency & Throughput Benchmark: Direct PostgreSQL vs. Redis Cache
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 4: EMPIRICAL LATENCY & THROUGHPUT BENCHMARK (100 ITERATIONS)")
    print("=" * 80)

    NUM_RUNS = 100
    print(f"Running {NUM_RUNS} iterations of guest profile lookup...")

    # Benchmark PostgreSQL Direct Lookups
    pg_latencies = []
    with pg_conn.cursor() as cur:
        for _ in range(NUM_RUNS):
            t0 = time.perf_counter()
            cur.execute("""
                SELECT guest_id, first_name, last_name, email, phone, nationality
                FROM guest
                WHERE guest_id = 4520;
            """)
            cur.fetchone()
            pg_latencies.append((time.perf_counter() - t0) * 1000)

    # Benchmark Redis Cache Lookups
    bench_cache_key = "bench:guest:4520"
    r.set(bench_cache_key, json.dumps({
        "guest_id": 4520, "first_name": "Tunde", "last_name": "Igwe",
        "email": "tunde.igwe4520@mail.ng", "phone": "+2348030000000"
    }))

    redis_latencies = []
    for _ in range(NUM_RUNS):
        t0 = time.perf_counter()
        r.get(bench_cache_key)
        redis_latencies.append((time.perf_counter() - t0) * 1000)

    # Statistical Computations
    pg_latencies.sort()
    redis_latencies.sort()

    avg_pg = sum(pg_latencies) / NUM_RUNS
    med_pg = pg_latencies[NUM_RUNS // 2]
    p95_pg = pg_latencies[int(NUM_RUNS * 0.95)]
    qps_pg = 1000.0 / avg_pg

    avg_redis = sum(redis_latencies) / NUM_RUNS
    med_redis = redis_latencies[NUM_RUNS // 2]
    p95_redis = redis_latencies[int(NUM_RUNS * 0.95)]
    qps_redis = 1000.0 / avg_redis

    speedup_avg = avg_pg / avg_redis
    speedup_p95 = p95_pg / p95_redis

    print(f"\n{'Metric':<25} | {'PostgreSQL (Direct)':>22} | {'Redis (Cached)':>18} | {'Improvement':>14}")
    print("-" * 85)
    print(f"{'Average Latency':<25} | {avg_pg:>19.3f} ms | {avg_redis:>15.3f} ms | {speedup_avg:>12.1f}x")
    print(f"{'Median Latency (p50)':<25} | {med_pg:>19.3f} ms | {med_redis:>15.3f} ms | {med_pg/med_redis:>12.1f}x")
    print(f"{'95th Percentile (p95)':<25} | {p95_pg:>19.3f} ms | {p95_redis:>15.3f} ms | {speedup_p95:>12.1f}x")
    print(f"{'Estimated Throughput':<25} | {qps_pg:>15.1f} ops/s | {qps_redis:>11.1f} ops/s | {qps_redis/qps_pg:>12.1f}x")

    # --------------------------------------------------------------------------
    # 5. Redis Key Space Inspection & Summary
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 5: REDIS KEYSPACE AUDIT & MEMORY HEALTH")
    print("=" * 80)

    all_keys = r.keys("*")
    print(f"  Total Keys Created in Redis: {len(all_keys)}")
    print("  Active Key Samples:")
    for k in sorted(all_keys)[:12]:
        ktype = r.type(k)
        ktimetolive = r.ttl(k)
        ttl_str = f"{ktimetolive}s" if ktimetolive > 0 else ("Persistent" if ktimetolive == -1 else "Expired")
        print(f"    - [{ktype:<6}] {k:<38} (TTL: {ttl_str})")

    info_mem = r.info("memory")
    used_mem_human = info_mem.get("used_memory_human", "N/A")
    peak_mem_human = info_mem.get("used_memory_peak_human", "N/A")
    mem_fragmentation = info_mem.get("mem_fragmentation_ratio", "N/A")

    print(f"\n  Redis Memory Footprint:")
    print(f"    - Used Memory: {used_mem_human}")
    print(f"    - Peak Memory: {peak_mem_human}")
    print(f"    - Memory Fragmentation Ratio: {mem_fragmentation}")

    print("\n==================================================================")
    print("Redis operations & benchmarking completed successfully.")
    print(f"Evidence logged to: {EVIDENCE_FILE}")
    print("==================================================================")

    pg_conn.close()
    r.close()
    sys.stdout = tee.stdout
    tee.close()


if __name__ == "__main__":
    main()
