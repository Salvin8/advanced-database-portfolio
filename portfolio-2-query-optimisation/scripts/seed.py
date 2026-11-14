#!/usr/bin/env python3
"""
seed.py - High-Performance Deterministic Seed Data Generator for Savannah Crest Hotels
Portfolio 2: Query Processing and Optimisation

Generates realistic relational data respecting all business constraints:
- 6 Hotels across Nigerian cities
- 4 Room types, 600 rooms (100 per hotel)
- 60 Staff members across properties
- ~50,000 Guests (scaled by SCALE)
- ~500,000 Bookings with realistic seasonal distributions (December & holiday peaks)
- ~600,000 Payments (card, cash, bank transfer, mobile money, with some failed attempts)
- Check-in/out physical stay records
- Room status histories (housekeeping cycles)

Uses bulk COPY streams with in-memory TSV buffers for maximum throughput.
Fixed random seed (42) guarantees 100% deterministic reproducibility.
"""

import os
import sys
import io
import time
import random
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
import psycopg

# Load environment configuration
load_dotenv()

SCALE = float(os.getenv("SCALE", "1.0"))
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

# Fixed random seed for deterministic reproduction
SEED = 42
random.seed(SEED)

print(f"==================================================================")
print(f"Savannah Crest Hotels - Database Seeder")
print(f"Scale Factor: {SCALE}")
print(f"Target Database: {PG_DB} at {PG_HOST}:{PG_PORT} (User: {PG_USER})")
print(f"Seed: {SEED}")
print(f"==================================================================")

# ------------------------------------------------------------------------------
# Reference Data
# ------------------------------------------------------------------------------

HOTELS = [
    (1, "Savannah Crest Abuja", "Abuja", "10 Shehu Shagari Way, Maitama", "+2349010001001", "abuja@savannahcrest.ng", 5),
    (2, "Savannah Crest Victoria Island", "Lagos", "14 Adeola Odeku Street, Victoria Island", "+2349010002002", "vi.lagos@savannahcrest.ng", 5),
    (3, "Savannah Crest Port Harcourt", "Port Harcourt", "8 Tombia Extension, GRA Phase 2", "+2349010003003", "ph@savannahcrest.ng", 4),
    (4, "Savannah Crest Kano Royal", "Kano", "42 Bompai Road, Nassarawa", "+2349010004004", "kano@savannahcrest.ng", 4),
    (5, "Savannah Crest Independence Layout", "Enugu", "18 Presidential Road, Independence Layout", "+2349010005005", "enugu@savannahcrest.ng", 4),
    (6, "Savannah Crest Bodija", "Ibadan", "25 Oshuntokun Avenue, Old Bodija", "+2349010006006", "ibadan@savannahcrest.ng", 3),
]

ROOM_TYPES = [
    (1, "Standard Room", "Comfortable queen bed with work desk and high-speed Wi-Fi", 1, 2, 28000.00),
    (2, "Deluxe Room", "Spacious king bed with city view, lounge seating and espresso bar", 2, 2, 45000.00),
    (3, "Executive Suite", "One-bedroom suite with separate living room, kitchenette and lounge access", 2, 3, 85000.00),
    (4, "Presidential Suite", "Two-bedroom luxury suite with dining hall, private terrace and butler service", 2, 4, 180000.00),
]

# Realistic Nigerian first names and surnames
NIGERIAN_FIRST_NAMES = [
    "Chinedu", "Amaka", "Babatunde", "Oluwaseun", "Fatima", "Ibrahim", "Ngozi", "Emeka",
    "Amina", "Abubakar", "Folake", "Tunde", "Zainab", "Chidi", "Kehinde", "Taiwo",
    "Maryam", "Usman", "Chioma", "Kelechi", "Damilola", "Adeola", "Aliyu", "Hadiza",
    "Olumide", "Yetunde", "Musa", "Halima", "Obinna", "Blessing", "Victor", "Grace",
    "Samuel", "Emmanuel", "Patience", "Joy", "David", "Esther", "Peter", "Ruth",
    "Mohammed", "Bilikisu", "Jumoke", "Sani", "Umar", "Khadijah", "Chigozie", "Nneka"
]

