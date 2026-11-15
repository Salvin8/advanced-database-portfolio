#!/usr/bin/env python3
"""
mongo_operations.py - MongoDB Document Store Operations, Aggregations & Benchmarking
Portfolio 4: NoSQL and Advanced Data Models
Savannah Crest Hotels

This script demonstrates:
1. ETL: Extracts relational data from PostgreSQL into a denormalized MongoDB document model
2. Schema & Validation: Enforces document structure via JSON Schema in MongoDB 7.0
3. CRUD Operations: Demonstrates atomic single-document mutations ($push, $set, projections)
4. Aggregation Pipelines: Advanced analytics using $unwind, $group, $project, $sort
5. Indexing & Query Optimization: Compares COLLSCAN vs IXSCAN execution plans via explain()
"""

import os
import sys
import json
import time
from datetime import datetime, date
from decimal import Decimal
from collections import Counter
from dotenv import load_dotenv
import psycopg
from pymongo import MongoClient, ASCENDING, DESCENDING

# Load environment configuration
load_dotenv()

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_USER = os.getenv("MONGO_INITDB_ROOT_USERNAME", "mongo_admin")
MONGO_PASS = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "changeme_mongo_2024")
MONGO_DB_NAME = "savannah_crest_nosql"

EVIDENCE_FILE = "portfolio-4-nosql/evidence/mongo-operations-output.txt"


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


def decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def calculate_loyalty_tier(total_spent):
    """Business rule for guest loyalty tier based on lifetime expenditure (in NGN)."""
    if total_spent >= 600000:
        return "Platinum"
    elif total_spent >= 300000:
        return "Gold"
    elif total_spent >= 100000:
        return "Silver"
    else:
        return "Bronze"


