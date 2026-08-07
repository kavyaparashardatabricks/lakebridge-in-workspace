# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Transpiler — in-workspace run (no CLI, no `install-transpile`)
# MAGIC
# MAGIC Converts source SQL/ETL to Databricks SQL from inside a workspace notebook. Lakebridge
# MAGIC ships **two** transpiler engines — pick per your source and constraints:
# MAGIC
# MAGIC | Engine | What it is | In-workspace fit | Notes |
# MAGIC |---|---|---|---|
# MAGIC | **Morpheus** | Deterministic grammar-based transpiler (`databricks-bb-*`) | Needs **Java 21** on the compute | Best for supported SQL dialects; JDK is hard on serverless — use a classic cluster with Java, or run locally |
# MAGIC | **Switch** | LLM/agent-based transpiler that runs **as a Databricks job** | Native in-workspace | Uses model serving (token cost); handles dialects Morpheus doesn't; newer `/migrate` agentic converter is the productized successor |
# MAGIC
# MAGIC > ⚠️ **Verification status:** the Analyzer and Reconciler notebooks in this folder are
# MAGIC > verified end-to-end. This transpiler notebook is a **starting scaffold** — the
# MAGIC > engine call below follows the package API but has not been run end-to-end in a
# MAGIC > notebook here. Validate on a small batch first. For most in-workspace, no-CLI use
# MAGIC > cases the **Switch job** or the productized **agentic converter** (`/migrate`,
# MAGIC > https://docs.databricks.com/aws/en/migration/lakebridge-agentic-converter) is the
# MAGIC > smoother path.

# COMMAND ----------

# MAGIC %pip install databricks-labs-lakebridge
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
SOURCE_DIR    = "/Volumes/<catalog>/<schema>/<volume>/input"    # source SQL/ETL files
OUTPUT_DIR    = "/Volumes/<catalog>/<schema>/<volume>/transpiled"
SOURCE_DIALECT = "oracle"      # e.g. oracle, snowflake, tsql, teradata, ...
# Morpheus needs Java 21 available on the driver; check before running (see cell below).

# COMMAND ----------

# DBTITLE 1,Morpheus path — direct engine call
# The transpiler config + engine live under databricks.labs.lakebridge.transpiler.
# This mirrors what `databricks labs lakebridge transpile` drives internally.
import shutil, subprocess, tempfile
from pathlib import Path

# 1) Confirm Java 21 is present (Morpheus requirement). If this fails, use Switch instead.
print(subprocess.run(["java", "-version"], capture_output=True, text=True).stderr or "no java")

from databricks.labs.lakebridge.config import TranspileConfig
from databricks.labs.lakebridge.transpiler.execute import transpile as run_transpile  # engine entrypoint
from databricks.sdk import WorkspaceClient

out = Path(OUTPUT_DIR); out.mkdir(parents=True, exist_ok=True)
cfg = TranspileConfig(
    transpiler_config_path=None,        # default Morpheus config
    source_dialect=SOURCE_DIALECT,
    input_source=SOURCE_DIR,
    output_folder=OUTPUT_DIR,
    skip_validation=True,               # set False to validate against a target
    catalog_name=None, schema_name=None,
)
# NOTE: exact transpile() signature can vary by Lakebridge version — inspect with
#   help(run_transpile)
# and adjust. Prefer Switch (next cell) if Java 21 isn't available on this compute.
result = run_transpile(WorkspaceClient(), cfg)   # may be async in some versions
print("transpile result:", result)
print("outputs:", [p.name for p in out.iterdir()][:20])

# COMMAND ----------

# DBTITLE 1,Switch path (LLM transpiler as a workspace job) — pointer
# MAGIC %md
# MAGIC Switch runs as a Databricks **job** and uses model serving (token-metered). It is the
# MAGIC no-CLI, no-JDK in-workspace option and handles dialects Morpheus can't. To use it:
# MAGIC install/import the Switch assets into the workspace and trigger the job with your
# MAGIC source/target volumes as parameters. The newer **agentic converter** (`/migrate`) is
# MAGIC the productized version and is recommended going forward. Token consumption is the
# MAGIC main cost driver — as a rough field data point, ~350 SQL files transpiled with Switch
# MAGIC consumed on the order of 5–8M tokens/day for the running user.
