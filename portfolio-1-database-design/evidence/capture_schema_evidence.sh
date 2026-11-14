#!/bin/bash
# capture_schema_evidence.sh
# Captures \d+ output for key tables into evidence/ files.
# Run after: make up && make p1
#
# Usage: bash portfolio-1-database-design/evidence/capture_schema_evidence.sh

set -euo pipefail

EVIDENCE_DIR="portfolio-1-database-design/evidence"
PSQL="docker compose exec -T postgres psql -U ${POSTGRES_USER:-hotel_admin} -d ${POSTGRES_DB:-savannah_crest}"

echo "Capturing schema evidence..."

# List all tables
$PSQL -c "\dt+" > "$EVIDENCE_DIR/table-list.txt"
echo "  -> table-list.txt"

# Detailed description of each key table
for table in hotel room_type room guest booking booking_room payment seasonal_rate staff check_in_out room_status_history audit_log; do
    $PSQL -c "\d+ $table" > "$EVIDENCE_DIR/desc-${table}.txt"
    echo "  -> desc-${table}.txt"
done

# List all views
$PSQL -c "\dv+" > "$EVIDENCE_DIR/view-list.txt"
echo "  -> view-list.txt"

# List all indexes
$PSQL -c "\di+" > "$EVIDENCE_DIR/index-list.txt"
echo "  -> index-list.txt"

# List all constraints (useful for viva)
$PSQL -c "
SELECT conrelid::regclass AS table_name,
       conname,
       contype,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
ORDER BY conrelid::regclass::text, contype, conname;
" > "$EVIDENCE_DIR/all-constraints.txt"
echo "  -> all-constraints.txt"

# List triggers
$PSQL -c "
SELECT trigger_name, event_object_table, event_manipulation, action_timing
FROM information_schema.triggers
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;
" > "$EVIDENCE_DIR/trigger-list.txt"
echo "  -> trigger-list.txt"

echo "Done. Evidence saved to $EVIDENCE_DIR/"

