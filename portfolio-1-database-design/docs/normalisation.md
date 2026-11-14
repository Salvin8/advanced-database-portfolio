# Normalisation Analysis: Savannah Crest Hotels

This document presents a rigorous normalisation analysis for the Savannah Crest hotel reservation system. It begins with a flat, un-normalised spreadsheet representation of a hotel booking log, identifies all functional dependencies, traces the systematic decomposition through 1NF, 2NF, 3NF, and Boyce-Codd Normal Form (BCNF), and concludes with an explicit discussion of intentional denormalisation decisions.

---

## 1. The Un-normalised Relation (UNF)

In legacy property management workflows or manual front-desk ledgers, reservations are frequently recorded in a single flat structure (e.g., a spreadsheet). Below is a representative un-normalised relation:

`UNF_HOTEL_BOOKING_SHEET`:
```text
(
    booking_ref,
    booking_date,
    guest_email,
    guest_name,
    guest_phone,
    hotel_name,
    hotel_city,
    hotel_address,
    hotel_phone,
    hotel_star_rating,
    rooms_booked: [
        {
            room_number,
            floor,
            room_type_name,
            base_capacity,
            max_capacity,
            check_in_date,
            check_out_date,
            rate_per_night,
            room_status
        }
    ],
    payments: [
        {
            payment_date,
            amount,
            payment_method,
            payment_status,
            transaction_ref
        }
    ],
    total_amount,
    booking_status
)
```

### Anomalies Present in UNF

1. **Insertion Anomaly:**
   - A new room cannot be catalogued in the system until a guest books it.
   - A newly negotiated seasonal rate or new hotel property cannot be recorded without an artificial dummy reservation.
2. **Deletion Anomaly:**
   - If a booking record is cancelled and deleted, all associated guest history, room catalogue data, and historical payment logs are deleted alongside it.
3. **Update (Modification) Anomaly:**
   - If a hotel changes its primary contact telephone number or address, every historical booking row involving that hotel must be updated. Any missed row results in inconsistent data.
   - If a guest updates their mobile number, disparate records will disagree.

---

## 2. Functional Dependencies (FDs)

Let us define the attributes formally:

- `booking_ref` $\rightarrow$ `booking_date`, `booking_status`, `total_amount`, `guest_email`, `hotel_name`
- `guest_email` $\rightarrow$ `guest_name`, `guest_phone`, `nationality`, `id_type`, `id_number`
- `hotel_name` $\rightarrow$ `hotel_city`, `hotel_address`, `hotel_phone`, `hotel_star_rating`
- `(hotel_name, room_number)` $\rightarrow$ `floor`, `room_type_name`, `is_active`
- `room_type_name` $\rightarrow$ `base_capacity`, `max_capacity`
- `(booking_ref, room_number)` $\rightarrow$ `check_in_date`, `check_out_date`, `rate_per_night`, `room_status`
- `transaction_ref` $\rightarrow$ `booking_ref`, `amount`, `payment_method`, `payment_status`, `payment_date`

---

## 3. Step-by-Step Normalisation

### Step 1: First Normal Form (1NF)
**Definition:** A relation is in 1NF if and only if all attribute domains are atomic (no repeating groups, multi-valued attributes, or nested relations), and a unique primary key is identified.

**Transformation:**
Flatten the repeating groups (`rooms_booked` array and `payments` array) by creating individual rows for each combination. 

The composite candidate key for this flattened relation becomes:
`{booking_ref, room_number, transaction_ref}`.

**Resulting 1NF Relation:**
```text
FLAT_BOOKING(
    booking_ref, room_number, transaction_ref,
    booking_date, booking_status, total_amount,
    guest_email, guest_name, guest_phone,
    hotel_name, hotel_city, hotel_address, hotel_phone, hotel_star_rating,
    floor, room_type_name, base_capacity, max_capacity,
    check_in_date, check_out_date, rate_per_night, room_status,
    payment_date, amount, payment_method, payment_status
)
```

**Evaluation:**
- Satisfies atomicity.
- Suffer severe data redundancy because hotel details and guest details repeat across every room and payment row.

---

### Step 2: Second Normal Form (2NF)
**Definition:** A relation is in 2NF if it is in 1NF and every non-prime attribute is **fully functionally dependent** on the primary key (no partial functional dependencies where an attribute depends on only a subset of a composite candidate key).

**Violations in 1NF:**
In `FLAT_BOOKING`, the composite key is `{booking_ref, room_number, transaction_ref}`:
- `booking_date`, `booking_status`, `guest_email`, `hotel_name` depend strictly on `{booking_ref}`.
- `check_in_date`, `check_out_date`, `rate_per_night` depend strictly on `{booking_ref, room_number}`.
- `floor`, `room_type_name` depend on `{hotel_name, room_number}`, not the transaction or booking.
- `payment_date`, `amount`, `payment_method` depend strictly on `{transaction_ref}`.

**Decomposition to 2NF:**
We decompose into four distinct relations to eliminate partial dependencies:

1. `BOOKING_HEADER`:
   - Attributes: `(booking_ref, booking_date, booking_status, total_amount, guest_email, hotel_name)`
   - Primary Key: `booking_ref`
2. `BOOKING_ROOM_ASSIGNMENT`:
   - Attributes: `(booking_ref, room_number, check_in_date, check_out_date, rate_per_night, room_status)`
   - Primary Key: `{booking_ref, room_number}`
3. `ROOM_CATALOGUE`:
   - Attributes: `(hotel_name, room_number, floor, room_type_name, base_capacity, max_capacity)`
   - Primary Key: `{hotel_name, room_number}`