NIGERIAN_LAST_NAMES = [
    "Okonkwo", "Adeyemi", "Balogun", "Ibrahim", "Danjuma", "Chukwu", "Bello", "Eze",
    "Okafor", "Adeleke", "Lawal", "Yusuf", "Oladipo", "Nwosu", "Ogundipe", "Shehu",
    "Ojo", "Aliyu", "Igwe", "Kalu", "Oyetola", "Abiola", "Suleiman", "Garba",
    "Obi", "Fashola", "Ogunleye", "Sanusi", "Adedipe", "Mohammed", "Onyekwere", "Mustapha",
    "Ajayi", "Akintola", "Uba", "Okoro", "Salami", "Gidado", "Adebayo", "Nnamani"
]

PAYMENT_METHODS = ["card", "bank_transfer", "mobile_money", "cash"]
PAYMENT_METHOD_WEIGHTS = [0.55, 0.25, 0.15, 0.05]

START_DATE = date(2020, 1, 1)
END_DATE = date(2026, 12, 31)
TOTAL_DAYS = (END_DATE - START_DATE).days


def bulk_copy(cursor, table_name, columns, data_generator, row_count, batch_size=50000):
    col_str = ", ".join(columns)
    copy_sql = f"COPY {table_name} ({col_str}) FROM STDIN WITH (FORMAT text, NULL '\\N')"
    
    total_written = 0
    buffer = io.StringIO()
    t0 = time.time()
    
    for row in data_generator:
        line = "\t".join("\\N" if val is None else str(val).replace("\t", " ").replace("\n", " ") for val in row)
        buffer.write(line + "\n")
        total_written += 1
        
        if total_written % batch_size == 0 or total_written == row_count:
            buffer.seek(0)
            with cursor.copy(copy_sql) as copy:
                copy.write(buffer.read())
            buffer = io.StringIO()
            elapsed = max(0.001, time.time() - t0)
            sys.stdout.write(f"\r  Loaded {total_written:,} / {row_count:,} rows into {table_name} ({total_written/elapsed:.0f} rows/s)...")
            sys.stdout.flush()
            
    print(f"\n  Finished {table_name}: {total_written:,} rows in {time.time()-t0:.2f}s.")
    return total_written


