# Portfolio 2: Screenshots Capture Guide

For the final portfolio submission, capture the following terminal screenshots and save them in this folder (`portfolio-2-query-optimisation/screenshots/`).

| Screenshot File | Command to Run | What to Capture in Terminal |
|---|---|---|
| `p2-01-row-counts.png` | `cat portfolio-2-query-optimisation/evidence/row-counts.txt` | Terminal showing 500k bookings, 520k payments, 50k guests in PostgreSQL live tables. |
| `p2-02-baseline-plan-q06.png` | `head -n 50 portfolio-2-query-optimisation/evidence/baseline/q06.txt` | Terminal showing baseline plan for Q06 with SubPlan 2 and 32,341 ms execution time. |
| `p2-03-optimised-comparison.png` | `cat portfolio-2-query-optimisation/evidence/performance-summary.csv` | Terminal output showing the 10-query comparison table with speedups up to 313x. |
| `p2-04-index-sizes.png` | `head -n 45 portfolio-2-query-optimisation/evidence/table-index-sizes.txt` | Terminal output showing `pg_relation_size` and highlighting the 24 kB BRIN index. |

