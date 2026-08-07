# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Analyzer — in-workspace run (no CLI, no desktop app)
# MAGIC
# MAGIC Runs the Lakebridge **Assessment/Analyzer** engine directly in a **serverless**
# MAGIC Python notebook — no Databricks CLI and no desktop app required.
# MAGIC
# MAGIC **How it works**
# MAGIC 1. `pip install` the Lakebridge package into the notebook session.
# MAGIC 2. Point the analyzer at a folder of exported source metadata (SQL / ETL exports)
# MAGIC    staged on a **Unity Catalog Volume**.
# MAGIC 3. Call the underlying `bladespector` engine directly (NOT `ApplicationContext`,
# MAGIC    which fails on import in a notebook with `Cannot find project root`).
# MAGIC 4. Write the `.xlsx`/`.json` report to **local scratch first**, then copy to the
# MAGIC    output Volume — Volumes are a FUSE mount and can't do the random-access writes
# MAGIC    the xlsx (zip) writer needs, so a direct write produces a ~390B corrupt stub.
# MAGIC
# MAGIC **Edit the CONFIG cell below**, then Run All.

# COMMAND ----------

# MAGIC %pip install databricks-labs-lakebridge openpyxl
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
# Folder of exported source metadata to analyze (SQL files, or ETL repo exports).
SOURCE_DIR   = "/Volumes/<catalog>/<schema>/<volume>/input"

# Where the finished report should land (Volume folder). Files: report.xlsx (+ report.json).
OUTPUT_DIR   = "/Volumes/<catalog>/<schema>/<volume>/output"

# Source technology. Must match a value from Analyzer.supported_source_technologies()
# (printed below). Examples: "Oracle", "Snowflake", "Teradata", "SSIS", "Informatica",
# "DataStage", "BigQuery", "Hive", "Talend", ...
PLATFORM     = "Oracle"

# Also emit a machine-readable JSON report alongside the Excel workbook.
GENERATE_JSON = True

# COMMAND ----------

# DBTITLE 1,Run analyzer (local write -> copy to Volume)
import shutil, tempfile
from pathlib import Path
from databricks.labs.bladespector.analyzer import Analyzer

src     = Path(SOURCE_DIR)
vol_out = Path(OUTPUT_DIR)

# Serverless-writable local scratch (seekable FS). NOTE: /local_disk0 is read-only on
# serverless, so use tempfile.mkdtemp() which writes under /tmp.
local_out  = Path(tempfile.mkdtemp(prefix="lakebridge_"))
local_xlsx = local_out / "report.xlsx"                 # MUST end in .xlsx
local_json = (local_out / "report.json") if GENERATE_JSON else None

# Sanity checks
assert src.is_dir(), f"source dir missing: {src}"
print("source entries:", [p.name for p in src.iterdir()][:20])
vol_out.mkdir(parents=True, exist_ok=True)

# Confirm the platform string is valid
techs = Analyzer.supported_source_technologies()
print("supported technologies:", techs)
assert PLATFORM in techs, f"{PLATFORM!r} not in supported list — pick one from above"

# 1) write to LOCAL scratch (not the Volume). Signature:
#    Analyzer.analyze(source_dir, results_file_path, platform, is_debug, json_result)
Analyzer.analyze(src, local_xlsx, PLATFORM, False, local_json)

# 2) verify it's a real workbook locally (KBs, not ~390 bytes)
sz = local_xlsx.stat().st_size
print("local xlsx size:", sz)
assert sz > 5000, "report still looks corrupt — check source dir / platform"

# 3) copy finished files to the Volume
shutil.copy(local_xlsx, vol_out / "report.xlsx")
if local_json and local_json.exists():
    shutil.copy(local_json, vol_out / "report.json")

print("done. output volume now has:", [p.name for p in vol_out.iterdir()])
print("final xlsx size on volume:", (vol_out / "report.xlsx").stat().st_size)

# COMMAND ----------

# DBTITLE 1,Verify the workbook opens and inspect sheets
import pandas as pd

sheets = pd.read_excel(local_xlsx, sheet_name=None)
print("sheets:", list(sheets.keys()))
for name, df in sheets.items():
    print(f"\n--- {name}: {df.shape[0]} rows x {df.shape[1]} cols ---")
    print(df.head(5).to_string(max_colwidth=40))
