# Portfolio 3: Screenshots Capture Guide

For the final portfolio submission, capture the following terminal screenshots and save them in this folder (`portfolio-3-transactions-concurrency/screenshots/`).

| Screenshot File | Command to Run | What to Capture in Terminal |
|---|---|---|
| `p3-01-deadlock-session-b.png` | `python3 portfolio-3-transactions-concurrency/scripts/run_deadlock.py` | Terminal showing Phase 1 where PostgreSQL outputs `ERROR: deadlock detected (SQLSTATE 40P01)` with process lock wait details. |
| `p3-02-double-booking-table.png` | `cat portfolio-3-transactions-concurrency/evidence/double-booking-results.md` | Terminal displaying the comparative results table showing 20 double bookings in Run A vs exactly 1 in Runs B, C, D. |
| `p3-03-isolation-levels-output.png` | `cat portfolio-3-transactions-concurrency/evidence/isolation_levels_output.txt` | Terminal showing Experiment 4 where SSI catches write skew (`Reason code: Canceled on identification as a pivot`) and initiates the retry loop. |

