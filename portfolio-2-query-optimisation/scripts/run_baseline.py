#!/usr/bin/env python3
"""
run_baseline.py - Execute Query Suite under Baseline (P1 indexes only)
Portfolio 2: Query Processing and Optimisation

Executes each of the 10 queries:
  1. Captures EXPLAIN (ANALYZE, BUFFERS) -> evidence/baseline/qNN.txt
  2. Captures sample query results      -> evidence/results/qNN.txt
"""

import os
import re
import psycopg
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

BASELINE_DIR = "portfolio-2-query-optimisation/evidence/baseline"
RESULTS_DIR = "portfolio-2-query-optimisation/evidence/results"
SQL_FILE = "portfolio-2-query-optimisation/sql/10_queries.sql"

os.makedirs(BASELINE_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


def parse_queries(sql_content):
    """Parses 10_queries.sql into individual queries with their comments."""
    # Split by section headers '-- Q01:', '-- Q02:', etc.
    pattern = r"(-- =+\n-- (Q\d+):[^\n]+\n-- =+[\s\S]*?)(?=-- =+\n-- Q\d+:|$)"
    matches = re.findall(pattern, sql_content)
    
    queries = []
    for header_and_body, q_id in matches:
        # Separate comments from SQL statement
        lines = header_and_body.strip().split("\n")
        comment_lines = []
        sql_lines = []
        in_sql = False
        for line in lines:
            if line.startswith("--") and not in_sql:
                comment_lines.append(line)
            else:
                in_sql = True
                sql_lines.append(line)
        sql_text = "\n".join(sql_lines).strip()
        if sql_text.endswith(";"):
            sql_text = sql_text[:-1].strip()
        queries.append((q_id, "\n".join(comment_lines), sql_text))
    return queries


def format_table(cursor, max_rows=25):
    """Formats query results as an ASCII table."""
    desc = cursor.description
    if not desc:
        return "No rows returned."
    
    headers = [col.name for col in desc]
    rows = cursor.fetchmany(max_rows)
    
    if not rows:
        return "No rows returned."
        
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(val) if val is not None else "NULL"))
            
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    
    lines = [header_line, sep_line]
    for row in rows:
        lines.append(" | ".join((str(val) if val is not None else "NULL").ljust(col_widths[i]) for i, val in enumerate(row)))
        
    if len(rows) == max_rows:
        lines.append(f"\n(... truncated to first {max_rows} rows ...)")
    return "\n".join(lines)


def main():
    print("==================================================================")
    print("Portfolio 2: Running Baseline Query Execution Plans")
    print(f"Connecting to {PG_DB} at {PG_HOST}:{PG_PORT}...")
    print("==================================================================")
    
    with open(SQL_FILE, "r") as f:
        content = f.read()
        
    queries = parse_queries(content)
    print(f"Found {len(queries)} queries in {SQL_FILE}.\n")
    
    conn = psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB
    )
    
    for q_id, comments, sql_text in queries:
        num_str = q_id.lower() # q01, q02, etc.
        baseline_file = os.path.join(BASELINE_DIR, f"{num_str}.txt")
        result_file = os.path.join(RESULTS_DIR, f"{num_str}.txt")
        
        print(f"Executing {q_id}...")
        
        # 1. Capture EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)
        cur = conn.cursor()
        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) {sql_text};"
        try:
            cur.execute(explain_sql)
            plan_lines = [r[0] for r in cur.fetchall()]
            
            with open(baseline_file, "w") as f:
                f.write(f"=====================================================================\n")
                f.write(f"BASELINE EXECUTION PLAN: {q_id}\n")
                f.write(f"Environment: PostgreSQL 16 (P1 Base Schema, Baseline Indexes Only)\n")
                f.write(f"=====================================================================\n\n")
                f.write(f"{comments}\n\n")
                f.write(f"--- QUERY SQL ---\n{sql_text};\n\n")
                f.write(f"--- EXPLAIN (ANALYZE, BUFFERS) ---\n")
                f.write("\n".join(plan_lines) + "\n")
            print(f"  -> Plan saved: {baseline_file}")
        except Exception as e:
            print(f"  ERROR running plan for {q_id}: {e}")
            conn.rollback()
            continue

        # 2. Capture actual query output sample
        try:
            cur.execute(sql_text)
            formatted_table = format_table(cur, max_rows=25)
            
            with open(result_file, "w") as f:
                f.write(f"=====================================================================\n")
                f.write(f"SAMPLE QUERY RESULTS: {q_id}\n")
                f.write(f"=====================================================================\n\n")
                f.write(f"{comments}\n\n")
                f.write(formatted_table + "\n")
            print(f"  -> Results saved: {result_file}")
        except Exception as e:
            print(f"  ERROR running query for {q_id}: {e}")
            conn.rollback()
            continue
            
        cur.close()

    conn.close()
    print("\nAll baseline queries executed and evidence captured successfully.")


if __name__ == "__main__":
    main()

