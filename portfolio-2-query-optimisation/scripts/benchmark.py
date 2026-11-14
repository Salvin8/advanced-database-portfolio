#!/usr/bin/env python3
"""
benchmark.py - Automated Query Performance Benchmarking & Evidence Generator
Portfolio 2: Query Processing and Optimisation

Executes:
  1. Re-runs all 10 queries with EXPLAIN (ANALYZE, BUFFERS) -> evidence/optimised/qNN.txt
  2. Runs each query 3 times to measure median execution time (before vs after)
  3. Generates evidence/performance-summary.csv
  4. Measures relation and index storage footprints -> evidence/table-index-sizes.txt
  5. Measures insert write throughput overhead to document indexing trade-offs
"""

import os
import re
import csv
import time
import statistics
import psycopg
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "hotel_admin")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme_hotel_2024")
PG_DB = os.getenv("POSTGRES_DB", "savannah_crest")

BASELINE_DIR = "portfolio-2-query-optimisation/evidence/baseline"
OPTIMISED_DIR = "portfolio-2-query-optimisation/evidence/optimised"
SUMMARY_CSV = "portfolio-2-query-optimisation/evidence/performance-summary.csv"
SIZES_FILE = "portfolio-2-query-optimisation/evidence/table-index-sizes.txt"
SQL_FILE = "portfolio-2-query-optimisation/sql/10_queries.sql"

os.makedirs(OPTIMISED_DIR, exist_ok=True)


def parse_queries(sql_content):
    pattern = r"(-- =+\n-- (Q\d+):[^\n]+\n-- =+[\s\S]*?)(?=-- =+\n-- Q\d+:|$)"
    matches = re.findall(pattern, sql_content)
    queries = []
    for header_and_body, q_id in matches:
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


def extract_metrics_from_plan(plan_text):
    """Extracts execution time, planning time, and buffer hits/reads from EXPLAIN output."""
    exec_match = re.search(r"Execution Time:\s+([\d\.]+)\s+ms", plan_text)
    plan_match = re.search(r"Planning Time:\s+([\d\.]+)\s+ms", plan_text)
    hit_match = re.search(r"shared hit=(\d+)", plan_text)
    read_match = re.search(r"read=(\d+)", plan_text)
    
    exec_time = float(exec_match.group(1)) if exec_match else 0.0
    plan_time = float(plan_match.group(1)) if plan_match else 0.0
    shared_hit = int(hit_match.group(1)) if hit_match else 0
    shared_read = int(read_match.group(1)) if read_match else 0
    
    return {
        "execution_time_ms": exec_time,
        "planning_time_ms": plan_time,
        "shared_hit": shared_hit,
        "shared_read": shared_read,
        "total_buffers": shared_hit + shared_read
    }


def identify_plan_node(plan_text):
    """Identifies primary plan access method and join types."""
    nodes = []
    if "Index Only Scan" in plan_text:
        nodes.append("Index Only Scan")
    elif "Index Scan" in plan_text:
        nodes.append("Index Scan")
    elif "Bitmap Index Scan" in plan_text:
        nodes.append("Bitmap Scan")
    elif "Seq Scan" in plan_text:
        nodes.append("Seq Scan")
        
    if "SubPlan" in plan_text:
        nodes.append("SubPlan (Correlated)")
    if "WindowAgg" in plan_text:
        nodes.append("WindowAgg")
    if "external merge" in plan_text:
        nodes.append("Disk Sort")
    elif "top-N heapsort" in plan_text:
        nodes.append("Top-N Heapsort")
    elif "quicksort" in plan_text:
        nodes.append("Quicksort")
    return " + ".join(nodes[:3]) if nodes else "Standard Plan"


def measure_median_execution(cursor, sql_text, runs=3):
    """Runs query N times and returns median execution time in ms."""
    timings = []
    for _ in range(runs):
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql_text};")
        rows = [r[0] for r in cursor.fetchall()]
        plan_str = "\n".join(rows)
        m = re.search(r"Execution Time:\s+([\d\.]+)\s+ms", plan_str)
        if m:
            timings.append(float(m.group(1)))
    return round(statistics.median(timings), 2) if timings else 0.0


