# Requirements Analysis: Savannah Crest Hotels

## Business Rules

| ID | Rule |
|----|------|
| R1 | A room cannot have two overlapping active bookings (enforced at the database level). |
| R2 | Each hotel operates in exactly one city; the chain has 6 hotels across Nigerian cities. |
| R3 | Every room belongs to exactly one hotel and has exactly one room type. |
| R4 | Room numbers are unique within a hotel (not globally). |
| R5 | A booking is made by exactly one guest but may cover one or more rooms (e.g., a family booking two rooms). |
| R6 | Each booked room has a snapshotted nightly rate recorded at booking time; this rate does not change if seasonal pricing is later updated. |
| R7 | Room rates vary by hotel, room type, and season (date range). A default rate exists when no seasonal rate applies. |
| R8 | A payment must have a non-negative amount. A booking may have multiple payments (e.g., deposit then balance, or a refund). |
| R9 | Check-out date/time must be strictly after check-in date/time. |
| R10 | A booking progresses through defined statuses: pending, confirmed, checked_in, checked_out, cancelled, no_show. |
| R11 | Check-in and check-out are recorded separately from the booking itself (the booking is a reservation; the stay is the physical event). |
| R12 | Every room has a housekeeping status (clean, dirty, inspected, out_of_order, maintenance) tracked over time. |
| R13 | Staff members are assigned to a specific hotel. Staff roles include: receptionist, manager, housekeeping, maintenance. |
| R14 | All changes to booking status must be audit-logged with before/after values and a timestamp. |
| R15 | Guest email addresses are unique across the system (one account per guest). |
| R16 | Payments can be made via card, cash, bank transfer, or mobile money (reflecting Nigerian payment methods). |

## Entities and Relationships

### Core Entities

| Entity | Description |
|--------|-------------|
| **hotel** | A physical hotel property in the chain. |
| **room_type** | A category of room (Standard, Deluxe, Suite, Executive). Shared across hotels. |
| **room** | A specific room within a hotel. |
| **guest** | A person who books rooms. |
| **booking** | A reservation made by a guest at a specific hotel. |
| **booking_room** | Junction: assigns one or more rooms to a booking with date ranges and snapshotted rates. |
| **payment** | A financial transaction against a booking. |
| **seasonal_rate** | Pricing for a room type at a hotel during a date range. |
| **staff** | An employee at a hotel. |
| **check_in_out** | The physical check-in and check-out record for a booked room. |
| **room_status_history** | A log of housekeeping/maintenance status changes for a room. |
| **audit_log** | A generic change log for auditable tables (especially booking status changes). |

### Relationships and Cardinalities

| Relationship | Cardinality | Participation |
|-------------|-------------|---------------|
| hotel HAS rooms | 1:M | Total on room side (every room belongs to a hotel) |
| hotel EMPLOYS staff | 1:M | Total on staff side |
| hotel HAS seasonal_rates | 1:M | Partial (rates are optional per period) |
| room_type CATEGORISES rooms | 1:M | Total on room side |
| room_type HAS seasonal_rates | 1:M | Partial |
| guest MAKES bookings | 1:M | Partial (a guest may exist without bookings) |
| booking CONTAINS booking_rooms | 1:M | Total (a booking must have at least one room) |
| booking HAS payments | 1:M | Partial (a pending booking may not yet have payment) |
| room IS ASSIGNED via booking_room | 1:M | Partial (not all rooms are booked at all times) |
| booking_room HAS check_in_out | 1:1 | Partial (only if the guest actually arrives) |
| staff PROCESSES check_in_out | 1:M | Partial |
| room HAS room_status_history | 1:M | Partial |
| staff UPDATES room_status_history | 1:M | Partial |

## Core Queries the System Must Answer

| # | Query | Primary Tables |
|---|-------|---------------|
| Q1 | **Availability search:** which rooms at hotel X are free for date range [A, B]? | room, booking_room |
| Q2 | **Make a reservation:** insert a booking with room assignment, respecting no-overlap. | booking, booking_room, payment |
| Q3 | **Guest booking history:** all past and future bookings for a given guest, with status and payment totals. | guest, booking, booking_room, payment |
| Q4 | **Daily occupancy report:** for a given date, how many rooms are occupied vs total at each hotel? | hotel, room, booking_room |
| Q5 | **Revenue report:** total revenue by hotel, by month, for a given year. | hotel, booking, payment |
| Q6 | **Modify/cancel a booking:** update booking status and handle payment refund if applicable. | booking, booking_room, payment |
| Q7 | **Check-in a guest:** record actual arrival, update booking_room status, update room housekeeping status. | booking_room, check_in_out, room_status_history |
| Q8 | **Check-out a guest:** record departure, calculate final charges, update room status to dirty. | booking_room, check_in_out, room_status_history, payment |
| Q9 | **Seasonal rate lookup:** what is the nightly rate for room type Y at hotel X for date D? | seasonal_rate, room_type |
| Q10 | **Housekeeping dashboard:** all rooms at hotel X with current status, ordered by floor. | room, room_status_history |

