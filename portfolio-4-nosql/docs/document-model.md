# MongoDB Document Model & Schema Architecture

**Portfolio 4: NoSQL and Advanced Data Models**  
**Savannah Crest Hotels Management System**

---

## 1. Executive Summary & Design Rationale

In Portfolios 1 through 3, Savannah Crest Hotels was modelled as a strictly normalised relational schema in PostgreSQL 16. While the third normal form (3NF) relational design guarantees data integrity, zero redundancy, and strict transactional ACID enforcement, it introduces significant join overhead for read-intensive guest profile lookups and CRM analytics.

A front-desk receptionist checking in a guest, or a mobile guest application rendering a "My Stays & Loyalty" dashboard, requires data spanning five relational tables:
1. `guest` (demographics and contact details)
2. `booking` (reservation headers and statuses)
3. `booking_room` (dates, rates, and assigned room numbers)
4. `room` and `room_type` (physical room and amenity definitions)
5. `payment` (financial transactions, payment methods, and statuses)

In PostgreSQL, assembling this complete "Guest 360" dossier requires a multi-table `JOIN` with aggregation subqueries or window functions. In MongoDB 7.0, we adopt a **denormalised document model** (`guest_profiles` collection) that collapses this relational subgraph into a single hierarchical BSON document.

```
Relational Model (Normalized 3NF)          Document Model (Denormalized BSON)
┌──────────────┐                          ┌─────────────────────────────────────────┐
│    guest     │                          │ guest_profiles                          │
└──────┬───────┘                          │  ├── guest_id, name, email, phone       │
       │ 1:N                              │  ├── loyalty_tier                       │
┌──────▼───────┐                          │  ├── stats (pre-aggregated summary)     │
│   booking    │                          │  │    ├── total_bookings, total_spent   │
└──────┬───────┘                          │  │    └── preferred_hotel, avg_stay     │
       │ 1:N                              │  └── bookings: [                        │
┌──────▼───────┐  1:N   ┌──────────────┐  │       ├── booking_ref, hotel, dates     │
│ booking_room ├───────►│   payment    │  │       ├── room_type, room_number, status│
└──────┬───────┘        └──────────────┘  │       └── payments: [                   │
       │ N:1                              │            └── amount, method, status   │
┌──────▼───────┐                          │           ]                             │
│     room     │                          │      ]                                  │
└──────────────┘                          └─────────────────────────────────────────┘
```

---

## 2. Embedding vs. Referencing Decision Matrix

A foundational architectural decision in document database design is whether related entities should be **embedded** as subdocuments/arrays or **referenced** via foreign keys/`ObjectId` references.

| Entity Relationship | Design Decision | Architectural Justification |
| :--- | :---: | :--- |
| **Guest $\rightarrow$ Loyalty Stats** | **Embedded Subdocument** | **1:1 Cardinality & Co-locality:** Pre-aggregated statistics (`total_spent`, `preferred_hotel`, `avg_stay_nights`) are always queried together with the guest profile. Embedding eliminates query joins and enables instant dashboard rendering. |
| **Guest $\rightarrow$ Bookings** | **Embedded Array** | **Bounded 1:N Cardinality:** Even high-frequency business travellers accumulate at most 50–100 bookings over several years. A guest document with 100 bookings consumes ~25 KB of memory, well within MongoDB's 16 MB BSON document size ceiling. Bookings are logically owned by the guest. |
| **Booking $\rightarrow$ Payments** | **Embedded Array** | **Bounded 1:N (Small):** A single hotel booking typically has 1 to 3 payment attempts (e.g., initial deposit, final balance settlement, or a failed card retry). Embedding guarantees that financial settlement history is retrieved atomically with the booking. |
| **Booking $\rightarrow$ Hotel / Room Type** | **Denormalised Attributes** | **Read-optimised Snapshot:** The hotel name, city, and room type name are copied directly into the booking subdocument. Room rates and property names at the time of booking represent an immutable historical audit trail, shielding past reservations from future hotel renamings. |
| **Room Inventory / Grid** | **Referenced (Kept in PostgreSQL)** | **High Contention & Global State:** Available room inventory is shared across all guests simultaneously. Embedding room inventory inside guest documents would cause severe data duplication and impossible concurrency locks. Real-time room allocation remains in PostgreSQL using GiST exclusion constraints. |

---

## 3. Formal Document Schema Specification

The `guest_profiles` collection is enforced via **MongoDB JSON Schema Validation** (`$jsonSchema`) at `validationLevel: "moderate"` and `validationAction: "error"`, ensuring strict type safety while retaining document flexibility:

