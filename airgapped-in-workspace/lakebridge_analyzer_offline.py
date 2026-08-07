# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Analyzer — air-gapped in-workspace run
# MAGIC
# MAGIC Same as the regular analyzer, but installs Lakebridge from an **offline wheelhouse on
# MAGIC a UC Volume** (`--no-index --find-links`) because the cluster has **no outbound
# MAGIC internet**. See `RUNBOOK.md` §3–4 for building/uploading the wheelhouse, and §9 for
# MAGIC the full gotchas table.
# MAGIC
# MAGIC **Prereq:** wheelhouse staged at `WHEELS_DIR` (built for the *cluster's* Python/OS —
# MAGIC e.g. DBR 17.3 ⇒ cp312 / manylinux x86_64), including `openpyxl` and the
# MAGIC `databricks_bb_analyzer` wheel. Run on a **classic cluster**.

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
WHEELS_DIR = "/Volumes/<catalog>/default/lakebridge/wheels"      # offline wheelhouse
SOURCE_DIR = "/Volumes/<catalog>/default/lakebridge/input"       # exported source files
OUTPUT_DIR = "/Volumes/<catalog>/default/lakebridge/output"
PLATFORM   = "Oracle"    # must be in Analyzer.supported_source_technologies()

# COMMAND ----------

# MAGIC %pip install --no-index --find-links=/Volumes/<catalog>/default/lakebridge/wheels databricks-labs-lakebridge openpyxl
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Run analyzer (local write -> copy to Volume)
import shutil, tempfile
from pathlib import Path
from databricks.labs.bladespector.analyzer import Analyzer   # NOT ApplicationContext

src, vol_out = Path(SOURCE_DIR), Path(OUTPUT_DIR)
local_out  = Path(tempfile.mkdtemp(prefix="lakebridge_"))    # seekable local scratch
local_xlsx = local_out / "report.xlsx"
local_json = local_out / "report.json"

assert src.is_dir() and any(src.iterdir()), f"empty/missing source dir: {src}"
vol_out.mkdir(parents=True, exist_ok=True)
assert PLATFORM in Analyzer.supported_source_technologies()

# write to LOCAL scratch first, then copy to the Volume (Volumes can't do random-access
# writes -> a direct .xlsx write truncates to a ~390-byte corrupt stub)
Analyzer.analyze(src, local_xlsx, PLATFORM, False, local_json)
assert local_xlsx.stat().st_size > 5000, "report looks corrupt (empty dir / wrong platform?)"
shutil.copy(local_xlsx, vol_out / "report.xlsx")
if local_json.exists():
    shutil.copy(local_json, vol_out / "report.json")
print("done:", [p.name for p in vol_out.iterdir()])
