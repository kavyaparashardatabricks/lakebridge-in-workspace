# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Transpiler — air-gapped in-workspace run
# MAGIC
# MAGIC Converts source SQL (e.g. Redshift, Oracle, Snowflake) to **Databricks SQL** using the
# MAGIC pure-Python **sqlglot** engine — no Java, no `install-transpile`, no internet. Installs
# MAGIC Lakebridge from an **offline wheelhouse on a UC Volume**. See `RUNBOOK.md` §3–4 (wheelhouse)
# MAGIC and §6b (transpiler).
# MAGIC
# MAGIC **What it does:** reads every `.sql` file in an input folder, transpiles it, writes the
# MAGIC Databricks-SQL version to an output folder, and prints how many statements converted and
# MAGIC any per-file errors. It's a SQL transpiler — procedural PL/SQL blocks come out only
# MAGIC partially converted (check the error count).

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
WHEELS_DIR  = "/Volumes/<catalog>/default/lakebridge/wheels"     # offline wheelhouse
INPUT_DIR   = "/Volumes/<catalog>/default/lakebridge/input"      # source .sql files
OUTPUT_DIR  = "/Volumes/<catalog>/default/lakebridge/transpiled" # where converted .sql go
SRC_DIALECT = "redshift"     # source: redshift/oracle/snowflake/mssql/synapse/teradata/bigquery
TGT_DIALECT = "databricks"

# COMMAND ----------

# MAGIC %pip install --no-index --find-links=/Volumes/<catalog>/default/lakebridge/wheels databricks-labs-lakebridge
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Transpile every .sql file
import asyncio, threading
from pathlib import Path
from databricks.labs.lakebridge.transpiler.sqlglot.sqlglot_engine import SqlglotEngine

in_dir, out_dir = Path(INPUT_DIR), Path(OUTPUT_DIR)
out_dir.mkdir(parents=True, exist_ok=True)
engine = SqlglotEngine()

# Databricks notebooks already run an event loop, so asyncio.run() fails.
# Run each async transpile on a fresh loop in a worker thread.
def run_coro(coro):
    box = {}
    def _t():
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        try:
            box["v"] = loop.run_until_complete(coro)
        finally:
            loop.close()
    th = threading.Thread(target=_t); th.start(); th.join()
    return box["v"]

sql_files = sorted(p for p in in_dir.iterdir() if p.suffix.lower() == ".sql")
assert sql_files, f"no .sql files in {in_dir}"

total_err = 0
for f in sql_files:
    res = run_coro(engine.transpile(SRC_DIALECT, TGT_DIALECT, f.read_text(), f))
    (out_dir / f.name).write_text(res.transpiled_code)     # plain-text write is FUSE-safe
    total_err += len(res.error_list)
    print(f"\n=== {f.name}: {res.success_count} statements, {len(res.error_list)} errors")
    for e in res.error_list:
        print("   ERROR:", e)

print(f"\nDone. {len(sql_files)} files, {total_err} total errors. Output: {out_dir}")
dbutils.notebook.exit(f"transpile_done files={len(sql_files)} errors={total_err}")
