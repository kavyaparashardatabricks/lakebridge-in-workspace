# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Profiler — air-gapped in-workspace run
# MAGIC
# MAGIC Runs the Lakebridge **Profiler** (assessment pipeline) against a source database and writes
# MAGIC a **DuckDB extract** (`profiler_extract_<source>_<ver>_<date>.db`) you can feed into the TCO
# MAGIC tooling. Installs Lakebridge from an **offline wheelhouse on a UC Volume**. See `RUNBOOK.md`
# MAGIC §3–4 (wheelhouse) and §10 (profiler).
# MAGIC
# MAGIC **Two things to know:**
# MAGIC 1. Unlike the reconciler, the profiler connects **directly** to the source DB from the cluster
# MAGIC    (e.g. Redshift port 5439). Your workspace compute needs a **network route to that database**
# MAGIC    (VPC peering / PrivateLink / security-group rule). No internet is needed.
# MAGIC 2. Store the DB credentials in a **Databricks secret scope** (don't hard-code them here).
# MAGIC
# MAGIC **Compute:** classic cluster, DBR 17.3+. Supported sources: redshift, snowflake, mssql,
# MAGIC synapse, oracle, teradata (Lakebridge 0.15.0).

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
WHEELS_DIR    = "/Volumes/<catalog>/default/lakebridge/wheels"      # offline wheelhouse
OUTPUT_DIR    = "/Volumes/<catalog>/default/lakebridge/profiler"    # where the .db extract lands
SOURCE_SYSTEM = "redshift"      # redshift/snowflake/mssql/synapse/oracle/teradata
SECRET_SCOPE  = "lakebridge"    # Databricks secret scope holding the connection

# Create the secrets once from your laptop, e.g.:
#   databricks secrets create-scope lakebridge
#   databricks secrets put-secret lakebridge redshift_host     --string-value <host>
#   databricks secrets put-secret lakebridge redshift_db       --string-value <db>
#   databricks secrets put-secret lakebridge redshift_user     --string-value <user>
#   databricks secrets put-secret lakebridge redshift_password --string-value <password>

# COMMAND ----------

# MAGIC %pip install --no-index --find-links=/Volumes/<catalog>/default/lakebridge/wheels databricks-labs-lakebridge
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Load the shipped Redshift pipeline (works on 0.14.x and 0.15.x layouts)
from pathlib import Path
import databricks.labs.lakebridge as lb
from databricks.labs.lakebridge.assessments.pipeline import PipelineClass, make_profiler_db_filename

pkg_root = Path(lb.__file__).parent
src_base = pkg_root / "resources" / "assessments" / SOURCE_SYSTEM
if (src_base / "pipeline_config.yml").exists():          # 0.15.x: flat config + sql/ subdir
    cfg_file = src_base / "pipeline_config.yml"
    sql_base = src_base / "sql" if (src_base / "sql").exists() else src_base
else:                                                     # 0.14.x: provisioned/ subdir
    cfg_file = src_base / "provisioned" / "pipeline_config.yml"
    sql_base = src_base / "provisioned"
assert cfg_file.exists(), f"pipeline config not found under {src_base}"

config = PipelineClass.load_config_from_yaml(cfg_file)
config = config.copy(steps=[s.copy(extract_source=str(sql_base / Path(s.extract_source).name))
                            for s in config.steps])
print("pipeline:", config.name, "| steps:", [(s.name, s.type) for s in config.steps])

# COMMAND ----------

# DBTITLE 1,Connect to the source and run the profiler
import shutil, tempfile
# 0.15.x exposes create_connector(); 0.14.x used DatabaseManager(...).connector
try:
    from databricks.labs.lakebridge.connections.database_manager import create_connector
    def make_extractor(src, cfg): return create_connector(src, cfg)
except ImportError:
    from databricks.labs.lakebridge.connections.database_manager import DatabaseManager
    def make_extractor(src, cfg): return DatabaseManager(src, cfg).connector

connect_config = {
    "host":      dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_SYSTEM}_host"),
    "port":      5439,
    "database":  dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_SYSTEM}_db"),
    "user":      dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_SYSTEM}_user"),
    "password":  dbutils.secrets.get(SECRET_SCOPE, f"{SOURCE_SYSTEM}_password"),
    "auth_type": "sql_authentication",
    "ssl":       "true",
}
extractor = make_extractor(SOURCE_SYSTEM, connect_config)
print("source health check:", extractor.health_check())

local_out = Path(tempfile.mkdtemp(prefix="lbprofiler_"))   # DuckDB needs a seekable local FS
db_path   = local_out / make_profiler_db_filename(SOURCE_SYSTEM)
creds_stub = local_out / "creds.yml"; creds_stub.write_text("{}")   # unused: no python steps

results = PipelineClass(config, extractor, db_path, creds_stub).execute()
for r in results:
    print(f"  {r.step_name}: {r.status}")
print("extract:", db_path, "bytes:", db_path.stat().st_size)

# COMMAND ----------

# DBTITLE 1,Inspect the DuckDB extract and copy it to the Volume
import duckdb, json
conn = duckdb.connect(str(db_path))
tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
summary = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
conn.close()
print("tables:", summary)

vol_out = Path(OUTPUT_DIR); vol_out.mkdir(parents=True, exist_ok=True)
shutil.copy(db_path, vol_out / db_path.name)
print("copied to:", vol_out / db_path.name)
dbutils.notebook.exit(json.dumps({"db": db_path.name, "tables": len(tables), "rows": summary}, default=str))
