-- =============================================================================
-- 01_schema.sql
-- Savannah Crest Hotels: Full PostgreSQL 16 Schema
-- Portfolio 1: Database Design and Modelling
--
-- This script is idempotent: it drops existing objects before recreating them.
-- Run with: cat sql/01_schema.sql | docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB
-- =============================================================================

-- Drop existing objects in reverse dependency order
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS room_status_history CASCADE;
DROP TABLE IF EXISTS check_in_out CASCADE;
DROP TABLE IF EXISTS payment CASCADE;
DROP TABLE IF EXISTS booking_room CASCADE;
DROP TABLE IF EXISTS booking CASCADE;
DROP TABLE IF EXISTS seasonal_rate CASCADE;
DROP TABLE IF EXISTS staff CASCADE;
DROP TABLE IF EXISTS room CASCADE;
DROP TABLE IF EXISTS guest CASCADE;
DROP TABLE IF EXISTS room_type CASCADE;
DROP TABLE IF EXISTS hotel CASCADE;

-- Required extension: provides integer equality operator for GiST indexes,
-- enabling the exclusion constraint that prevents overlapping bookings.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- =============================================================================
-- HOTEL AND ROOM MANAGEMENT
-- =============================================================================

-- hotel: A physical property in the Savannah Crest chain.
-- One row per hotel (6 hotels across Nigerian cities).
CREATE TABLE hotel (
    hotel_id    SERIAL        PRIMARY KEY,
    name        VARCHAR(100)  NOT NULL,
    city        VARCHAR(50)   NOT NULL,
    address     TEXT          NOT NULL,
    phone       VARCHAR(20),
    email       VARCHAR(100),
    star_rating SMALLINT      NOT NULL CHECK (star_rating BETWEEN 1 AND 5),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
-- ON DELETE: not referenced with CASCADE from anywhere critical.
-- Hotels should never be deleted; decommission by removing rooms instead.

-- room_type: Categories of rooms shared across all hotels.
-- Examples: Standard, Deluxe, Suite, Executive.
CREATE TABLE room_type (
    room_type_id  SERIAL      PRIMARY KEY,
    name          VARCHAR(50) NOT NULL UNIQUE,
    description   TEXT,
    base_capacity SMALLINT    NOT NULL CHECK (base_capacity > 0),
    max_capacity  SMALLINT    NOT NULL CHECK (max_capacity > 0),
    CONSTRAINT chk_capacity_range CHECK (max_capacity >= base_capacity)
);

-- room: A specific, numbered room within a hotel.
-- ~100 rooms per hotel, ~600 total.
CREATE TABLE room (
    room_id      SERIAL      PRIMARY KEY,
    hotel_id     INT         NOT NULL REFERENCES hotel(hotel_id) ON DELETE RESTRICT,
    room_type_id INT         NOT NULL REFERENCES room_type(room_type_id) ON DELETE RESTRICT,
    room_number  VARCHAR(10) NOT NULL,
    floor        SMALLINT    NOT NULL CHECK (floor >= 0),
    is_active    BOOLEAN     NOT NULL DEFAULT true,
    CONSTRAINT uq_room_number_per_hotel UNIQUE (hotel_id, room_number)
);
-- ON DELETE RESTRICT: cannot delete a hotel or room_type that has rooms.
-- Rooms are deactivated (is_active = false) rather than deleted, preserving
-- booking history.

-- =============================================================================
-- GUESTS
-- =============================================================================

-- guest: A person who makes bookings. ~50,000 at scale 1.
CREATE TABLE guest (
    guest_id      SERIAL       PRIMARY KEY,
    first_name    VARCHAR(50)  NOT NULL,
    last_name     VARCHAR(50)  NOT NULL,
    email         VARCHAR(100) NOT NULL UNIQUE,
    phone         VARCHAR(20),
    id_type       VARCHAR(20)  CHECK (id_type IN ('passport', 'national_id', 'drivers_license')),
    id_number     VARCHAR(50),
    nationality   VARCHAR(50),
    date_of_birth DATE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- email UNIQUE: one account per guest across the chain.
-- id_type uses CHECK rather than CREATE TYPE for easier extension (see
-- modelling decision #8 in er-diagram.md).

-- =============================================================================
-- BOOKINGS AND ROOM ASSIGNMENTS
-- =============================================================================

-- booking: A reservation made by a guest at a specific hotel.
-- ~500,000 at scale 1. This is the header; room details are in booking_room.
CREATE TABLE booking (
    booking_id   SERIAL         PRIMARY KEY,
    guest_id     INT            NOT NULL REFERENCES guest(guest_id) ON DELETE RESTRICT,
    hotel_id     INT            NOT NULL REFERENCES hotel(hotel_id) ON DELETE RESTRICT,
    booking_ref  VARCHAR(20)    NOT NULL UNIQUE,
    status       VARCHAR(20)    NOT NULL DEFAULT 'pending'
                 CHECK (status IN (
                     'pending',      -- just created, awaiting confirmation/payment
                     'confirmed',    -- payment received or guaranteed
                     'checked_in',   -- guest has arrived
                     'checked_out',  -- guest has departed
                     'cancelled',    -- guest or hotel cancelled
                     'no_show'       -- guest did not arrive
                 )),
    booking_date TIMESTAMPTZ    NOT NULL DEFAULT now(),
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    notes        TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now()
);
-- ON DELETE RESTRICT on guest_id: cannot delete a guest who has booking history.
-- booking_ref: human-readable reference, e.g. "SC-2024-000001".
-- total_amount: denormalised sum of (rate_per_night * nights) across booking_rooms.
-- Acceptable denormalisation because recalculating on every query is wasteful,
-- and the value must not change if rates are later updated (see er-diagram.md #2).

-- booking_room: Junction table assigning rooms to bookings with date ranges.
-- Each row = one room for one stay period within one booking.
-- This is where the exclusion constraint lives.
CREATE TABLE booking_room (
    booking_room_id SERIAL         PRIMARY KEY,
    booking_id      INT            NOT NULL REFERENCES booking(booking_id) ON DELETE CASCADE,
    room_id         INT            NOT NULL REFERENCES room(room_id) ON DELETE RESTRICT,
    check_in_date   DATE           NOT NULL,
    check_out_date  DATE           NOT NULL,

    -- Computed daterange for the exclusion constraint.
    -- '[)' = closed start, open end: check-in day is included, check-out day is not.
    -- A guest checking out on Jan 3 does not block another checking in on Jan 3.
    stay            daterange      GENERATED ALWAYS AS (
                        daterange(check_in_date, check_out_date, '[)')
                    ) STORED,

    rate_per_night  NUMERIC(12, 2) NOT NULL CHECK (rate_per_night >= 0),
    num_guests      SMALLINT       NOT NULL DEFAULT 1 CHECK (num_guests > 0),
    status          VARCHAR(20)    NOT NULL DEFAULT 'reserved'
                    CHECK (status IN (
                        'reserved',     -- room is booked but guest hasn't arrived
                        'checked_in',   -- guest is currently staying
                        'checked_out',  -- guest has departed
                        'cancelled'     -- this room assignment was cancelled
                    )),

    -- Date validation: check-out must be after check-in.
    CONSTRAINT chk_checkout_after_checkin CHECK (check_out_date > check_in_date),

    -- EXCLUSION CONSTRAINT: prevents overlapping active bookings for the same room.
    -- Only rows with status 'reserved' or 'checked_in' participate.
    -- Cancelled and checked_out bookings do not block future reservations.
    -- Requires btree_gist extension for the integer = operator in a GiST index.
    CONSTRAINT excl_no_overlapping_booking EXCLUDE USING gist (
        room_id WITH =,
        stay    WITH &&
    ) WHERE (status IN ('reserved', 'checked_in'))
);
-- ON DELETE CASCADE on booking_id: room assignments are deleted if the booking
-- is deleted (in practice, bookings are cancelled, not deleted).
-- ON DELETE RESTRICT on room_id: cannot delete a room with booking history.

-- =============================================================================
-- PAYMENTS
-- =============================================================================

-- payment: Financial transactions against bookings.
-- A booking may have multiple payments (deposit + balance, or partial refunds).
-- ~600,000 at scale 1.
CREATE TABLE payment (
    payment_id     SERIAL         PRIMARY KEY,
    booking_id     INT            NOT NULL REFERENCES booking(booking_id) ON DELETE RESTRICT,
    amount         NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    payment_method VARCHAR(20)    NOT NULL
                   CHECK (payment_method IN (
                       'card',           -- credit/debit card
                       'cash',           -- cash at front desk
                       'bank_transfer',  -- direct bank transfer
                       'mobile_money'    -- mobile money (common in Nigeria)
                   )),
    payment_status VARCHAR(20)    NOT NULL DEFAULT 'pending'
                   CHECK (payment_status IN ('pending', 'completed', 'failed', 'refunded')),
    transaction_ref VARCHAR(50),
    payment_date   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ    NOT NULL DEFAULT now()
);
-- ON DELETE RESTRICT on booking_id: cannot delete a booking that has payment
-- records. Financial audit trail must be preserved.
-- amount >= 0: refunds are recorded as separate rows with status 'refunded',
-- not as negative amounts.

-- =============================================================================
-- PRICING
-- =============================================================================

-- seasonal_rate: Nightly rate for a room type at a hotel during a date range.
-- Supports seasonal pricing (peak season, holidays, off-peak).
CREATE TABLE seasonal_rate (
    rate_id         SERIAL         PRIMARY KEY,
    hotel_id        INT            NOT NULL REFERENCES hotel(hotel_id) ON DELETE CASCADE,
    room_type_id    INT            NOT NULL REFERENCES room_type(room_type_id) ON DELETE CASCADE,
    season_name     VARCHAR(50)    NOT NULL,
    start_date      DATE           NOT NULL,
    end_date        DATE           NOT NULL,
    price_per_night NUMERIC(12, 2) NOT NULL CHECK (price_per_night > 0),
    CONSTRAINT chk_season_dates CHECK (end_date > start_date)
);
-- ON DELETE CASCADE: if a hotel or room type is removed, its pricing is
-- no longer meaningful. In practice, neither is deleted.

-- =============================================================================
-- STAFF
-- =============================================================================

-- staff: Employees at each hotel.
CREATE TABLE staff (
    staff_id   SERIAL       PRIMARY KEY,
    hotel_id   INT          NOT NULL REFERENCES hotel(hotel_id) ON DELETE RESTRICT,
    first_name VARCHAR(50)  NOT NULL,
    last_name  VARCHAR(50)  NOT NULL,
    email      VARCHAR(100) NOT NULL UNIQUE,
    role       VARCHAR(20)  NOT NULL
               CHECK (role IN ('receptionist', 'manager', 'housekeeping', 'maintenance')),
    is_active  BOOLEAN      NOT NULL DEFAULT true,
    hired_date DATE         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- ON DELETE RESTRICT on hotel_id: cannot delete a hotel with staff records.
-- Staff are deactivated (is_active = false) rather than deleted.

-- =============================================================================
-- STAY RECORDS AND HOUSEKEEPING
-- =============================================================================

-- check_in_out: Records the physical arrival and departure for a booked room.
-- Optional (partial participation): a no-show booking has no check_in_out row.
CREATE TABLE check_in_out (
    record_id       SERIAL      PRIMARY KEY,
    booking_room_id INT         NOT NULL UNIQUE
                    REFERENCES booking_room(booking_room_id) ON DELETE CASCADE,
    checked_in_by   INT         REFERENCES staff(staff_id) ON DELETE SET NULL,
    checked_out_by  INT         REFERENCES staff(staff_id) ON DELETE SET NULL,
    check_in_time   TIMESTAMPTZ NOT NULL DEFAULT now(),
    check_out_time  TIMESTAMPTZ,
    CONSTRAINT chk_checkout_after_checkin_time
        CHECK (check_out_time IS NULL OR check_out_time > check_in_time)
);
-- UNIQUE on booking_room_id: enforces 1:1 (one stay record per room assignment).
-- ON DELETE CASCADE on booking_room_id: stay record is meaningless without the
-- room assignment.
-- ON DELETE SET NULL on staff FKs: preserve the stay record even if the staff
-- member who processed it is removed. In practice, staff are deactivated, not deleted.

-- room_status_history: Tracks housekeeping and maintenance status changes per room.
-- The current status is the most recent entry (queryable via DISTINCT ON).
CREATE TABLE room_status_history (
    status_id  SERIAL      PRIMARY KEY,
    room_id    INT         NOT NULL REFERENCES room(room_id) ON DELETE CASCADE,
    status     VARCHAR(20) NOT NULL
               CHECK (status IN (
                   'clean',        -- ready for guest
                   'dirty',        -- after checkout, needs cleaning
                   'inspected',    -- cleaned and verified by supervisor
                   'out_of_order', -- unusable (e.g., broken fixture)
                   'maintenance'   -- undergoing scheduled maintenance
               )),
    changed_by INT         REFERENCES staff(staff_id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes      TEXT
);
-- ON DELETE CASCADE on room_id: status history for a deleted room is discarded.
-- ON DELETE SET NULL on changed_by: preserve the record even if the staff member
-- is removed.

-- =============================================================================
-- AUDIT LOG
-- =============================================================================

-- audit_log: Generic change log for auditable operations.
-- Primarily captures booking status changes via trigger (see 02_views_and_triggers.sql).
-- Uses JSONB for flexibility: stores before/after values without schema coupling.
CREATE TABLE audit_log (
    log_id     BIGSERIAL    PRIMARY KEY,
    table_name VARCHAR(50)  NOT NULL,
    record_id  INT          NOT NULL,
    action     VARCHAR(10)  NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    old_values JSONB,
    new_values JSONB,
    changed_by VARCHAR(100),
    changed_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- BIGSERIAL: audit tables grow fast; INT would overflow sooner.
-- No foreign keys to source tables: the audit log is append-only and must
-- survive even if the source record is deleted.

-- =============================================================================
-- INDEXES
-- =============================================================================
-- These are the minimum indexes needed for FK lookups and basic query patterns.
-- Additional performance indexes are added in Portfolio 2 after baseline analysis.

-- FK indexes (PostgreSQL does not auto-create indexes on FK columns)
CREATE INDEX idx_room_hotel        ON room (hotel_id);
CREATE INDEX idx_room_room_type    ON room (room_type_id);
CREATE INDEX idx_booking_guest     ON booking (guest_id);
CREATE INDEX idx_booking_hotel     ON booking (hotel_id);
CREATE INDEX idx_booking_room_fk_booking ON booking_room (booking_id);
CREATE INDEX idx_booking_room_fk_room    ON booking_room (room_id);
CREATE INDEX idx_payment_booking   ON payment (booking_id);
CREATE INDEX idx_seasonal_rate_hotel_type ON seasonal_rate (hotel_id, room_type_id);
CREATE INDEX idx_staff_hotel       ON staff (hotel_id);
CREATE INDEX idx_check_in_out_booking_room ON check_in_out (booking_room_id);
CREATE INDEX idx_room_status_room  ON room_status_history (room_id, changed_at DESC);

-- Audit log lookup indexes
CREATE INDEX idx_audit_log_table_record ON audit_log (table_name, record_id);
CREATE INDEX idx_audit_log_time         ON audit_log (changed_at);

-- Booking status for filtered queries
CREATE INDEX idx_booking_status ON booking (status);

-- Booking room date range for availability searches
CREATE INDEX idx_booking_room_dates ON booking_room (check_in_date, check_out_date);

