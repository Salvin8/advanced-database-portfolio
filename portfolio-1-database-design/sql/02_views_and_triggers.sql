-- =============================================================================
-- 02_views_and_triggers.sql
-- Savannah Crest Hotels: Views and Triggers
-- Portfolio 1: Database Design and Modelling
--
-- Depends on: 01_schema.sql (tables must exist)
-- =============================================================================

-- =============================================================================
-- VIEWS
-- =============================================================================

-- v_room_availability: Shows every active room and whether it is available today.
-- To check availability for a different date range, query booking_room directly
-- with a daterange overlap condition (see Portfolio 2 queries).
--
-- Usage:
--   SELECT * FROM v_room_availability WHERE hotel_id = 1 AND is_available_today;
CREATE OR REPLACE VIEW v_room_availability AS
SELECT
    r.room_id,
    r.room_number,
    r.floor,
    h.hotel_id,
    h.name        AS hotel_name,
    h.city,
    rt.name       AS room_type,
    rt.base_capacity,
    rt.max_capacity,
    -- A room is available today if no active booking_room covers CURRENT_DATE.
    CASE
        WHEN br.booking_room_id IS NOT NULL THEN false
        ELSE true
    END AS is_available_today
FROM room r
JOIN hotel h      ON r.hotel_id     = h.hotel_id
JOIN room_type rt ON r.room_type_id = rt.room_type_id
LEFT JOIN booking_room br
    ON  r.room_id = br.room_id
    AND br.status IN ('reserved', 'checked_in')
    AND br.stay @> CURRENT_DATE       -- daterange contains today
WHERE r.is_active = true;

COMMENT ON VIEW v_room_availability IS
    'Active rooms with a boolean flag indicating availability for today. '
    'Filter by hotel_id and/or room_type. For arbitrary date ranges, query '
    'booking_room with a daterange overlap (&&) condition instead.';


-- v_daily_occupancy: Occupancy statistics per hotel for today.
-- Shows total active rooms, how many are occupied, and the occupancy percentage.
--
-- Usage:
--   SELECT * FROM v_daily_occupancy ORDER BY occupancy_pct DESC;
CREATE OR REPLACE VIEW v_daily_occupancy AS
SELECT
    h.hotel_id,
    h.name    AS hotel_name,
    h.city,
    COUNT(r.room_id)                AS total_rooms,
    COUNT(br.booking_room_id)       AS occupied_rooms,
    COUNT(r.room_id) - COUNT(br.booking_room_id) AS available_rooms,
    ROUND(
        COUNT(br.booking_room_id)::NUMERIC / NULLIF(COUNT(r.room_id), 0) * 100,
        1
    ) AS occupancy_pct
FROM hotel h
JOIN room r ON h.hotel_id = r.hotel_id AND r.is_active = true
LEFT JOIN booking_room br
    ON  r.room_id = br.room_id
    AND br.status IN ('reserved', 'checked_in')
    AND br.stay @> CURRENT_DATE
GROUP BY h.hotel_id, h.name, h.city;

COMMENT ON VIEW v_daily_occupancy IS
    'Per-hotel occupancy for today: total rooms, occupied, available, and '
    'occupancy percentage. Uses only active rooms and active bookings.';


-- v_current_room_status: The most recent housekeeping status for each active room.
-- Uses DISTINCT ON to pick the latest entry from room_status_history.
-- Rooms with no status history default to ''clean''.
--
-- Usage:
--   SELECT * FROM v_current_room_status WHERE hotel_id = 1 ORDER BY floor, room_number;
CREATE OR REPLACE VIEW v_current_room_status AS
SELECT DISTINCT ON (r.room_id)
    r.room_id,
    r.room_number,
    r.floor,
    h.hotel_id,
    h.name             AS hotel_name,
    rt.name            AS room_type,
    COALESCE(rsh.status, 'clean') AS housekeeping_status,
    rsh.changed_at     AS status_since,
    CASE
        WHEN s.staff_id IS NOT NULL
        THEN s.first_name || ' ' || s.last_name
        ELSE NULL
    END AS changed_by_name