def main():
    conn_params = {
        "host": PG_HOST,
        "port": PG_PORT,
        "user": PG_USER,
        "password": PG_PASSWORD,
        "dbname": PG_DB,
    }
    
    print("Connecting to PostgreSQL...")
    conn = psycopg.connect(**conn_params, autocommit=False)
    cur = conn.cursor()
    
    # --------------------------------------------------------------------------
    # 1. Clean existing data
    # --------------------------------------------------------------------------
    print("Truncating existing tables to avoid duplicate key conflicts...")
    cur.execute("""
        TRUNCATE TABLE 
            audit_log, room_status_history, check_in_out, payment, 
            booking_room, booking, seasonal_rate, staff, room, guest, 
            room_type, hotel 
        RESTART IDENTITY CASCADE;
    """)
    conn.commit()
    
    # --------------------------------------------------------------------------
    # 2. Insert Hotels and Room Types
    # --------------------------------------------------------------------------
    print("Loading Hotels & Room Types...")
    cur.executemany("""
        INSERT INTO hotel (hotel_id, name, city, address, phone, email, star_rating)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, [(h[0], h[1], h[2], h[3], h[4], h[5], h[6]) for h in HOTELS])
    
    cur.executemany("""
        INSERT INTO room_type (room_type_id, name, description, base_capacity, max_capacity)
        VALUES (%s, %s, %s, %s, %s);
    """, [(rt[0], rt[1], rt[2], rt[3], rt[4]) for rt in ROOM_TYPES])
    conn.commit()
    
    # --------------------------------------------------------------------------
    # 3. Insert Rooms (100 per hotel = 600 rooms total)
    # --------------------------------------------------------------------------
    print("Generating Rooms (100 rooms across 5 floors per hotel = 600 rooms)...")
    rooms = []
    room_id = 1
    type_allocation = (
        [1] * 50 +  # Standard
        [2] * 30 +  # Deluxe
        [3] * 15 +  # Executive
        [4] * 5     # Presidential
    )
    
    for h in HOTELS:
        h_id = h[0]
        for idx, rt_id in enumerate(type_allocation):
            floor = (idx // 20) + 1
            num_in_floor = (idx % 20) + 1
            room_num = f"{floor}{num_in_floor:02d}"
            rooms.append((room_id, h_id, rt_id, room_num, floor, True))
            room_id += 1
            
    bulk_copy(cur, "room", ["room_id", "hotel_id", "room_type_id", "room_number", "floor", "is_active"],
              rooms, len(rooms))
    conn.commit()
    
    # --------------------------------------------------------------------------
    # 4. Insert Staff (~10 staff per hotel = 60 staff total)
    # --------------------------------------------------------------------------
    print("Generating Staff (60 staff members across 6 properties)...")
    staff_members = []
    staff_id = 1
    for h in HOTELS:
        h_id = h[0]
        hotel_roles = ["manager"] + ["receptionist"] * 4 + ["housekeeping"] * 3 + ["maintenance"] * 2
        for r in hotel_roles:
            fn = random.choice(NIGERIAN_FIRST_NAMES)
            ln = random.choice(NIGERIAN_LAST_NAMES)
            email = f"{fn.lower()}.{ln.lower()}.{staff_id}@savannahcrest.ng"
            hired = START_DATE - timedelta(days=random.randint(100, 1500))
            staff_members.append((staff_id, h_id, fn, ln, email, r, True, hired))
            staff_id += 1
            
    bulk_copy(cur, "staff", ["staff_id", "hotel_id", "first_name", "last_name", "email", "role", "is_active", "hired_date"],
              staff_members, len(staff_members))
    conn.commit()
    
    # --------------------------------------------------------------------------
    # 5. Insert Seasonal Rates
    # --------------------------------------------------------------------------
    print("Generating Seasonal Tariffs...")
    rates = []
    rate_id = 1
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    for yr in years:
        seasons = [
            ("New Year Peak", date(yr, 1, 1), date(yr, 1, 15), 1.35),
            ("Easter Break", date(yr, 4, 1), date(yr, 4, 20), 1.20),
            ("Summer Holiday", date(yr, 7, 1), date(yr, 8, 31), 1.15),
            ("Independence Holiday", date(yr, 9, 28), date(yr, 10, 5), 1.25),
            ("December Festive Peak", date(yr, 12, 1), date(yr, 12, 31), 1.45),
        ]
        for sname, sstart, send, multiplier in seasons:
            for h in HOTELS:
                for rt in ROOM_TYPES:
                    base_price = rt[5]
                    hotel_multiplier = 1.25 if h[0] in (1, 2) else 1.0
                    price = round(base_price * multiplier * hotel_multiplier, 2)
                    rates.append((rate_id, h[0], rt[0], f"{sname} {yr}", sstart, send, price))
                    rate_id += 1
                    
    bulk_copy(cur, "seasonal_rate", ["rate_id", "hotel_id", "room_type_id", "season_name", "start_date", "end_date", "price_per_night"],
              rates, len(rates))
    conn.commit()

    # --------------------------------------------------------------------------
    # 6. Insert Guests (~50,000 guests at SCALE=1.0)
    # --------------------------------------------------------------------------
    num_guests = int(50000 * SCALE)
    print(f"Generating {num_guests:,} Guests...")
    
    def guest_generator():
        for gid in range(1, num_guests + 1):
            fn = random.choice(NIGERIAN_FIRST_NAMES)
            ln = random.choice(NIGERIAN_LAST_NAMES)
            email = f"{fn.lower()}.{ln.lower()}{gid}@mail.ng"
            phone = f"+234{random.choice(['803', '802', '805', '810', '901'])}{random.randint(1000000, 9999999)}"
            id_type = random.choice(["passport", "national_id", "drivers_license"])
            id_num = f"NGR{random.randint(10000000, 99999999)}"
            nationality = "Nigerian" if random.random() < 0.90 else random.choice(["Ghanaian", "British", "American", "Kenyan", "South African"])
            dob = date(1960, 1, 1) + timedelta(days=random.randint(0, 15000))
            created = START_DATE + timedelta(days=random.randint(0, TOTAL_DAYS))
            yield (gid, fn, ln, email, phone, id_type, id_num, nationality, dob, created, created)

    bulk_copy(cur, "guest", 
              ["guest_id", "first_name", "last_name", "email", "phone", "id_type", "id_number", "nationality", "date_of_birth", "created_at", "updated_at"],
              guest_generator(), num_guests)
    conn.commit()

    # --------------------------------------------------------------------------
    # 7. Generate Bookings, Booking_Rooms, Payments, Check-in/out, Room Status
    # --------------------------------------------------------------------------
    target_bookings = int(500000 * SCALE)
    print(f"Generating approximately {target_bookings:,} Bookings with strict no-overlap timelines...")
    
    booking_id = 1
    booking_room_id = 1
    payment_id = 1
    checkin_record_id = 1
    status_id = 1

    base_prices = {}
    for h in HOTELS:
        for rt in ROOM_TYPES:
            h_mult = 1.25 if h[0] in (1, 2) else 1.0
            base_prices[(h[0], rt[0])] = round(rt[5] * h_mult, 2)

    t_start = time.time()
    
    b_buffer = []
    br_buffer = []
    p_buffer = []
    cio_buffer = []
    rsh_buffer = []

    b_count = 0
    batch_flush = 25000

    def flush_buffers():
        nonlocal b_buffer, br_buffer, p_buffer, cio_buffer, rsh_buffer
        
        if b_buffer:
            buf = io.StringIO("\n".join(b_buffer) + "\n")
            with cur.copy("COPY booking (booking_id, guest_id, hotel_id, booking_ref, status, booking_date, total_amount, notes, created_at, updated_at) FROM STDIN WITH (FORMAT text, NULL '\\N')") as cp:
                cp.write(buf.read())
            b_buffer = []

        if br_buffer:
            buf = io.StringIO("\n".join(br_buffer) + "\n")
            with cur.copy("COPY booking_room (booking_room_id, booking_id, room_id, check_in_date, check_out_date, rate_per_night, num_guests, status) FROM STDIN WITH (FORMAT text, NULL '\\N')") as cp:
                cp.write(buf.read())
            br_buffer = []

        if p_buffer:
            buf = io.StringIO("\n".join(p_buffer) + "\n")
            with cur.copy("COPY payment (payment_id, booking_id, amount, payment_method, payment_status, transaction_ref, payment_date, created_at) FROM STDIN WITH (FORMAT text, NULL '\\N')") as cp:
                cp.write(buf.read())
            p_buffer = []

        if cio_buffer:
            buf = io.StringIO("\n".join(cio_buffer) + "\n")
            with cur.copy("COPY check_in_out (record_id, booking_room_id, checked_in_by, checked_out_by, check_in_time, check_out_time) FROM STDIN WITH (FORMAT text, NULL '\\N')") as cp:
                cp.write(buf.read())
            cio_buffer = []

        if rsh_buffer:
            buf = io.StringIO("\n".join(rsh_buffer) + "\n")
            with cur.copy("COPY room_status_history (status_id, room_id, status, changed_by, changed_at, notes) FROM STDIN WITH (FORMAT text, NULL '\\N')") as cp:
                cp.write(buf.read())
            rsh_buffer = []

    vip_guests = list(range(1, max(2, int(num_guests * 0.15))))
    casual_guests = list(range(max(2, int(num_guests * 0.15)), num_guests + 1))

    # Room timelines state: room_id -> current_available_date
    room_timelines = {r[0]: START_DATE for r in rooms}
    
    # Initial clean housekeeping status per room
    for r in rooms:
        rsh_buffer.append(f"{status_id}\t{r[0]}\tclean\t\\N\t{START_DATE} 08:00:00+00\tInitial setup")
        status_id += 1

    # Bookings generation loop: distribute evenly across rooms until target_bookings is reached
    room_list = list(rooms)
    
    while b_count < target_bookings:
        for r in room_list:
            if b_count >= target_bookings:
                break
                
            r_id, h_id, rt_id, r_num, floor, is_act = r
            cur_date = room_timelines[r_id]
            rate = base_prices[(h_id, rt_id)]
            
            # If timeline has surpassed END_DATE, wrap around to earlier dates or break
            if cur_date >= END_DATE:
                continue
                
            # Seasonality: shorter idle gaps in Dec/April/August
            month = cur_date.month
            if month == 12 or month == 4:
                idle_days = 0 if random.random() < 0.70 else 1
            elif month in (7, 8):
                idle_days = 0 if random.random() < 0.50 else 1
            else:
                idle_days = random.choice([0, 1, 2])
                
            checkin = cur_date + timedelta(days=idle_days)
            if checkin >= END_DATE:
                room_timelines[r_id] = END_DATE
                continue
                
            nights = random.choices([1, 2, 3, 4, 5], weights=[0.30, 0.40, 0.18, 0.08, 0.04])[0]
            checkout = checkin + timedelta(days=nights)
            if checkout > END_DATE:
                checkout = END_DATE
                nights = (checkout - checkin).days
                if nights <= 0:
                    room_timelines[r_id] = END_DATE
                    continue

            guest_id = random.choice(vip_guests) if random.random() < 0.55 else random.choice(casual_guests)
            
            # Status distribution: 88% completed stays, 8% cancelled, 4% no-show
            rand_status = random.random()
            if rand_status < 0.08:
                b_status = "cancelled"
                br_status = "cancelled"
            elif rand_status < 0.12:
                b_status = "no_show"
                br_status = "reserved"
            else:
                b_status = "checked_out"
                br_status = "checked_out"
                
            b_ref = f"SC-{checkin.year}-{b_count+1:07d}"
            booking_date = datetime.combine(checkin - timedelta(days=random.randint(1, 25)), datetime.min.time())
            total_amt = round(rate * nights, 2)
            
            b_buffer.append(f"{booking_id}\t{guest_id}\t{h_id}\t{b_ref}\t{b_status}\t{booking_date}+00\t{total_amt}\t\\N\t{booking_date}+00\t{booking_date}+00")
            br_buffer.append(f"{booking_room_id}\t{booking_id}\t{r_id}\t{checkin}\t{checkout}\t{rate}\t1\t{br_status}")
            
            if b_status != "cancelled":
                pmethod = random.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS)[0]
                tx_ref = f"TXN-{b_ref}-1"
                p_buffer.append(f"{payment_id}\t{booking_id}\t{total_amt}\t{pmethod}\tcompleted\t{tx_ref}\t{booking_date}+00\t{booking_date}+00")
                payment_id += 1
                
                # Check-in/out record for completed stays
                if b_status == "checked_out":
                    cin_time = datetime.combine(checkin, datetime.min.time()) + timedelta(hours=14, minutes=random.randint(0, 180))
                    cout_time = datetime.combine(checkout, datetime.min.time()) + timedelta(hours=10, minutes=random.randint(0, 120))
                    staff_cin = (h_id - 1) * 10 + 2
                    staff_cout = (h_id - 1) * 10 + 3
                    cio_buffer.append(f"{checkin_record_id}\t{booking_room_id}\t{staff_cin}\t{staff_cout}\t{cin_time}+00\t{cout_time}+00")
                    checkin_record_id += 1
                    
                    # Housekeeping cycles
                    rsh_buffer.append(f"{status_id}\t{r_id}\tdirty\t\\N\t{cout_time}+00\tCheckout service")
                    status_id += 1
                    clean_time = cout_time + timedelta(hours=1, minutes=random.randint(15, 60))
                    staff_hk = (h_id - 1) * 10 + 6
                    rsh_buffer.append(f"{status_id}\t{r_id}\tclean\t{staff_hk}\t{clean_time}+00\tServiced")
                    status_id += 1
            else:
                if random.random() < 0.50:
                    tx_ref = f"TXN-{b_ref}-FAIL"
                    p_buffer.append(f"{payment_id}\t{booking_id}\t{total_amt}\tcard\tfailed\t{tx_ref}\t{booking_date}+00\t{booking_date}+00")
                    payment_id += 1
                else:
                    tx_ref1 = f"TXN-{b_ref}-P"
                    tx_ref2 = f"TXN-{b_ref}-R"
                    p_buffer.append(f"{payment_id}\t{booking_id}\t{total_amt}\tcard\tcompleted\t{tx_ref1}\t{booking_date}+00\t{booking_date}+00")
                    payment_id += 1
                    p_buffer.append(f"{payment_id}\t{booking_id}\t{total_amt}\tcard\trefunded\t{tx_ref2}\t{booking_date + timedelta(hours=2)}+00\t{booking_date + timedelta(hours=2)}+00")
                    payment_id += 1

            b_count += 1
            booking_id += 1
            booking_room_id += 1

            # Advance room timeline
            if br_status == "cancelled":
                room_timelines[r_id] = checkin
            else:
                room_timelines[r_id] = checkout

            if b_count % batch_flush == 0:
                flush_buffers()
                elapsed = max(0.001, time.time() - t_start)
                sys.stdout.write(f"\r  Generated {b_count:,} / {target_bookings:,} bookings ({b_count/elapsed:.0f} b/s)...")
                sys.stdout.flush()

    flush_buffers()
    conn.commit()
    print(f"\n  Bookings generation complete in {time.time()-t_start:.2f}s.")
    
    # --------------------------------------------------------------------------
    # 8. Reset Sequences and Run ANALYZE
    # --------------------------------------------------------------------------
    print("Synchronizing PostgreSQL sequences...")
    cur.execute("""
        SELECT setval('hotel_hotel_id_seq', (SELECT MAX(hotel_id) FROM hotel));
        SELECT setval('room_type_room_type_id_seq', (SELECT MAX(room_type_id) FROM room_type));
        SELECT setval('room_room_id_seq', (SELECT MAX(room_id) FROM room));
        SELECT setval('staff_staff_id_seq', (SELECT MAX(staff_id) FROM staff));
        SELECT setval('seasonal_rate_rate_id_seq', (SELECT MAX(rate_id) FROM seasonal_rate));
        SELECT setval('guest_guest_id_seq', (SELECT MAX(guest_id) FROM guest));
        SELECT setval('booking_booking_id_seq', (SELECT MAX(booking_id) FROM booking));
        SELECT setval('booking_room_booking_room_id_seq', (SELECT MAX(booking_room_id) FROM booking_room));
        SELECT setval('payment_payment_id_seq', (SELECT MAX(payment_id) FROM payment));
        SELECT setval('check_in_out_record_id_seq', (SELECT MAX(record_id) FROM check_in_out));
        SELECT setval('room_status_history_status_id_seq', (SELECT MAX(status_id) FROM room_status_history));
    """)
    conn.commit()

    print("Running ANALYZE across all tables for accurate query planner statistics...")
    t_analyze = time.time()
    cur.execute("ANALYZE;")
    conn.commit()
    print(f"ANALYZE completed in {time.time()-t_analyze:.2f}s.")

    # --------------------------------------------------------------------------
    # 9. Record Row Counts into Evidence
    # --------------------------------------------------------------------------
    evidence_path = "portfolio-2-query-optimisation/evidence/row-counts.txt"
    os.makedirs(os.path.dirname(evidence_path), exist_ok=True)
    
    cur.execute("""
        SELECT relname AS table_name, n_live_tup AS row_count
        FROM pg_stat_user_tables
        WHERE schemaname = 'public'
        ORDER BY n_live_tup DESC;
    """)
    counts = cur.fetchall()

    with open(evidence_path, "w") as f:
        f.write("=====================================================================\n")
        f.write("SAVANNAH CREST HOTELS - LIVE DATABASE ROW COUNTS (SCALE = {})\n".format(SCALE))
        f.write("Timestamp: {}\n".format(datetime.now().isoformat()))
        f.write("=====================================================================\n\n")
        f.write(f"{'Table Name':<25} | {'Row Count':>12}\n")
        f.write("-" * 42 + "\n")
        for tbl, cnt in counts:
            f.write(f"{tbl:<25} | {cnt:>12,}\n")
            print(f"  {tbl:<25} : {cnt:>10,}")
        f.write("-" * 42 + "\n")
        
    print(f"\nRow counts written to {evidence_path}")
    cur.close()
    conn.close()
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    main()
