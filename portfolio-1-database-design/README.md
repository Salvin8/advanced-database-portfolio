# Portfolio 1: Database Design and Modelling

**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** Savannah Crest Hotels (Central Reservation and Property Management System)  
**Database Engine:** PostgreSQL 16  
**Status:** Completed  

---

## 1. Overview and Deliverables

Portfolio 1 implements the complete conceptual, logical, and physical database design for Savannah Crest Hotels across 6 properties in Nigeria (Abuja, Lagos, Port Harcourt, Kano, Enugu, Ibadan).

The deliverables comprise:
- **Requirements & Business Rules:** [docs/requirements.md](docs/requirements.md) (16 business rules, entity catalog, cardinalities, 10 core queries).
- **Entity-Relationship Diagram:** [docs/er-diagram.md](docs/er-diagram.md) (Mermaid ER diagram detailing PK/FK relationships and cardinalities).
- **Relational Schema DDL:** [sql/01_schema.sql](sql/01_schema.sql) (PostgreSQL 16 DDL with keys, constraints, generated daterange, exclusion constraint).
- **Views and Triggers:** [sql/02_views_and_triggers.sql](sql/02_views_and_triggers.sql) (Availability, occupancy, housekeeping status, audit trigger).
- **Normalisation Analysis:** [docs/normalisation.md](docs/normalisation.md) (Rigorous UNF -> 1NF -> 2NF -> 3NF/BCNF decomposition and denormalisation justifications).
- **Schema Overview:** [docs/schema-overview.md](docs/schema-overview.md) (Table-by-table specifications).
- **Constraint Test Suite:** [sql/03_constraint_tests.sql](sql/03_constraint_tests.sql) (Positive and negative test harness).
- **Empirical Evidence:** [evidence/](evidence/) (All real terminal outputs from psql: tables, descriptions, constraints, views, triggers, and test execution logs).
- **Screenshots Guide:** [screenshots/README.md](screenshots/README.md) (Instructions for assessor inspection captures).

---

## 2. Environment and How to Run

Ensure the PostgreSQL container is running:
```bash
make up
```

Apply the schema and views cleanly:
```bash
make p1
```

Run the constraint verification test suite and capture results:
```bash
docker compose exec -T postgres psql -U hotel_admin -d savannah_crest \
  < portfolio-1-database-design/sql/03_constraint_tests.sql \
  > portfolio-1-database-design/evidence/constraint-tests.txt 2>&1
```

Re-generate all table and constraint evidence dumps:
```bash
bash portfolio-1-database-design/evidence/capture_schema_evidence.sh
```

---

## 3. Advanced Concept: The GiST Exclusion Constraint

A core requirement in hotel management is the prevention of double bookings. Standard SQL primary and unique constraints can only enforce discrete equality on single columns or combinations (e.g., room 101 cannot be assigned twice with the same reservation ID). They cannot evaluate temporal range intersections ($[start_1, end_1) \cap [start_2, end_2) \neq \emptyset$).

In this design, double booking prevention is enforced at the database kernel level using PostgreSQL's generalized search tree (GiST) index with the `btree_gist` extension:

```sql
CONSTRAINT excl_no_overlapping_booking EXCLUDE USING gist (
    room_id WITH =,
    stay    WITH &&
) WHERE (status IN ('reserved', 'checked_in'))
```

### Explanatory notes:
- **`btree_gist` extension:** Standard GiST indexes do not support scalar integer equality (`=`). The extension provides GiST operator classes for standard B-tree types, enabling a single multi-column GiST index over `(room_id, stay)`.
- **`stay` daterange with `[)` bounds:** Check-in date is inclusive; check-out date is exclusive. If Guest A checks out on `2026-12-15` and Guest B checks in on `2026-12-15`, the ranges `[2026-12-10, 2026-12-15)` and `[2026-12-15, 2026-12-20)` do not intersect (`&&` evaluates to `FALSE`). This allows frictionless same-day turnaround.
- **Partial filter (`WHERE status IN ('reserved', 'checked_in')`):** When a booking is marked `cancelled` or `checked_out`, it stops competing for the room. A cancelled booking retains its row for audit without blocking future reservations for those dates.

---

## 4. Evidence Summary

