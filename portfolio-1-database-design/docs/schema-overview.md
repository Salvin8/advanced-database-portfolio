# Schema Overview: Savannah Crest Hotels

## Table Summary

| # | Table | Purpose | Rows (at scale 1) |
|---|-------|---------|--------------------|
| 1 | hotel | Physical hotel properties in the chain | 6 |
| 2 | room_type | Room categories shared across hotels | 4 |
| 3 | room | Individual rooms within hotels | ~600 |
| 4 | guest | People who make bookings | ~50,000 |
| 5 | booking | Reservation headers | ~500,000 |
| 6 | booking_room | Room assignments within bookings (junction) | ~500,000+ |
| 7 | payment | Financial transactions | ~600,000 |
| 8 | seasonal_rate | Room pricing by season | ~100 |
| 9 | staff | Hotel employees | ~60 |
| 10 | check_in_out | Physical arrival/departure records | ~400,000 |
| 11 | room_status_history | Housekeeping status log | ~1,000,000+ |
| 12 | audit_log | Generic change log (booking status changes) | grows over time |

---

## Table-by-Table Detail

### hotel

- **Purpose:** Stores each hotel property in the Savannah Crest chain.
- **PK:** `hotel_id` (SERIAL)
- **Key constraints:** `star_rating` between 1 and 5; `name`, `city`, `address` are NOT NULL.
- **Notes:** Hotels are never deleted. The `updated_at` column is maintained by a trigger.

### room_type

- **Purpose:** Defines room categories (Standard, Deluxe, Suite, Executive) shared across all hotels.
- **PK:** `room_type_id` (SERIAL)
- **Key constraints:** `name` is UNIQUE; `max_capacity >= base_capacity`; both capacities must be > 0.
- **Notes:** Room types are global (not per-hotel), so all hotels offer the same categories.

### room

- **Purpose:** A specific, numbered room within a hotel.
- **PK:** `room_id` (SERIAL)
- **FKs:** `hotel_id` -> hotel (RESTRICT), `room_type_id` -> room_type (RESTRICT)
- **Key constraints:** `(hotel_id, room_number)` is UNIQUE (room numbers are unique within a hotel, not globally); `floor >= 0`.
- **Notes:** Rooms are deactivated (`is_active = false`) rather than deleted, preserving booking history.

### guest

- **Purpose:** People who book rooms, identified by email.
- **PK:** `guest_id` (SERIAL)
- **Key constraints:** `email` is UNIQUE (one account per guest); `id_type` is validated via CHECK (passport, national_id, drivers_license).
- **Notes:** `id_type` and `id_number` are nullable because guests may register online before providing identification.

### booking

- **Purpose:** A reservation made by a guest at a specific hotel. This is the header; room details are in `booking_room`.
- **PK:** `booking_id` (SERIAL)
- **FKs:** `guest_id` -> guest (RESTRICT), `hotel_id` -> hotel (RESTRICT)
- **Key constraints:** `booking_ref` is UNIQUE; `status` is CHECK-constrained to 6 valid values; `total_amount >= 0`.
- **Notes:** `total_amount` is a denormalised sum of (rate_per_night * nights) across all booking_rooms. This is acceptable because the price must not change retroactively (see modelling decisions). The `updated_at` column is maintained by a trigger; status changes are audit-logged.

### booking_room

- **Purpose:** Junction table assigning rooms to bookings with date ranges and snapshotted prices. This is the core of the reservation system.
- **PK:** `booking_room_id` (SERIAL)
- **FKs:** `booking_id` -> booking (CASCADE), `room_id` -> room (RESTRICT)
- **Key constraints:**
  - `check_out_date > check_in_date` (cannot check out before checking in)
  - `rate_per_night >= 0`, `num_guests > 0`
  - `status` CHECK-constrained to 4 values
  - **Exclusion constraint** (`excl_no_overlapping_booking`): prevents overlapping date ranges for the same room when status is 'reserved' or 'checked_in'. Uses `btree_gist` extension.
