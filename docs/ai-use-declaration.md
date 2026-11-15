# AI Use Declaration

**MIT 8103 Advanced Database Systems**  
**Student:** Tobias Salvin
**Coursework:** Savannah Crest Hotels Management System

---

## I) AI Tool(s) Used

- **Antigravity (Google DeepMind Agentic Assistant / Gemini 3.8 & Claude 4.6)** via the Antigravity IDE.

---

## II) What It Was Used For

1. **Scaffolding & Boilerplate Generation:** Initial directory hierarchies, Docker Compose templates (`docker-compose.yml`), Makefile automation rules, and reference documentation skeletons.
2. **Deterministic Data Generation:** Developing the high-performance bulk COPY generator (`seed.py`) with realistic Nigerian demographics, seasonal pricing multipliers, and strict date sequences.
3. **Drafting SQL Scripts & Harnesses:** Assisting with query syntax, PL/pgSQL stored procedure templates, and Python multi-threaded concurrency scripts (`psycopg`, `pymongo`, `redis`).
4. **Drafting Initial Documentation:** Generating initial markdown outlines, comparison matrices, and theoretical overviews for CAP and PACELC theorems.
5. **Code Debugging & Diagnostics:** Explaining PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` execution plans, GiST index internals, and serialization conflict reason codes.

---

## III) How I Reviewed, Corrected, Tested, and Verified the Output

As the student submitting this work, I took full personal responsibility for reviewing, understanding, executing, and modifying every artifact:

1. **Line-by-Line Code Review:**  
   Every generated SQL migration, stored procedure, Python harness, and JSON schema was examined line-by-line prior to execution. I ensured that all constraints adhered strictly to the Savannah Crest Hotels domain requirements (e.g. Nigerian pricing in Naira, Maitama/Victoria Island property naming, and closed-open interval bounds).

2. **Hands-On Debugging & Real Problem Resolution:**  
   When the automated scripts encountered real database engine errors, I diagnosed the root cause and directed the fix:
   - **Data Exception on Generated Column:** Identified that PostgreSQL evaluates the generated stored `stay` daterange column before the `CHECK (check_out_date > check_in_date)` constraint, modifying the PL/pgSQL exception block to handle `check_violation OR data_exception`.
   - **Stored Procedure String Truncation:** Diagnosed `ERROR: value too long for type character varying(50)` on `sp_make_reservation`'s output parameter, altering `p_status` to `TEXT`.
   - **Serializable Write Skew Thread Synchronization:** Discovered that a single `threading.Barrier` in Python failed to force concurrent overlapping read snapshots under SSI, and designed a dual-barrier synchronization protocol with event triggers to reliably reproduce `SQLSTATE 40001` pivot aborts.
   - **Saga Orchestrator Re-runs:** Solved collision errors on demo bookings during repeated testing by adding an idempotent purge step at script startup.

3. **Live Container Execution & Zero Fabricated Data:**  
   Every evidence file in this repository (`evidence/*.txt`, `evidence/*.csv`) was captured directly from live terminal runs against running Docker containers (`savannah-crest-pg`, `savannah-crest-mongo`, `savannah-crest-redis`). No benchmark metrics, EXPLAIN plans, or row counts were simulated or manually fabricated.

4. **Independent Conceptual Mastery:**  
   I can independently explain and defend every design decision, query rewrite, isolation anomaly, indexing trade-off, and distributed transaction pattern during the viva voce examination without reference to the AI tool.
