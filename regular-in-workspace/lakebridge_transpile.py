# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Transpiler — in-workspace run (no CLI, no `install-transpile`, no Java)
# MAGIC
# MAGIC Converts source SQL to Databricks SQL from inside a workspace notebook using
# MAGIC Lakebridge's **pure-Python `sqlglot` engine** — no `databricks labs lakebridge
# MAGIC install-transpile`, no downloaded LSP transpiler servers, and **no Java 21**.
# MAGIC Runs on serverless or classic compute.
# MAGIC
# MAGIC Lakebridge ships three transpiler engines; this notebook uses the first:
# MAGIC
# MAGIC | Engine | What it is | In-workspace fit |
# MAGIC |---|---|---|
# MAGIC | **sqlglot** (used here) | Pure-Python dialect translator | ✅ Runs directly in a notebook, no Java, no extra install |
# MAGIC | **Morpheus** | Deterministic grammar-based LSP transpiler | Needs `install-transpile` + **Java 21** on the compute |
# MAGIC | **Switch** | LLM/agent transpiler that runs as a Databricks job | Token-metered (model serving); newer `/migrate` agentic converter is the productized successor |
# MAGIC
# MAGIC sqlglot handles the common SQL-dialect surface; for constructs it can't translate it
# MAGIC records a per-file error (see `error_count` in the output) — those are the pieces to
# MAGIC route to Morpheus/Switch or fix by hand.
# MAGIC
# MAGIC > ✅ **Verified end-to-end** on a Databricks classic cluster (Azure, DBR 16.4):
# MAGIC > 4 Oracle files transpiled and written to a UC Volume. sqlglot translates SQL
# MAGIC > constructs well (`NVL`→`COALESCE`, `SYSDATE`→`CURRENT_TIMESTAMP()`, INSERT
# MAGIC > reformatting). It is a **SQL** transpiler, so PL/SQL procedural wrappers
# MAGIC > (`CREATE FUNCTION … IS BEGIN … END`, `DBMS_OUTPUT`, cursors) are only partially
# MAGIC > handled — route those files to **Morpheus** or **Switch**. Check `error_count`
# MAGIC > per file to see what needs follow-up.

# COMMAND ----------

# MAGIC %pip install databricks-labs-lakebridge nest_asyncio
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
SOURCE_DIR     = "/Volumes/<catalog>/<schema>/<volume>/input"        # source .sql files
OUTPUT_DIR     = "/Volumes/<catalog>/<schema>/<volume>/transpiled"   # transpiled output
SOURCE_DIALECT = "oracle"       # must be in SqlglotEngine().supported_dialects
TARGET_DIALECT = "databricks"

# COMMAND ----------

# DBTITLE 1,Transpile every .sql file with the sqlglot engine
import asyncio, shutil, tempfile
import nest_asyncio; nest_asyncio.apply()   # notebooks already run an event loop, so
                                            # asyncio.run() would raise; patch to allow it
from pathlib import Path
from databricks.labs.lakebridge.transpiler.sqlglot.sqlglot_engine import SqlglotEngine

engine = SqlglotEngine()
print("engine:", engine.transpiler_name)
assert SOURCE_DIALECT in engine.supported_dialects, \
    f"{SOURCE_DIALECT!r} not supported; pick from {engine.supported_dialects}"
assert TARGET_DIALECT in engine.supported_dialects

src = Path(SOURCE_DIR)
vol_out = Path(OUTPUT_DIR); vol_out.mkdir(parents=True, exist_ok=True)
local_out = Path(tempfile.mkdtemp(prefix="lb_transpile_"))   # seekable local scratch

sql_files = list(src.rglob("*.sql"))
assert sql_files, f"no .sql files under {src}"

async def run():
    rows = []
    for f in sql_files:
        res = await engine.transpile(SOURCE_DIALECT, TARGET_DIALECT, f.read_text(), f)
        out_name = f.stem + ".databricks.sql"
        (local_out / out_name).write_text(res.transpiled_code)   # write local first
        shutil.copy(local_out / out_name, vol_out / out_name)    # then copy to Volume
        rows.append((f.name, res.success_count, len(res.error_list)))
        for err in res.error_list:
            print(f"  [warn] {f.name}: {err}")
    return rows

rows = asyncio.get_event_loop().run_until_complete(run())
print("\ntranspiled (file, success_count, error_count):")
for r in rows:
    print("  ", r)
print("\noutput dir:", [p.name for p in vol_out.iterdir()])

# COMMAND ----------

# DBTITLE 1,Show one transpiled sample
sample = sorted(vol_out.glob("*.databricks.sql"))[0]
print("===", sample.name, "===")
print(sample.read_text())
