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

.PHONY: p1 p1-test p2 p2-seed p3 p4 p5

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

p2:
	@echo "Portfolio 2: Query Processing and Optimisation"
	@echo "TODO: implement"

p2-seed:
	@echo "Portfolio 2: Seeding database with deterministic dataset..."
	.venv/bin/python3 portfolio-2-query-optimisation/scripts/seed.py

p3:
	@echo "Portfolio 3: Transactions and Concurrency"
	@echo "TODO: implement"

p4:
	@echo "Portfolio 4: NoSQL and Advanced Data Models"
	@echo "TODO: implement"

p5:
	@echo "Portfolio 5: Distributed and Cloud Database Exercise"
	@echo "TODO: implement"