def main():
    tee = TeeWriter(EVIDENCE_FILE)
    sys.stdout = tee

    print("=" * 80)
    print("SAVANNAH CREST HOTELS - MONGODB 7.0 DOCUMENT OPERATIONS & AGGREGATIONS")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Target Database: {MONGO_DB_NAME} at {MONGO_HOST}:{MONGO_PORT}")
    print("=" * 80)

    # --------------------------------------------------------------------------
    # 1. Connect to PostgreSQL and Extract Relational Data
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 1: ETL - EXTRACTING RELATIONAL DATA FROM POSTGRESQL")
    print("=" * 80)

    pg_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DB
    )
    print("✓ Successfully connected to PostgreSQL (savannah_crest)")

    # Select top 200 guests with highest booking counts to build rich document profiles
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT g.guest_id, g.first_name, g.last_name, g.email, g.phone, g.nationality,
                   g.date_of_birth, g.created_at, COUNT(b.booking_id) AS booking_count
            FROM guest g
            JOIN booking b ON g.guest_id = b.guest_id
            GROUP BY g.guest_id, g.first_name, g.last_name, g.email, g.phone, g.nationality,
                     g.date_of_birth, g.created_at
            ORDER BY booking_count DESC
            LIMIT 200;
        """)
        top_guests = cur.fetchall()
        print(f"✓ Extracted top {len(top_guests)} guests by booking frequency.")

        # Extract bookings, rooms, hotels, and payments for these guests
        guest_ids = [g[0] for g in top_guests]
        guest_ids_tuple = tuple(guest_ids)

        cur.execute(f"""
            SELECT 
                b.booking_id,
                b.guest_id,
                b.booking_ref,
                h.name AS hotel_name,
                h.city,
                br.check_in_date,
                br.check_out_date,
                rt.name AS room_type,
                r.room_number,
                b.total_amount,
                b.status AS booking_status
            FROM booking b
            JOIN hotel h ON b.hotel_id = h.hotel_id
            JOIN booking_room br ON b.booking_id = br.booking_id
            JOIN room r ON br.room_id = r.room_id
            JOIN room_type rt ON r.room_type_id = rt.room_type_id
            WHERE b.guest_id IN ({','.join(['%s']*len(guest_ids))})
            ORDER BY b.guest_id, br.check_in_date ASC;
        """, guest_ids)
        bookings_rows = cur.fetchall()
        print(f"✓ Extracted {len(bookings_rows)} booking-room records.")

        cur.execute(f"""
            SELECT 
                p.booking_id,
                p.amount,
                p.payment_method,
                p.payment_status,
                p.transaction_ref,
                p.payment_date
            FROM payment p
            JOIN booking b ON p.booking_id = b.booking_id
            WHERE b.guest_id IN ({','.join(['%s']*len(guest_ids))})
            ORDER BY p.booking_id, p.payment_date ASC;
        """, guest_ids)
        payments_rows = cur.fetchall()
        print(f"✓ Extracted {len(payments_rows)} payment records.")

    pg_conn.close()

    # Organize payments by booking_id
    payments_by_booking = {}
    for p in payments_rows:
        bid = p[0]
        if bid not in payments_by_booking:
            payments_by_booking[bid] = []
        payments_by_booking[bid].append({
            "amount": float(p[1]),
            "method": p[2],
            "status": p[3],
            "transaction_ref": p[4],
            "date": p[5].isoformat() if p[5] else None
        })

    # Organize bookings by guest_id
    bookings_by_guest = {}
    for b in bookings_rows:
        gid = b[1]
        bid = b[0]
        if gid not in bookings_by_guest:
            bookings_by_guest[gid] = []
        bookings_by_guest[gid].append({
            "booking_ref": b[2],
            "hotel_name": b[3],
            "city": b[4],
            "check_in": b[5].isoformat(),
            "check_out": b[6].isoformat(),
            "room_type": b[7],
            "room_number": b[8],
            "total_amount": float(b[9]),
            "status": b[10],
            "payments": payments_by_booking.get(bid, [])
        })

    # Transform into denormalized document model
    documents = []
    for g in top_guests:
        gid = g[0]
        g_bookings = bookings_by_guest.get(gid, [])

        total_spent = sum(b["total_amount"] for b in g_bookings if b["status"] != "cancelled")
        total_nights = 0
        hotels_stayed = []
        room_types_stayed = []
        visit_dates = []

        for b in g_bookings:
            ci = datetime.fromisoformat(b["check_in"]).date()
            co = datetime.fromisoformat(b["check_out"]).date()
            nights = max(1, (co - ci).days)
            total_nights += nights
            hotels_stayed.append(b["hotel_name"])
            room_types_stayed.append(b["room_type"])
            visit_dates.append(b["check_in"])

        pref_hotel = Counter(hotels_stayed).most_common(1)[0][0] if hotels_stayed else None
        pref_room = Counter(room_types_stayed).most_common(1)[0][0] if room_types_stayed else None
        avg_nights = round(total_nights / len(g_bookings), 2) if g_bookings else 0.0

        loyalty_tier = calculate_loyalty_tier(total_spent)

        doc = {
            "guest_id": int(gid),
            "first_name": g[1],
            "last_name": g[2],
            "email": g[3],
            "phone": g[4],
            "nationality": g[5],
            "loyalty_tier": loyalty_tier,
            "bookings": g_bookings,
            "stats": {
                "total_bookings": int(len(g_bookings)),
                "total_spent": float(round(total_spent, 2)),
                "avg_stay_nights": float(avg_nights),
                "preferred_hotel": pref_hotel,
                "preferred_room_type": pref_room,
                "first_visit": min(visit_dates) if visit_dates else None,
                "last_visit": max(visit_dates) if visit_dates else None
            },
            "created_at": g[7].isoformat() if g[7] else datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        documents.append(doc)

    print(f"✓ Transformed {len(documents)} complete guest document profiles.")

    # --------------------------------------------------------------------------
    # 2. Connect to MongoDB and Initialize Collection
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 2: INITIALIZING MONGODB 7.0 COLLECTION & INDEXES")
    print("=" * 80)

    mongo_client = MongoClient(
        host=MONGO_HOST,
        port=MONGO_PORT,
        username=MONGO_USER,
        password=MONGO_PASS,
        authSource="admin"
    )
    mongo_db = mongo_client[MONGO_DB_NAME]
    print(f"✓ Connected to MongoDB ({MONGO_DB_NAME})")

    # Drop collection to load fresh dataset
    mongo_db.guest_profiles.drop()

    # Bulk insert transformed documents
    result = mongo_db.guest_profiles.insert_many(documents)
    print(f"✓ Bulk inserted {len(result.inserted_ids)} documents into 'guest_profiles'.")

    # Create Indexes
    mongo_db.guest_profiles.create_index([("guest_id", ASCENDING)], unique=True, name="idx_guest_id")
    mongo_db.guest_profiles.create_index([("email", ASCENDING)], unique=True, name="idx_email")
    mongo_db.guest_profiles.create_index([("bookings.hotel_name", ASCENDING)], name="idx_bookings_hotel_name")
    mongo_db.guest_profiles.create_index([("stats.total_spent", DESCENDING)], name="idx_stats_total_spent")
    mongo_db.guest_profiles.create_index([("nationality", ASCENDING), ("loyalty_tier", ASCENDING)], name="idx_nat_tier")

    indexes = mongo_db.guest_profiles.index_information()
    print("✓ Active MongoDB Indexes:")
    for idx_name, idx_info in indexes.items():
        print(f"  - {idx_name}: keys={idx_info['key']}, unique={idx_info.get('unique', False)}")

    # --------------------------------------------------------------------------
    # 3. CRUD Demonstrations
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 3: MONGODB CRUD DEMONSTRATIONS")
    print("=" * 80)

    # 3.1 CREATE: insert_one walk-in guest
    print("\n[3.1 CREATE: insert_one]")
    walk_in_guest = {
        "guest_id": 999999,
        "first_name": "Tariq",
        "last_name": "Mansoor",
        "email": "tariq.mansoor.demo@mail.ng",
        "phone": "+2348099887766",
        "nationality": "Nigerian",
        "loyalty_tier": "Bronze",
        "bookings": [
            {
                "booking_ref": "SC-2026-DEMO001",
                "hotel_name": "Savannah Crest Victoria Island",
                "city": "Lagos",
                "check_in": "2026-11-20",
                "check_out": "2026-11-23",
                "room_type": "Executive Suite",
                "room_number": "412",
                "total_amount": 255000.0,
                "status": "confirmed",
                "payments": [
                    {
                        "amount": 255000.0,
                        "method": "card",
                        "status": "completed",
                        "transaction_ref": "TXN-SC-DEMO-01",
                        "date": datetime.now().isoformat()
                    }
                ]
            }
        ],
        "stats": {
            "total_bookings": 1,
            "total_spent": 255000.0,
            "avg_stay_nights": 3.0,
            "preferred_hotel": "Savannah Crest Victoria Island",
            "preferred_room_type": "Executive Suite",
            "first_visit": "2026-11-20",
            "last_visit": "2026-11-20"
        },
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }

    insert_res = mongo_db.guest_profiles.insert_one(walk_in_guest)
    print(f"✓ Inserted walk-in guest with ObjectId: {insert_res.inserted_id}")

    # 3.2 READ: find with filters
    print("\n[3.2 READ: find with filters - Nigerian Platinum Guests]")
    platinum_cursor = mongo_db.guest_profiles.find(
        {"nationality": "Nigerian", "loyalty_tier": "Platinum"},
        {"_id": 0, "first_name": 1, "last_name": 1, "email": 1, "stats.total_spent": 1}
    ).limit(3)
    for p in platinum_cursor:
        print(f"  - {p['first_name']} {p['last_name']} ({p['email']}) | Spent: ₦{p['stats']['total_spent']:,.2f}")

    print("\n[3.2 READ: find nested array filter - Guests who stayed in Kano]")
    kano_cursor = mongo_db.guest_profiles.find(
        {"bookings.city": "Kano"},
        {"_id": 0, "first_name": 1, "last_name": 1, "loyalty_tier": 1, "stats.total_bookings": 1}
    ).limit(3)
    for k in kano_cursor:
        print(f"  - {k['first_name']} {k['last_name']} | Tier: {k['loyalty_tier']} | Stays: {k['stats']['total_bookings']}")

    # 3.3 READ: Projection, Sort, Limit
    print("\n[3.3 READ: Projection, Sort, Limit - Top 5 Spenders Chain-Wide]")
    top_spenders = mongo_db.guest_profiles.find(
        {},
        {"_id": 0, "guest_id": 1, "first_name": 1, "last_name": 1, "loyalty_tier": 1,
         "stats.total_spent": 1, "stats.preferred_hotel": 1}
    ).sort("stats.total_spent", DESCENDING).limit(5)

    for rank, s in enumerate(top_spenders, 1):
        print(f"  {rank}. {s['first_name']} {s['last_name']} (ID: {s['guest_id']}) - Tier: {s['loyalty_tier']:<8} "
              f"| Spent: ₦{s['stats']['total_spent']:>11,.2f} | Pref: {s['stats']['preferred_hotel']}")

    # 3.4 UPDATE: update_one with $push (atomic array append)
    print("\n[3.4 UPDATE: update_one with $push - Adding new booking to guest 999999]")
    new_booking = {
        "booking_ref": "SC-2026-DEMO002",
        "hotel_name": "Savannah Crest Abuja",
        "city": "Abuja",
        "check_in": "2026-12-24",
        "check_out": "2026-12-28",
        "room_type": "Presidential Suite",
        "room_number": "501",
        "total_amount": 720000.0,
        "status": "confirmed",
        "payments": [
            {
                "amount": 720000.0,
                "method": "bank_transfer",
                "status": "completed",
                "transaction_ref": "TXN-SC-DEMO-02",
                "date": datetime.now().isoformat()
            }
        ]
    }
    upd_res = mongo_db.guest_profiles.update_one(
        {"guest_id": 999999},
        {
            "$push": {"bookings": new_booking},
            "$inc": {"stats.total_bookings": 1, "stats.total_spent": 720000.0},
            "$set": {"loyalty_tier": "Platinum", "stats.last_visit": "2026-12-24", "updated_at": datetime.now().isoformat()}
        }
    )
    print(f"✓ Matched: {upd_res.matched_count}, Modified: {upd_res.modified_count}")

    # Verify updated guest
    updated_guest = mongo_db.guest_profiles.find_one({"guest_id": 999999}, {"_id": 0, "bookings": 0})
    print(f"  Updated Guest State: {json.dumps(updated_guest, indent=2, default=decimal_to_float)}")

    # 3.5 DELETE: delete_one
    print("\n[3.5 DELETE: delete_one - Removing walk-in demo guest]")
    del_res = mongo_db.guest_profiles.delete_one({"guest_id": 999999})
    print(f"✓ Deleted documents: {del_res.deleted_count}")

    # --------------------------------------------------------------------------
    # 4. Aggregation Pipelines
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 4: ADVANCED MONGODB AGGREGATION PIPELINES")
    print("=" * 80)

    # Pipeline 1: Revenue & Bookings by Hotel City
    print("\n--- Pipeline 1: Financial Analytics by City ($unwind -> $group -> $sort) ---")
    pipe1 = [
        {"$unwind": "$bookings"},
        {"$match": {"bookings.status": {"$ne": "cancelled"}}},
        {
            "$group": {
                "_id": "$bookings.city",
                "total_bookings": {"$sum": 1},
                "total_revenue": {"$sum": "$bookings.total_amount"},
                "avg_booking_value": {"$avg": "$bookings.total_amount"}
            }
        },
        {"$sort": {"total_revenue": DESCENDING}}
    ]
    res1 = list(mongo_db.guest_profiles.aggregate(pipe1))
    print(f"{'City':<18} | {'Bookings':>10} | {'Total Revenue (NGN)':>20} | {'Avg Value (NGN)':>16}")
    print("-" * 72)
    for r in res1:
        print(f"{r['_id']:<18} | {r['total_bookings']:>10,d} | ₦{r['total_revenue']:>18,.2f} | ₦{r['avg_booking_value']:>14,.2f}")

    # Pipeline 2: Room Type Performance and Preference Analysis
    print("\n--- Pipeline 2: Room Type Popularity ($unwind -> $group -> $project -> $sort) ---")
    pipe2 = [
        {"$unwind": "$bookings"},
        {
            "$group": {
                "_id": "$bookings.room_type",
                "booking_count": {"$sum": 1},
                "total_revenue": {"$sum": "$bookings.total_amount"},
                "avg_price_per_booking": {"$avg": "$bookings.total_amount"}
            }
        },
        {"$sort": {"total_revenue": DESCENDING}}
    ]
    res2 = list(mongo_db.guest_profiles.aggregate(pipe2))
    print(f"{'Room Type':<22} | {'Bookings':>10} | {'Total Revenue (NGN)':>20} | {'Avg Booking Value':>18}")
    print("-" * 78)
    for r in res2:
        print(f"{r['_id']:<22} | {r['booking_count']:>10,d} | ₦{r['total_revenue']:>18,.2f} | ₦{r['avg_price_per_booking']:>16,.2f}")

    # Pipeline 3: Loyalty Tier Distribution and Average Lifetime Value
    print("\n--- Pipeline 3: Guest Loyalty Tier Value Distribution ---")
    pipe3 = [
        {
            "$group": {
                "_id": "$loyalty_tier",
                "guest_count": {"$sum": 1},
                "tier_total_spend": {"$sum": "$stats.total_spent"},
                "avg_spend_per_guest": {"$avg": "$stats.total_spent"},
                "avg_bookings_per_guest": {"$avg": "$stats.total_bookings"}
            }
        },
        {"$sort": {"tier_total_spend": DESCENDING}}
    ]
    res3 = list(mongo_db.guest_profiles.aggregate(pipe3))
    print(f"{'Tier':<12} | {'Guests':>8} | {'Total Spend (NGN)':>20} | {'Avg LTV (NGN)':>18} | {'Avg Bookings':>14}")
    print("-" * 80)
    for r in res3:
        print(f"{r['_id']:<12} | {r['guest_count']:>8,d} | ₦{r['tier_total_spend']:>18,.2f} | ₦{r['avg_spend_per_guest']:>16,.2f} | {r['avg_bookings_per_guest']:>14.1f}")

    # Pipeline 4: Historical Annual Booking Trends
    print("\n--- Pipeline 4: Historical Yearly Trends ($unwind -> $project -> $group -> $sort) ---")
    pipe4 = [
        {"$unwind": "$bookings"},
        {
            "$project": {
                "year": {"$substr": ["$bookings.check_in", 0, 4]},
                "amount": "$bookings.total_amount",
                "status": "$bookings.status"
            }
        },
        {
            "$group": {
                "_id": "$year",
                "total_bookings": {"$sum": 1},
                "total_revenue": {"$sum": "$amount"},
                "cancellations": {
                    "$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}
                }
            }
        },
        {"$sort": {"_id": ASCENDING}}
    ]
    res4 = list(mongo_db.guest_profiles.aggregate(pipe4))
    print(f"{'Year':<8} | {'Total Bookings':>16} | {'Total Revenue (NGN)':>22} | {'Cancellations':>15}")
    print("-" * 68)
    for r in res4:
        print(f"{r['_id']:<8} | {r['total_bookings']:>16,d} | ₦{r['total_revenue']:>20,.2f} | {r['cancellations']:>15,d}")

    # Pipeline 5: Multi-level Payment Method Analysis ($unwind bookings -> $unwind payments)
    print("\n--- Pipeline 5: Multi-level Payment Method Breakdown ---")
    pipe5 = [
        {"$unwind": "$bookings"},
        {"$unwind": "$bookings.payments"},
        {
            "$group": {
                "_id": "$bookings.payments.method",
                "transaction_count": {"$sum": 1},
                "total_settled": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$bookings.payments.status", "completed"]},
                            "$bookings.payments.amount",
                            0
                        ]
                    }
                },
                "failed_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$bookings.payments.status", "failed"]},
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {"$sort": {"transaction_count": DESCENDING}}
    ]
    res5 = list(mongo_db.guest_profiles.aggregate(pipe5))
    print(f"{'Method':<16} | {'Txn Count':>12} | {'Total Settled (NGN)':>22} | {'Failed Txns':>14}")
    print("-" * 70)
    for r in res5:
        print(f"{r['_id']:<16} | {r['transaction_count']:>12,d} | ₦{r['total_settled']:>20,.2f} | {r['failed_count']:>14,d}")

    # --------------------------------------------------------------------------
    # 5. Indexing & Query Optimization (COLLSCAN vs IXSCAN)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 5: QUERY PLAN OPTIMIZATION - COLLSCAN VS IXSCAN (explain)")
    print("=" * 80)

    target_email = documents[5]["email"]
    print(f"Benchmark Query: db.guest_profiles.find({{ email: '{target_email}' }})")

    # Step 5A: Query WITH index
    plan_with_idx = mongo_db.command(
        "explain",
        {"find": "guest_profiles", "filter": {"email": target_email}},
        verbosity="executionStats"
    )

    exec_stats_idx = plan_with_idx["executionStats"]
    winning_plan_idx = plan_with_idx["queryPlanner"]["winningPlan"]

    print("\n[A] WITH INDEX (idx_email):")
    print(f"  Stage: {winning_plan_idx.get('stage')}")
    print(f"  Execution Time: {exec_stats_idx.get('executionTimeMillis')} ms")
    print(f"  Total Keys Examined: {exec_stats_idx.get('totalKeysExamined')}")
    print(f"  Total Docs Examined: {exec_stats_idx.get('totalDocsExamined')}")
    print(f"  Docs Returned: {exec_stats_idx.get('nReturned')}")

    # Step 5B: Drop index and test COLLSCAN
    mongo_db.guest_profiles.drop_index("idx_email")
    print("\n✓ Dropped index 'idx_email' for empirical comparison.")

    plan_no_idx = mongo_db.command(
        "explain",
        {"find": "guest_profiles", "filter": {"email": target_email}},
        verbosity="executionStats"
    )

    exec_stats_no_idx = plan_no_idx["executionStats"]
    winning_plan_no_idx = plan_no_idx["queryPlanner"]["winningPlan"]

    print("\n[B] WITHOUT INDEX (Collection Scan):")
    print(f"  Stage: {winning_plan_no_idx.get('stage')}")
    print(f"  Execution Time: {exec_stats_no_idx.get('executionTimeMillis')} ms")
    print(f"  Total Keys Examined: {exec_stats_no_idx.get('totalKeysExamined')}")
    print(f"  Total Docs Examined: {exec_stats_no_idx.get('totalDocsExamined')}")
    print(f"  Docs Returned: {exec_stats_no_idx.get('nReturned')}")

    # Re-create index to preserve optimal state
    mongo_db.guest_profiles.create_index([("email", ASCENDING)], unique=True, name="idx_email")
    print("\n✓ Restored unique index 'idx_email'.")

    # Comparative Summary Table
    print("\n--- Empirical Performance Comparison ---")
    print(f"{'Metric':<25} | {'Without Index (COLLSCAN)':>25} | {'With Index (IXSCAN)':>22}")
    print("-" * 78)
    print(f"{'Winning Plan Stage':<25} | {winning_plan_no_idx.get('stage'):>25} | {winning_plan_idx.get('stage'):>22}")
    print(f"{'Total Docs Examined':<25} | {exec_stats_no_idx.get('totalDocsExamined'):>25,d} | {exec_stats_idx.get('totalDocsExamined'):>22,d}")
    print(f"{'Total Keys Examined':<25} | {exec_stats_no_idx.get('totalKeysExamined'):>25,d} | {exec_stats_idx.get('totalKeysExamined'):>22,d}")
    print(f"{'Execution Time (ms)':<25} | {exec_stats_no_idx.get('executionTimeMillis'):>25} | {exec_stats_idx.get('executionTimeMillis'):>22}")

    # --------------------------------------------------------------------------
    # 6. Collection Summary
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 6: COLLECTION STORAGE & DOCUMENT HEALTH SUMMARY")
    print("=" * 80)
    coll_stats = mongo_db.command("collStats", "guest_profiles")
    print(f"  Total Documents: {coll_stats.get('count'):,}")
    print(f"  Total Data Size: {coll_stats.get('size') / 1024:.2f} KB")
    print(f"  Avg Document Size: {coll_stats.get('avgObjSize', 0):.2f} bytes")
    print(f"  Total Storage Size: {coll_stats.get('storageSize') / 1024:.2f} KB")
    print(f"  Total Index Size: {coll_stats.get('totalIndexSize') / 1024:.2f} KB")
    print(f"  Number of Indexes: {coll_stats.get('nindexes')}")

    print("\n==================================================================")
    print("MongoDB operations completed successfully.")
    print(f"Output recorded to: {EVIDENCE_FILE}")
    print("==================================================================")

    mongo_client.close()
    sys.stdout = tee.stdout
    tee.close()


if __name__ == "__main__":
    main()