4. `PAYMENT_RECORD`:
   - Attributes: `(transaction_ref, booking_ref, payment_date, amount, payment_method, payment_status)`
   - Primary Key: `transaction_ref`

---

### Step 3: Third Normal Form (3NF)
**Definition:** A relation is in 3NF if it is in 2NF and **no non-prime attribute is transitively dependent** on any candidate key (no $X \rightarrow Y$ where $Y \rightarrow Z$ and $X$ is the PK).

**Violations in 2NF:**
1. In `BOOKING_HEADER`:
   - `booking_ref` $\rightarrow$ `guest_email` $\rightarrow$ `(guest_name, guest_phone)`.
   - `booking_ref` $\rightarrow$ `hotel_name` $\rightarrow$ `(hotel_city, hotel_address, hotel_phone, hotel_star_rating)`.
2. In `ROOM_CATALOGUE`:
   - `{hotel_name, room_number}` $\rightarrow$ `room_type_name` $\rightarrow$ `(base_capacity, max_capacity)`.

**Decomposition to 3NF:**
We extract the transitive dependencies into their own independent relations:

1. `GUEST`:
   - `(guest_id, first_name, last_name, email, phone, ...)` — PK: `guest_id` (email candidate key).
2. `HOTEL`:
   - `(hotel_id, name, city, address, phone, star_rating)` — PK: `hotel_id`.
3. `ROOM_TYPE`:
   - `(room_type_id, name, base_capacity, max_capacity)` — PK: `room_type_id`.
4. `ROOM`:
   - `(room_id, hotel_id, room_type_id, room_number, floor, is_active)` — PK: `room_id`; FKs: `hotel_id`, `room_type_id`.
5. `BOOKING`:
   - `(booking_id, guest_id, hotel_id, booking_ref, status, total_amount, ...)` — PK: `booking_id`; FKs: `guest_id`, `hotel_id`.
6. `BOOKING_ROOM`:
   - `(booking_room_id, booking_id, room_id, check_in_date, check_out_date, stay, rate_per_night, status)` — PK: `booking_room_id`; FKs: `booking_id`, `room_id`.
7. `PAYMENT`:
   - `(payment_id, booking_id, amount, payment_method, payment_status, transaction_ref, ...)` — PK: `payment_id`; FK: `booking_id`.

---

### Step 4: Boyce-Codd Normal Form (BCNF)
**Definition:** A relation is in BCNF if and only if for every non-trivial functional dependency $X \rightarrow Y$, $X$ is a **superkey**.

**Evaluation of our 3NF schema:**
- In `guest`: The candidate keys are `guest_id` and `email`. All FDs have either `guest_id` or `email` as determinant. Both are superkeys $\Rightarrow$ **BCNF satisfied**.
- In `room`: Candidate keys are `room_id` and `{hotel_id, room_number}`. All FDs originate from these keys $\Rightarrow$ **BCNF satisfied**.
- In `booking_room`: Candidate key is `booking_room_id`. The room-date exclusion rule ($room\_id, stay \rightarrow \emptyset$ on overlap) is a multi-attribute domain integrity rule enforced via GiST rather than an FD violation $\Rightarrow$ **BCNF satisfied**.
- In `room_type`, `hotel`, `payment`, `seasonal_rate`: Every determinant is a primary key or unique candidate key $\Rightarrow$ **BCNF satisfied**.

Thus, the core relational schema achieves full 3NF and BCNF compliance.

---

## 4. Intentional Denormalisation and Justifications

While normalisation minimizes update anomalies and eliminates redundancy, pure academic normalisation can impair operational performance or violate historical accounting integrity. The following intentional trade-offs are applied in Savannah Crest Hotels:

### 1. `booking_room.rate_per_night` (Historical Price Snapshot)
- **Theoretical concern:** One could argue `rate_per_night` is transitively dependent on `(hotel_id, room_type_id, date)` via the `seasonal_rate` table and should be looked up on the fly.
- **Why denormalised:** **Financial and legal immutability.** If the management increases holiday rates next month, existing historical bookings must **never** change their agreed price retroactively. A snapshot preserves the contract signed at reservation time.

### 2. `booking.total_amount` (Pre-computed Aggregation)
- **Theoretical concern:** `total_amount` is derivable from $\sum (\text{rate\_per\_night} \times \text{nights})$ across all `booking_room` rows linked to the booking.
- **Why denormalised:** High-frequency read queries (guest booking history, invoice generation, front-desk checkout screens, finance summaries) would otherwise require an aggregate join across `booking_room` on every query. The field is validated by application logic and audit triggers.

### 3. Generated Column `booking_room.stay` (`daterange`)
- **Theoretical concern:** The `stay` column redundantly stores `daterange(check_in_date, check_out_date, '[)')`, duplicating the start and end dates.
- **Why denormalised/stored:** Required for PostgreSQL's `btree_gist` index to execute index-assisted overlap detection (`&&`) inside the `EXCLUDE USING gist` constraint. Marking it `GENERATED ALWAYS AS (...) STORED` ensures PostgreSQL maintains it deterministically without risking drift between the dates and the range.

---

## Summary of Normalized Schema Architecture

```
[HOTEL] 1 --- M [ROOM] 1 --- M [BOOKING_ROOM] M --- 1 [BOOKING] M --- 1 [GUEST]
   |               |                   |                    |
   M               M                   1                    M
[STAFF]     [ROOM_TYPE]           [CHECK_IN_OUT]       [PAYMENT]
```

This normalized topology guarantees zero data anomalies for operational updates while preserving legal and performance characteristics through surgical denormalisations.

