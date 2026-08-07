# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebridge Reconciler — air-gapped in-workspace run
# MAGIC
# MAGIC Same as the regular reconciler, but installs Lakebridge from an **offline wheelhouse
# MAGIC on a UC Volume** (`--no-index --find-links`) because the cluster has no internet.
# MAGIC See `RUNBOOK.md` §5 (pre-create the backend), §7 (Databricks-to-Databricks), and §8
# MAGIC (external Redshift source via a UC connection + `remote_query`, DBR 17.3+).
# MAGIC
# MAGIC **Compute:** classic cluster (serverless unsupported for the persist step). The
# MAGIC metadata **schema + volume must pre-exist** (see RUNBOOK §5).
# MAGIC
# MAGIC > Field note: this JSON-driven `TableRecon` shape mirrors the original recon mapping,
# MAGIC > so the same table list can be reused across customers.

# COMMAND ----------

# DBTITLE 1,CONFIG — edit these
WHEELS_DIR    = "/Volumes/<catalog>/default/lakebridge/wheels"

REPORT_TYPE   = "all"          # "schema" | "data" | "row" | "all" | "aggregate"
DIALECT       = "databricks"   # or oracle/snowflake/mssql/synapse/redshift/teradata/bigquery
SRC_CATALOG   = "<catalog>"
SRC_SCHEMA    = "<schema>"
UC_CONNECTION = None           # e.g. "my_redshift_conn" for an external source (RUNBOOK §8)

TGT_CATALOG   = "<catalog>"
TGT_SCHEMA    = "<schema>"

META_CATALOG  = "<catalog>"
META_SCHEMA   = "lb_recon"
META_VOLUME   = "reconcile_volume"

# Tables to reconcile: (source_name, target_name, [join_columns])
TABLES = [
    ("customers_src", "customers_tgt", ["id"]),
]

# COMMAND ----------

# MAGIC %pip install --no-index --find-links=/Volumes/<catalog>/default/lakebridge/wheels databricks-labs-lakebridge
# MAGIC dbutils.library.restartPython()

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
    print("Results in:",
          f"{META_CATALOG}.{META_SCHEMA}.{{main, metrics, details}} where recon_id = '{out.recon_id}'")
    dbutils.notebook.exit(out.recon_id)
except ReconciliationException as e:
    print("RECON EXCEPTION:", e)
    raise