```json
{
  "$jsonSchema": {
    "bsonType": "object",
    "required": ["guest_id", "first_name", "last_name", "email", "loyalty_tier", "bookings", "stats"],
    "properties": {
      "guest_id": { "bsonType": "int" },
      "first_name": { "bsonType": "string" },
      "last_name": { "bsonType": "string" },
      "email": { 
        "bsonType": "string",
        "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
      },
      "phone": { "bsonType": ["string", "null"] },
      "nationality": { "bsonType": ["string", "null"] },
      "loyalty_tier": { "enum": ["Bronze", "Silver", "Gold", "Platinum"] },
      "bookings": {
        "bsonType": "array",
        "items": {
          "bsonType": "object",
          "required": ["booking_ref", "hotel_name", "city", "check_in", "check_out", "room_type", "total_amount", "status"],
          "properties": {
            "booking_ref": { "bsonType": "string" },
            "hotel_name": { "bsonType": "string" },
            "city": { "bsonType": "string" },
            "check_in": { "bsonType": "string" },
            "check_out": { "bsonType": "string" },
            "room_type": { "bsonType": "string" },
            "room_number": { "bsonType": ["string", "null"] },
            "total_amount": { "bsonType": "number", "minimum": 0 },
            "status": { "enum": ["pending", "confirmed", "checked_in", "checked_out", "cancelled", "no_show"] },
            "payments": {
              "bsonType": "array",
              "items": {
                "bsonType": "object",
                "required": ["amount", "method", "status"],
                "properties": {
                  "amount": { "bsonType": "number", "minimum": 0 },
                  "method": { "enum": ["card", "bank_transfer", "mobile_money", "cash"] },
                  "status": { "enum": ["pending", "completed", "failed", "refunded"] },
                  "transaction_ref": { "bsonType": ["string", "null"] },
                  "date": { "bsonType": ["date", "string", "null"] }
                }
              }
            }
          }
        }
      },
      "stats": {
        "bsonType": "object",
        "required": ["total_bookings", "total_spent", "avg_stay_nights"],
        "properties": {
          "total_bookings": { "bsonType": "int", "minimum": 0 },
          "total_spent": { "bsonType": "number", "minimum": 0 },
          "avg_stay_nights": { "bsonType": "number", "minimum": 0 },
          "preferred_hotel": { "bsonType": ["string", "null"] },
          "preferred_room_type": { "bsonType": ["string", "null"] },
          "first_visit": { "bsonType": ["string", "null"] },
          "last_visit": { "bsonType": ["string", "null"] }
        }
      }
    }
  }
}
```

---

## 4. Structural Comparison: Relational vs. Document

| Operational Dimension | Relational Model (PostgreSQL 16) | Document Model (MongoDB 7.0) |
| :--- | :--- | :--- |
| **Normalisation Level** | Boyce-Codd Normal Form (BCNF) / 3NF | Denormalised Document Store |
| **Query Latency (Single Guest Dossier)** | Moderate (Requires 4-way join across `guest`, `booking`, `booking_room`, `payment`) | Ultra-Low (Single primary key or email lookup directly into BSON memory) |
| **Atomicity Scope** | Multi-table ACID transaction via WAL (`BEGIN ... COMMIT`) | Single-document ACID transaction per document mutation |
| **Write Amplification** | Low (Updates modify only specific fixed-width tuple in heap) | Moderate to High (Appending to `bookings` array requires resizing the BSON document and updating multikey indexes) |
| **Schema Evolution** | `ALTER TABLE` DDL locks or migration scripts required | Polymorphic / Dynamic schema (field addition requires no table downtime) |
| **Cross-entity Joins** | First-class SQL operator (`JOIN`) executed via Hash/Merge Join | Emulated via `$lookup` aggregation stage (computationally expensive) |

---

## 5. ACID Guarantees & Transactional Trade-Offs

### 5.1 Single-Document Atomicity
MongoDB provides **strict ACID guarantees for single-document modifications**. When an operation appends a new reservation to a guest's profile using `$push` while updating loyalty metrics using `$inc` and `$set`:

```python
mongo_db.guest_profiles.update_one(
    {"guest_id": 999999},
    {
        "$push": {"bookings": new_booking},
        "$inc": {"stats.total_bookings": 1, "stats.total_spent": 720000.0},
        "$set": {"loyalty_tier": "Platinum", "updated_at": datetime.now().isoformat()}
    }
)
```
This mutation is **100% atomic**:
- Either all modifications succeed simultaneously, or none do.
- Readers never observe a partial state where the booking was added but the total spend was not updated.
- No locks are acquired on other guests' documents, eliminating lock contention.

