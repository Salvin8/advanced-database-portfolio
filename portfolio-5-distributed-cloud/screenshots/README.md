# Portfolio 5 Screenshots Catalog

This directory contains visual artifacts and screenshots demonstrating distributed database architectures, native declarative partitioning, partition pruning, and Saga orchestration in PostgreSQL 16.

> [!NOTE]
> Per project configuration, live interactive screenshots are deferred/stashed for final post-project capture after all coursework code implementation is verified. All underlying empirical evidence is captured directly from live database runs in `portfolio-5-distributed-cloud/evidence/`.

---

## Screenshot Inventory & Pending Captures

| Screenshot ID | Filename | Description / Target Screen | Source Command / Tool | Status |
| :--- | :--- | :--- | :--- | :---: |
| **SS-5.1** | `01_declarative_partitioning_counts.png` | Terminal query output showing the 6 physical geographic partitions (`booking_part_abuja` through `ibadan`) and ~83,300 rows per partition | `docker compose exec -T postgres psql -U hotel_admin -d savannah_crest -c "SELECT ..."` | *Pending post-project* |
| **SS-5.2** | `02_partition_pruning_explain_analyze.png` | Terminal EXPLAIN ANALYZE output proving static partition pruning (scanning only `booking_part_lagos` and pruning 5 partitions) | `portfolio-5-distributed-cloud/sql/01_partitioning.sql` | *Pending post-project* |
| **SS-5.3** | `03_saga_orchestrator_happy_path.png` | Terminal execution of `saga_orchestrator.py` showing Scenario 1 forward execution across Inventory, Payment, and Notification services | `portfolio-5-distributed-cloud/scripts/saga_orchestrator.py` | *Pending post-project* |
| **SS-5.4** | `04_saga_compensating_transaction.png` | Terminal output showing Scenario 2: simulated card decline triggering `release_hold_compensating_action` and PostgreSQL audit verification | `portfolio-5-distributed-cloud/scripts/saga_orchestrator.py` | *Pending post-project* |
| **SS-5.5** | `05_distributed_infrastructure_blueprint.png` | VS Code / terminal inspection of the multi-node distributed cluster blueprint with primary-standby streaming and Redis Sentinel | `portfolio-5-distributed-cloud/infra/distributed_cluster_example.yml` | *Pending post-project* |

---

## Instructions for Capturing Screenshots (Post-Project)

1. **Partitioning & Pruning:**
   ```bash
   make p5-partitioning
   docker compose exec postgres psql -U hotel_admin -d savannah_crest -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM booking_partitioned WHERE hotel_id = 2;"
   ```
2. **Saga Orchestrator Execution:**
   ```bash
   make p5-saga
   ```
3. **Infrastructure Blueprint:**
   ```bash
   cat portfolio-5-distributed-cloud/infra/distributed_cluster_example.yml
   ```

