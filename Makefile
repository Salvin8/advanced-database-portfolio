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

.PHONY: p1 p2 p2-seed p3 p4 p5

p1:
	@echo "Portfolio 1: Database Design and Modelling"
	@echo "TODO: implement"

p2:
	@echo "Portfolio 2: Query Processing and Optimisation"
	@echo "TODO: implement"

p2-seed:
	@echo "Portfolio 2: Seed data"
	@echo "TODO: implement"

p3:
	@echo "Portfolio 3: Transactions and Concurrency"
	@echo "TODO: implement"

p4:
	@echo "Portfolio 4: NoSQL and Advanced Data Models"
	@echo "TODO: implement"

p5:
	@echo "Portfolio 5: Distributed and Cloud Database Exercise"
	@echo "TODO: implement"
