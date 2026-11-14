# Portfolio 1: Screenshots Capture Guide

For the final portfolio submission, capture the following terminal screenshots and save them in this folder (`portfolio-1-database-design/screenshots/`).

| Screenshot File | Command to Run | What to Capture in Terminal |
|---|---|---|
| `p1-01-schema-tables.png` | `docker compose exec postgres psql -U hotel_admin -d savannah_crest -c "\dt+"` | Terminal showing all 12 relation tables with their size and persistence. |
| `p1-02-exclusion-constraint.png` | `docker compose exec postgres psql -U hotel_admin -d savannah_crest -c "\d+ booking_room"` | Terminal showing `booking_room` structure, especially the generated `stay` column and the `excl_no_overlapping_booking` exclusion constraint. |
| `p1-03-constraint-violation-tests.png` | `docker compose exec -T postgres psql -U hotel_admin -d savannah_crest < portfolio-1-database-design/sql/03_constraint_tests.sql` | Terminal output showing PART 2 where PostgreSQL rejects overlapping reservations and negative payments with notices. |