FROM room r
JOIN hotel h      ON r.hotel_id     = h.hotel_id
JOIN room_type rt ON r.room_type_id = rt.room_type_id
LEFT JOIN room_status_history rsh ON r.room_id = rsh.room_id
LEFT JOIN staff s ON rsh.changed_by = s.staff_id
WHERE r.is_active = true
ORDER BY r.room_id, rsh.changed_at DESC NULLS LAST;

COMMENT ON VIEW v_current_room_status IS
    'Current housekeeping status of each active room. The latest entry from '
    'room_status_history wins; rooms with no history show as clean.';


-- v_guest_booking_summary: Guest booking history with payment totals.
-- Useful for guest history lookups and loyalty analysis.
--
-- Usage:
--   SELECT * FROM v_guest_booking_summary WHERE guest_id = 42;
CREATE OR REPLACE VIEW v_guest_booking_summary AS
SELECT
    g.guest_id,
    g.first_name,
    g.last_name,
    g.email,
    b.booking_id,
    b.booking_ref,
    b.status       AS booking_status,
    b.booking_date,
    h.name         AS hotel_name,
    h.city,
    b.total_amount,
    COALESCE(p.paid, 0)    AS total_paid,
    b.total_amount - COALESCE(p.paid, 0) AS balance_due,
    br_agg.room_count,
    br_agg.earliest_checkin,
    br_agg.latest_checkout
FROM guest g
JOIN booking b ON g.guest_id = b.guest_id
JOIN hotel h   ON b.hotel_id = h.hotel_id
LEFT JOIN (
    SELECT booking_id,
           SUM(amount) FILTER (WHERE payment_status = 'completed') AS paid
    FROM payment
    GROUP BY booking_id
) p ON b.booking_id = p.booking_id
LEFT JOIN (
    SELECT booking_id,
           COUNT(*)              AS room_count,
           MIN(check_in_date)    AS earliest_checkin,
           MAX(check_out_date)   AS latest_checkout
    FROM booking_room
    WHERE status != 'cancelled'
    GROUP BY booking_id
) br_agg ON b.booking_id = br_agg.booking_id;

COMMENT ON VIEW v_guest_booking_summary IS
    'Guest booking history with payment totals, balance due, room count, '
    'and stay date range. One row per booking.';


-- =============================================================================
-- TRIGGER FUNCTIONS
-- =============================================================================

-- fn_set_updated_at: Automatically sets updated_at to now() on UPDATE.
-- Applied to tables with an updated_at column.
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_set_updated_at IS
    'Sets the updated_at column to the current timestamp on every UPDATE. '
    'Attached as a BEFORE UPDATE trigger to tables with an updated_at column.';


-- fn_audit_booking_status: Logs booking status changes to audit_log.
-- Fires only when the status column actually changes (not on every update).
CREATE OR REPLACE FUNCTION fn_audit_booking_status()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO audit_log (table_name, record_id, action, old_values, new_values, changed_by)
        VALUES (
            'booking',
            NEW.booking_id,
            'UPDATE',
            jsonb_build_object(
                'status',     OLD.status,
                'total_amount', OLD.total_amount,
                'updated_at', OLD.updated_at
            ),
            jsonb_build_object(
                'status',     NEW.status,
                'total_amount', NEW.total_amount,
                'updated_at', NEW.updated_at
            ),
            current_user
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_audit_booking_status IS
    'Captures booking status transitions in audit_log. Only fires when the '
    'status column changes, recording old and new values as JSONB.';


-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- updated_at maintenance triggers
CREATE TRIGGER trg_hotel_updated_at
    BEFORE UPDATE ON hotel
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_guest_updated_at
    BEFORE UPDATE ON guest
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_booking_updated_at
    BEFORE UPDATE ON booking
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- Audit trigger: logs every booking status change
CREATE TRIGGER trg_audit_booking_status
    AFTER UPDATE ON booking
    FOR EACH ROW
    EXECUTE FUNCTION fn_audit_booking_status();

