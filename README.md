# MIT 8103 Advanced Database Systems -- Individual Portfolio

## Case Study: Savannah Crest Hotels

**Organisation (simulated):** Savannah Crest Hotels, a chain of 6 mid-range hotels across Nigerian cities (Abuja, Lagos, Port Harcourt, Kano, Enugu, Ibadan).

- **Nature of the system:** Central reservation and property-management database supporting online booking, front-desk operations and reporting.
- **Users of the database:** Guests (via web/mobile booking), front-desk staff, revenue/finance managers, hotel managers, and analysts.
- **Major data stored:** Hotels, room types, rooms, guests, bookings (stay date ranges), payments, check-in/check-out records, rates/seasonal pricing, staff, housekeeping status, guest reviews, activity/audit logs.
- **Key operations:** Search availability by hotel and date range, reserve a room (without double-booking), modify/cancel a booking, process payment (including failed payment rollback), check-in/check-out, update room availability, daily occupancy and revenue reports, and guest history retrieval.

**Target data volume:** ~6 hotels, ~600 rooms, ~50,000 guests, ~500,000 bookings, ~600,000 payments (configurable via a `SCALE` variable).

---

## Portfolio Status

| Portfolio | Title | Status |
|-----------|-------|--------|
| P1 | Database Design and Modelling | Completed |
| P2 | Query Processing and Optimisation | Completed |
| P3 | Transactions and Concurrency | Completed |
| P4 | NoSQL and Advanced Data Models | Completed |
| P5 | Distributed and Cloud Database Exercise | Not started |
| Final | Documentation and Reflection | Not started |

---

## Repository Map

```
advanced-database-portfolio/
├── portfolio-1-database-design/      P1: ER diagram, schema, normalisation
├── portfolio-2-query-optimisation/   P2: Queries, indexes, performance analysis
├── portfolio-3-transactions-concurrency/  P3: ACID, isolation, concurrency control
├── portfolio-4-nosql/                P4: MongoDB + Redis implementations
├── portfolio-5-distributed-cloud/    P5: Replication, partitioning, cloud design
├── docs/                            Cross-cutting documentation
│   ├── references.md
│   ├── ai-use-declaration.md
│   ├── reflection-template.md
│   └── final-documentation.md
├── docker-compose.yml               Base services (PostgreSQL; MongoDB/Redis via profile)
├── Makefile                         Build and run targets
└── README.md                        This file
```

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Python 3.11+ (for seeding scripts and concurrency demos)
- `make` (GNU Make)
- `psql` (optional; available inside the Docker container)

## Quick Start

```bash
# 1. Copy environment file
cp .env.example .env

# 2. Start PostgreSQL
make up

# 3. Connect to PostgreSQL
make psql

# 4. Start all services (including MongoDB and Redis)
make up-all

# 5. Tear down everything (including volumes)
make reset
```

## Running Individual Portfolios

```bash
make p1    # Portfolio 1: Database Design
make p2    # Portfolio 2: Query Optimisation
make p3    # Portfolio 3: Transactions and Concurrency
make p4    # Portfolio 4: NoSQL
make p5    # Portfolio 5: Distributed and Cloud
```

---

## Documentation

- [References](docs/references.md)
- [AI Use Declaration](docs/ai-use-declaration.md)
- [Reflection Template](docs/reflection-template.md)
- [Final Documentation](docs/final-documentation.md)

---

## Technology Stack

| Component | Version | Purpose |
|-----------|---------|---------|
| PostgreSQL | 16.4 | Relational core, transactions, partitioning, replication |
| MongoDB | 7.0 | Document model (Portfolio 4) |
| Redis | 7.4 | Key-value store (Portfolio 4) |
| Docker + Compose | v2 | Containerised environment |
| Python | 3.11 | Seeding, concurrency demos, test harnesses |
| Mermaid | -- | ER and architecture diagrams |
