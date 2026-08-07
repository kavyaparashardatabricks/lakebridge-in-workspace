# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Reconciler — in-workspace run (no CLI, no `configure-reconcile`)
# MAGIC
# MAGIC Runs the Lakebridge **Reconciler** directly in a workspace notebook by calling
# MAGIC `TriggerReconService.trigger_recon(...)` — no `databricks labs lakebridge
# MAGIC configure-reconcile` and no desktop app.
# MAGIC
# MAGIC **Compute:** use a **classic cluster** (or Pro SQL warehouse), *not* serverless —
# MAGIC the reconcile persist step fails on serverless (`PERSIST TABLE not supported on
# MAGIC serverless`).
# MAGIC
# MAGIC **One-time backend setup** (what `configure-reconcile` normally creates): a metadata
# MAGIC schema and a UC Volume must pre-exist. The result tables (`main`/`metrics`/`details`)
# MAGIC auto-create via `saveAsTable`. The Volume is required whenever
# MAGIC `DATABRICKS_RUNTIME_VERSION` is set (i.e. any cluster), not just serverless:
# MAGIC ```sql
# MAGIC CREATE SCHEMA IF NOT EXISTS <catalog>.lb_recon;
# MAGIC -- + create a MANAGED volume <catalog>.lb_recon.reconcile_volume
# MAGIC ```

# COMMAND ----------

# MAGIC %pip install databricks-labs-lakebridge
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
# Reconcile scope
REPORT_TYPE   = "all"          # "schema" | "data" | "row" | "all" | "aggregate"

# Source: for Databricks-to-Databricks leave UC_CONNECTION = None (=> "databricks" dialect).
# For an external source (oracle/snowflake/mssql/synapse/redshift/teradata/bigquery),
# set DIALECT accordingly and point UC_CONNECTION at a pre-created UC connection.
DIALECT       = "databricks"
SRC_CATALOG   = "<catalog>"
SRC_SCHEMA    = "<schema>"
UC_CONNECTION = None           # e.g. "my_redshift_conn" for external sources

# Target (Databricks)
TGT_CATALOG   = "<catalog>"
TGT_SCHEMA    = "<schema>"

# Metadata backend (must pre-exist: schema + volume)
META_CATALOG  = "<catalog>"
META_SCHEMA   = "lb_recon"
META_VOLUME   = "reconcile_volume"

# Tables to reconcile: (source_name, target_name, [join_columns])
TABLES = [
    ("customers_src", "customers_tgt", ["id"]),
]

# COMMAND ----------

# DBTITLE 1,Run reconcile
import json
from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession
from databricks.labs.lakebridge.config import (
    ReconcileConfig, ReconcileMetadataConfig, TableRecon,
    SourceConnectionConfig, TargetConnectionConfig)
from databricks.labs.lakebridge.reconcile.recon_config import Table
from databricks.labs.lakebridge.reconcile.trigger_recon_service import TriggerReconService
from databricks.labs.lakebridge.reconcile.exception import ReconciliationException

spark = SparkSession.builder.getOrCreate()
ws = WorkspaceClient()

reconcile_config = ReconcileConfig(
    report_type=REPORT_TYPE,
    source=SourceConnectionConfig(
        dialect=DIALECT, catalog=SRC_CATALOG, schema=SRC_SCHEMA,
        uc_connection_name=UC_CONNECTION),
    target=TargetConnectionConfig(catalog=TGT_CATALOG, schema=TGT_SCHEMA),
    metadata_config=ReconcileMetadataConfig(
        catalog=META_CATALOG, schema=META_SCHEMA, volume=META_VOLUME),
)
table_recon = TableRecon(tables=[
    Table(source_name=s, target_name=t, join_columns=j) for (s, t, j) in TABLES
])

try:
    out = TriggerReconService.trigger_recon(ws, spark, table_recon, reconcile_config)
    print(json.dumps({"ok": True, "recon_id": out.recon_id}))
    print("Inspect results in:",
          f"{META_CATALOG}.{META_SCHEMA}.{{main, metrics, details}} where recon_id = '{out.recon_id}'")
    dbutils.notebook.exit(out.recon_id)
except ReconciliationException as e:
    print("RECON EXCEPTION:", e)
    raise