def main():
    print("==================================================================")
    print("Portfolio 2: Benchmark & Optimisation Performance Analysis")
    print(f"Connecting to {PG_DB} at {PG_HOST}:{PG_PORT}...")
    print("==================================================================")
    
    conn = psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB
    )
    cur = conn.cursor()
    
    with open(SQL_FILE, "r") as f:
        queries = parse_queries(f.read())
        
    summary_rows = []
    
    for q_id, comments, sql_text in queries:
        num_str = q_id.lower()
        baseline_file = os.path.join(BASELINE_DIR, f"{num_str}.txt")
        optimised_file = os.path.join(OPTIMISED_DIR, f"{num_str}.txt")
        
        print(f"\nEvaluating {q_id}...")
        
        # 1. Read baseline plan metrics
        baseline_metrics = {"execution_time_ms": 0.0, "total_buffers": 0}
        baseline_plan_node = "Seq Scan"
        if os.path.exists(baseline_file):
            with open(baseline_file, "r") as bf:
                base_text = bf.read()
                baseline_metrics = extract_metrics_from_plan(base_text)
                baseline_plan_node = identify_plan_node(base_text)

        # 2. Capture detailed optimised plan
        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) {sql_text};"
        cur.execute(explain_sql)
        opt_plan_lines = [r[0] for r in cur.fetchall()]
        opt_plan_text = "\n".join(opt_plan_lines)
        
        with open(optimised_file, "w") as of:
            of.write(f"=====================================================================\n")
            of.write(f"OPTIMISED EXECUTION PLAN: {q_id}\n")
            of.write(f"Environment: PostgreSQL 16 (Targeted Indexes & Windowing Applied)\n")
            of.write(f"=====================================================================\n\n")
            of.write(f"{comments}\n\n")
            of.write(f"--- QUERY SQL ---\n{sql_text};\n\n")
            of.write(f"--- EXPLAIN (ANALYZE, BUFFERS) ---\n")
            of.write(opt_plan_text + "\n")
            
        opt_metrics = extract_metrics_from_plan(opt_plan_text)
        opt_plan_node = identify_plan_node(opt_plan_text)
        
        # 3. Measure median of 3 runs for accurate timing
        median_time = measure_median_execution(cur, sql_text, runs=3)
        before_time = baseline_metrics["execution_time_ms"]
        
        # Compute speedup
        speedup_factor = round(before_time / max(0.01, median_time), 2)
        pct_reduction = round(((before_time - median_time) / max(0.01, before_time)) * 100, 1)
        
        plan_change_desc = f"{baseline_plan_node} -> {opt_plan_node}"
        
        print(f"  Baseline:   {before_time:.2f} ms ({baseline_metrics['total_buffers']:,} buffers) [{baseline_plan_node}]")
        print(f"  Optimised:  {median_time:.2f} ms ({opt_metrics['total_buffers']:,} buffers) [{opt_plan_node}]")
        print(f"  Improvement: {speedup_factor}x faster ({pct_reduction}% reduction)")

        summary_rows.append({
            "query": q_id,
            "before_ms": before_time,
            "after_ms": median_time,
            "speedup_factor": f"{speedup_factor}x",
            "time_reduction_pct": f"{pct_reduction}%",
            "buffers_before": baseline_metrics["total_buffers"],
            "buffers_after": opt_metrics["total_buffers"],
            "plan_change": plan_change_desc
        })
        
    # Write performance summary CSV
    with open(SUMMARY_CSV, "w", newline="") as cf:
        fieldnames = ["query", "before_ms", "after_ms", "speedup_factor", "time_reduction_pct", "buffers_before", "buffers_after", "plan_change"]
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
        
    print(f"\nPerformance summary written to {SUMMARY_CSV}")
    
    # --------------------------------------------------------------------------
    # 4. Measure Relation and Index Sizes
    # --------------------------------------------------------------------------
    print("\nMeasuring storage footprints across relations and indexes...")
    cur.execute("""
        SELECT 
            c.relname AS object_name,
            CASE c.relkind 
                WHEN 'r' THEN 'Table' 
                WHEN 'i' THEN 'Index' 
            END AS object_type,
            pg_size_pretty(pg_relation_size(c.oid)) AS size_pretty,
            pg_relation_size(c.oid) AS size_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' 
          AND c.relkind IN ('r', 'i')
        ORDER BY pg_relation_size(c.oid) DESC;
    """)
    sizes = cur.fetchall()
    
    with open(SIZES_FILE, "w") as sf:
        sf.write("=====================================================================\n")
        sf.write("DATABASE STORAGE FOOTPRINT: TABLES AND INDEXES\n")
        sf.write("=====================================================================\n\n")
        sf.write(f"{'Object Name':<35} | {'Type':<6} | {'Size':>10} | {'Bytes':>12}\n")
        sf.write("-" * 72 + "\n")
        for obj, otype, sz_pretty, sz_bytes in sizes:
            sf.write(f"{obj:<35} | {otype:<6} | {sz_pretty:>10} | {sz_bytes:>12,}\n")
        sf.write("-" * 72 + "\n")
        
    print(f"Table and index sizes written to {SIZES_FILE}")

    # --------------------------------------------------------------------------
    # 5. Measure Write Overhead (Insert Throughput Comparison)
    # --------------------------------------------------------------------------
    print("\nMeasuring write overhead on 'booking' table...")
    # Insert 1,000 benchmark rows
    test_rows = []
    t_base_id = 9000000
    for i in range(1000):
        test_rows.append(f"({t_base_id + i}, 1, 1, 'TEST-BENCH-{i:05d}', 'confirmed', '2026-12-01', 50000.00)")
        
    val_str = ",\n".join(test_rows)
    insert_sql = f"INSERT INTO booking (booking_id, guest_id, hotel_id, booking_ref, status, booking_date, total_amount) VALUES {val_str};"
    
    t0 = time.time()
    cur.execute(insert_sql)
    conn.commit()
    elapsed = time.time() - t0
    rate = 1000.0 / elapsed
    print(f"  Inserted 1,000 rows into indexed 'booking' table in {elapsed:.3f}s ({rate:.0f} rows/s).")
    
    # Clean up test rows
    cur.execute(f"DELETE FROM booking WHERE booking_id >= {t_base_id};")
    conn.commit()
    
    cur.close()
    conn.close()
    print("\nBenchmark and performance analysis completed successfully.")


if __name__ == "__main__":
    main()