- **Generated column:** `stay` is a `daterange` computed from `check_in_date` and `check_out_date` with `[)` bounds (closed start, open end). Used by the exclusion constraint.
- **Notes:** This is the most constraint-heavy table in the schema. The exclusion constraint is the primary defence against double-bookings and works even under concurrent transactions.

### payment

- **Purpose:** Financial transactions against bookings.
- **PK:** `payment_id` (SERIAL)
- **FKs:** `booking_id` -> booking (RESTRICT)
- **Key constraints:** `amount >= 0`; `payment_method` CHECK-constrained (card, cash, bank_transfer, mobile_money); `payment_status` CHECK-constrained (pending, completed, failed, refunded).
- **Notes:** Refunds are recorded as separate rows with status 'refunded', not as negative amounts. ON DELETE RESTRICT preserves the financial audit trail.

### seasonal_rate

- **Purpose:** Nightly pricing for a room type at a hotel during a specific date range.
- **PK:** `rate_id` (SERIAL)
- **FKs:** `hotel_id` -> hotel (CASCADE), `room_type_id` -> room_type (CASCADE)
- **Key constraints:** `end_date > start_date`; `price_per_night > 0`.
- **Notes:** Multiple overlapping seasons are allowed (the application picks the best match). ON DELETE CASCADE because rates are meaningless without their hotel/room_type.

### staff

- **Purpose:** Hotel employees who process check-ins, housekeeping, etc.
- **PK:** `staff_id` (SERIAL)
- **FKs:** `hotel_id` -> hotel (RESTRICT)
- **Key constraints:** `email` UNIQUE; `role` CHECK-constrained (receptionist, manager, housekeeping, maintenance).
- **Notes:** Staff are deactivated (`is_active = false`) rather than deleted.

### check_in_out

- **Purpose:** Records the physical arrival and departure for a booked room.
- **PK:** `record_id` (SERIAL)
- **FKs:** `booking_room_id` -> booking_room (CASCADE, UNIQUE), `checked_in_by` -> staff (SET NULL), `checked_out_by` -> staff (SET NULL)
- **Key constraints:** `booking_room_id` is UNIQUE (1:1 with booking_room); `check_out_time > check_in_time` (or NULL if not yet checked out).
- **Notes:** Partial participation -- a no-show booking has no check_in_out record. SET NULL on staff FKs preserves the record if a staff member is removed.

### room_status_history

- **Purpose:** Tracks housekeeping and maintenance status changes over time.
- **PK:** `status_id` (SERIAL)
- **FKs:** `room_id` -> room (CASCADE), `changed_by` -> staff (SET NULL)
- **Key constraints:** `status` CHECK-constrained (clean, dirty, inspected, out_of_order, maintenance).
- **Notes:** This is a log table, not a current-state table. The current status is the most recent entry per room, queryable via the `v_current_room_status` view (uses `DISTINCT ON`).

### audit_log

- **Purpose:** Generic change log capturing before/after values for auditable operations.
- **PK:** `log_id` (BIGSERIAL)
- **Key constraints:** `action` CHECK-constrained (INSERT, UPDATE, DELETE); no FKs to source tables.
- **Notes:** JSONB columns (`old_values`, `new_values`) store change data without schema coupling. BIGSERIAL because audit tables grow fast. Currently populated by the booking status change trigger; can be extended to other tables.

---

## Views

| View | Purpose |
|------|---------|
| `v_room_availability` | Active rooms with availability flag for today |
| `v_daily_occupancy` | Per-hotel occupancy statistics for today |
| `v_current_room_status` | Latest housekeeping status per active room |
| `v_guest_booking_summary` | Guest booking history with payment totals |

## Triggers

| Trigger | Table | Purpose |
|---------|-------|---------|
| `trg_hotel_updated_at` | hotel | Sets `updated_at` on UPDATE |
| `trg_guest_updated_at` | guest | Sets `updated_at` on UPDATE |
| `trg_booking_updated_at` | booking | Sets `updated_at` on UPDATE |
| `trg_audit_booking_status` | booking | Logs status changes to `audit_log` |

## Extensions

| Extension | Purpose |
|-----------|---------|
| `btree_gist` | Enables integer equality operator in GiST indexes, required for the exclusion constraint on `booking_room` |