### 5.2 Multi-Document Constraints & When Relational is Mandatory
Where MongoDB falls short compared to PostgreSQL:
1. **Cross-Document Constraints:** MongoDB cannot enforce that a room is not double-booked across two different guest documents without multi-document ACID transactions or distributed locks.
2. **Global Financial Auditing:** In PostgreSQL, the `payment` table is an immutable append-only ledger with database-level foreign key constraints. In MongoDB, updating nested payments across documents poses synchronization complexity.

---

## 6. Indexing Strategy & Execution Plan Analysis

To support fast operational queries, we provisioned targeted single-field, compound, and multikey indexes:

1. `idx_guest_id` (`{ "guest_id": 1 }`, Unique): Direct O(1) relational key lookup.
2. `idx_email` (`{ "email": 1 }`, Unique): Front-desk and login authentication lookup.
3. `idx_bookings_hotel_name` (`{ "bookings.hotel_name": 1 }`): **Multikey Index** indexing every array element inside the nested `bookings` array.
4. `idx_stats_total_spent` (`{ "stats.total_spent": -1 }`): High-value guest VIP ranking queries.
5. `idx_nat_tier` (`{ "nationality": 1, "loyalty_tier": 1 }`): Compound index for segmented marketing campaigns.

### Empirical Query Plan Benchmark (from `mongo_operations.py`)

We executed an exact email lookup (`fatima.eze6331@mail.ng`) under two empirical conditions:

```
Benchmark Query: db.guest_profiles.find({ email: 'fatima.eze6331@mail.ng' })
```

| Metric | Without Index (`COLLSCAN`) | With Index (`IXSCAN` + `FETCH`) | Architectural Impact |
| :--- | :---: | :---: | :--- |
| **Winning Plan Stage** | `COLLSCAN` | `FETCH` $\leftarrow$ `IXSCAN` | Index isolates target BSON document directly via B-tree traversal |
| **Documents Examined** | **200** | **1** | **99.5% reduction** in scanned documents |
| **Keys Examined** | 0 | 1 | Exact single-key B-tree hit |
| **Query Complexity** | $\mathcal{O}(N)$ linear scan | $\mathcal{O}(\log N)$ logarithmic lookup | Scalable to millions of guest profiles without CPU saturation |

---

## 7. Aggregation Pipeline Analytics

The MongoDB Aggregation Framework processes streams of documents through multi-stage pipelines. Our operational demonstration implemented five pipelines:

### 7.1 Pipeline 1: Financial Analytics by City
- Stages: `{"$unwind": "$bookings"}` $\rightarrow$ `{"$match": {"bookings.status": {"$ne": "cancelled"}}}` $\rightarrow$ `{"$group": { "_id": "$bookings.city", "total_revenue": {"$sum": "$bookings.total_amount"} }}` $\rightarrow$ `{"$sort": {"total_revenue": -1}}`
- **Result:** Lagos generated highest revenue (₦222.89M from 1,623 bookings), followed by Abuja (₦214.53M from 1,635 bookings).

### 7.2 Pipeline 2: Room Type Popularity
- Evaluates booking volume versus gross yield.
- **Finding:** While Standard Rooms had highest volume (5,103 bookings, ₦333.64M), Presidential Suites generated ₦225.54M across only 550 bookings (average booking value ₦410,072.73).

### 7.3 Pipeline 3: Loyalty Tier Value Distribution
- Groups guests by loyalty classification to assess lifetime customer value (LTV).
- Demonstrates how pre-aggregated `stats` allow tier evaluations without unwinding child arrays.

### 7.4 Pipeline 4: Historical Yearly Trends
- Stages: `$unwind` $\rightarrow$ `$project` (extracting year substring from ISO timestamp) $\rightarrow$ `$group` $\rightarrow$ `$sort`.
- Accurately tracks booking volumes and cancellation ratios across operational years 2020 through 2026.

### 7.5 Pipeline 5: Multi-Level Payment Breakdown
- Demonstrates nested `$unwind` (unwinding `bookings`, then unwinding `payments` within each booking).
- Analyzes settlement volumes across card (₦646.6M), bank transfers (₦281.3M), and mobile money (₦159.1M).

---

## 8. Polyglot Persistence Architecture

Savannah Crest Hotels operates under a **Polyglot Persistence** pattern:
- **PostgreSQL 16 (Relational System of Record):** Owns room inventory, live date range exclusion constraints (`btree_gist`), active room status histories, and the master financial ledger.
- **MongoDB 7.0 (Document Store / Read Model):** Serves as the operational data store for guest-facing mobile applications, CRM dossiers, VIP personalisation, and multi-dimensional analytical queries.
- **Synchronization Strategy:** PostgreSQL triggers or change data capture (CDC) pipelines stream committed reservations into MongoDB `guest_profiles`, keeping the read cache synchronized with zero risk of transaction double-booking.

