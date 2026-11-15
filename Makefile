# Load environment variables (optional; copy .env.example to .env first)
-include .env
export

# --- Core targets ---

.PHONY: up down psql reset logs

up:
	docker compose up -d
	@echo "Waiting for PostgreSQL to become healthy..."
	@until docker compose exec postgres pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB) > /dev/null 2>&1; do sleep 1; done
	@echo "PostgreSQL is ready."

up-all:
	docker compose --profile nosql up -d
	@echo "Waiting for all services to become healthy..."
	@until docker compose exec postgres pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB) > /dev/null 2>&1; do sleep 1; done
	@echo "All services are ready."

down:
	docker compose --profile nosql down

psql:
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

reset:
	docker compose --profile nosql down -v
	@echo "All containers stopped and volumes removed."

logs:
	docker compose --profile nosql logs -f

# --- Portfolio targets ---

.PHONY: p1 p1-test p2 p2-seed p2-baseline p2-optimise p2-benchmark p3 p3-acid p3-isolation p3-concurrency p3-deadlock p4 p4-mongo p4-redis p5

p1:
	@echo "Portfolio 1: Applying schema to clean database..."
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 \
		< portfolio-1-database-design/sql/01_schema.sql
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 \
		< portfolio-1-database-design/sql/02_views_and_triggers.sql
	@echo "Portfolio 1: Schema applied. Run 'make p1-test' or 'make psql' to inspect."

p1-test:
	@echo "Portfolio 1: Running constraint test suite..."
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< portfolio-1-database-design/sql/03_constraint_tests.sql \
		> portfolio-1-database-design/evidence/constraint-tests.txt 2>&1
	@echo "Portfolio 1: Constraint tests complete. Evidence written to portfolio-1-database-design/evidence/constraint-tests.txt"

p2: p2-optimise p2-benchmark
	@echo "Portfolio 2: Complete optimisation and benchmarking workflow executed."

p2-seed:
	@echo "Portfolio 2: Seeding database with deterministic dataset..."
	.venv/bin/python3 portfolio-2-query-optimisation/scripts/seed.py

p2-baseline:
	@echo "Portfolio 2: Capturing baseline execution plans..."
	.venv/bin/python3 portfolio-2-query-optimisation/scripts/run_baseline.py

p2-optimise:
	@echo "Portfolio 2: Applying targeted indexes..."
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 \
		< portfolio-2-query-optimisation/sql/20_indexes.sql
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -c "ANALYZE;"
	@echo "Portfolio 2: Targeted indexes applied and ANALYZE executed."

p2-benchmark:
	@echo "Portfolio 2: Running query benchmarking suite (3-run median)..."
	.venv/bin/python3 portfolio-2-query-optimisation/scripts/benchmark.py

p3: p3-acid p3-isolation p3-concurrency p3-deadlock
	@echo "Portfolio 3: Transactions and Concurrency full suite complete."

p3-acid:
	@echo "Portfolio 3: Running ACID transaction and rollback demonstrations..."
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< portfolio-3-transactions-concurrency/sql/01_booking_transaction.sql \
		> portfolio-3-transactions-concurrency/evidence/01_booking_transaction_output.txt 2>&1
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< portfolio-3-transactions-concurrency/sql/02_rollback_scenarios.sql \
		> portfolio-3-transactions-concurrency/evidence/02_rollback_scenarios_output.txt 2>&1
	@echo "Portfolio 3: ACID evidence written to portfolio-3-transactions-concurrency/evidence/"

p3-isolation:
	@echo "Portfolio 3: Running multi-session isolation levels and anomaly harness..."
	.venv/bin/python3 portfolio-3-transactions-concurrency/scripts/run_two_sessions.py

p3-concurrency:
	@echo "Portfolio 3: Running 4-way double booking concurrency harness..."
	.venv/bin/python3 portfolio-3-transactions-concurrency/scripts/double_booking_demo.py

p3-deadlock:
	@echo "Portfolio 3: Running deadlock reproduction and resolution harness..."
	.venv/bin/python3 portfolio-3-transactions-concurrency/scripts/run_deadlock.py

p4: p4-mongo p4-redis
	@echo "Portfolio 4: NoSQL and Advanced Data Models full suite complete."

p4-mongo:
	@echo "Portfolio 4: Running MongoDB document ETL, CRUD, aggregations, and index benchmarks..."
	.venv/bin/python3 portfolio-4-nosql/scripts/mongo_operations.py

p5:
	@echo "Portfolio 5: Distributed and Cloud Database Exercise"
	@echo "TODO: implement"