| Deliverable | File Path | Description |
|---|---|---|
| Table Catalog | [evidence/table-list.txt](evidence/table-list.txt) | `\dt+` output confirming 12 tables in public schema |
| Constraint Catalog | [evidence/all-constraints.txt](evidence/all-constraints.txt) | All PK, FK, CHECK, and EXCLUSION constraints queried from `pg_constraint` |
| Views Catalog | [evidence/view-list.txt](evidence/view-list.txt) | `\dv+` output showing availability, occupancy, and status views |
| Triggers Catalog | [evidence/trigger-list.txt](evidence/trigger-list.txt) | Triggers on `booking`, `hotel`, and `guest` |
| Constraint Execution Log | [evidence/constraint-tests.txt](evidence/constraint-tests.txt) | Live terminal execution log proving rejection of overlapping dates, negative money, orphan FKs |
| Table Definitions | `evidence/desc-<table_name>.txt` | Detailed `\d+` schema descriptions for each table |

---

## 5. Visual Evidence & Screenshots

- `TODO: add screenshot` [screenshots/p1-01-schema-tables.png](screenshots/p1-01-schema-tables.png) (Terminal showing `\dt+` output of all 12 tables)
- `TODO: add screenshot` [screenshots/p1-02-exclusion-constraint.png](screenshots/p1-02-exclusion-constraint.png) (Terminal showing `\d+ booking_room` focusing on the GiST exclusion constraint)
- `TODO: add screenshot` [screenshots/p1-03-constraint-violation-tests.png](screenshots/p1-03-constraint-violation-tests.png) (Terminal output executing `03_constraint_tests.sql` showing PostgreSQL constraint exceptions)

---

## 6. How I Would Explain This (Viva Notes)

1. **Why date ranges and pricing live on `booking_room` rather than `booking`:**
   - In realistic hotel systems, a single reservation can cover multiple rooms with differing lengths of stay (e.g., a conference attendee booking a deluxe room for 5 days and a standard room for a colleague for 2 days). Placing dates on the booking header would force artificial homogeneity or duplicate booking headers.
   - *Alternative rejected:* 1:1 booking-to-room table. This breaks multi-room family and corporate reservations into disconnected records.

2. **Why rate per night is snapshotted onto `booking_room`:**
   - The agreed price at reservation time is a legally binding contract. If management updates holiday rates in `seasonal_rate` next month, historical or existing confirmed bookings must not change their price.
   - *Alternative rejected:* Dynamic runtime price lookup from `seasonal_rate`. While strictly 3NF-compliant, it creates financial and legal calculation errors when tariffs change.

3. **Why exclusion constraints are superior to application-level checks:**
   - Application code checking `SELECT COUNT(*) WHERE room_id = X AND stay && Y` followed by an `INSERT` is susceptible to race conditions under concurrent requests. Two concurrent transactions can both read `COUNT = 0` and proceed to insert, causing a double booking. The GiST exclusion constraint enforces serialised mutual exclusion directly inside the PostgreSQL storage engine.
   - *Alternative rejected:* Application-level validation only, or manual table locking (`LOCK TABLE booking_room IN EXCLUSIVE MODE`), which destroys throughput.

4. **Why room status history is an append-only log:**
   - Housekeeping workflows require accountability: who cleaned room 302, when was it inspected, and why was it placed out of order? A single status column on `room` destroys operational history. Current status is retrieved with sub-millisecond efficiency using `DISTINCT ON (room_id) ... ORDER BY changed_at DESC` or via the `v_current_room_status` view.
   - *Alternative rejected:* Single mutable `status` column on `room`.

5. **Why JSONB was chosen for the audit log:**
   - The `audit_log` table captures changes across various business entities (primarily `booking` status transitions). Using `JSONB` for `old_values` and `new_values` provides schema-agnostic flexibility without needing a separate shadow table for every entity in the database.
   - *Alternative rejected:* Static column-per-table audit schemas or stringified unstructured text.

6. **Why status enums use CHECK constraints rather than PostgreSQL `CREATE TYPE`:**
   - Modifying a PostgreSQL enum (`ALTER TYPE ... ADD VALUE`) inside transactional migrations has historical restrictions and requires cluster-wide catalog alterations. `CHECK` constraints are table-specific, self-documenting in DDL, and allow straightforward schema adjustments.
   - *Alternative rejected:* PostgreSQL user-defined `ENUM` types.

7. **Why foreign keys use deliberate `ON DELETE` behaviours:**
   - `RESTRICT` is applied to `guest_id`, `hotel_id`, and `room_id` references to prevent accidental deletion of parent records that carry historical accounting or booking records.
   - `CASCADE` is used from `booking_room` to `check_in_out` and from `room` to `room_status_history` where dependent records have no standalone meaning.
   - `SET NULL` is used for `staff_id` references so that deactivating or removing an employee does not erase the record of who checked in a guest or inspected a room.
