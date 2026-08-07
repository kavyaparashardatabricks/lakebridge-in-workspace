# Lakebridge in an air-gapped Databricks workspace — install + Reconciler runbook

Run the Lakebridge **Analyzer** and **Reconciler** entirely **inside a Databricks
workspace notebook** — no Databricks CLI `labs install`, no `configure-reconcile`, no
desktop app — on a workspace whose **compute has no outbound internet**.

Verified end-to-end on 2026-07-30 in workspace `dbc-e8d3f54c-ce8c` (profile `capri-ws`)
on classic cluster `0729-064211-m5g0e77z` (DBR 17.3, `USER_ISOLATION`), Databricks-to-
Databricks. The Redshift source path (§8) is documented from the connector source but was
not run live (no Redshift endpoint available).

---

## 0. Why this is needed / TL;DR

The standard install (`databricks labs install lakebridge` + `configure-reconcile`) assumes
outbound GitHub/PyPI access from the install host **and** internet from the cluster. In a
locked-down workspace both break:

- `%pip install databricks-labs-lakebridge` on the cluster fails with
  `[Errno 101] Network is unreachable` (no route to pypi.org).
- The `%pip` magic **hides the real error** behind a generic
  `CalledProcessError ... non-zero exit status 1` — you must reproduce with `subprocess`
  to see the underlying pip message.

The fix is the same pattern the Barclays / private-PyPI playbooks describe, applied at the
notebook level instead of the CLI:

1. Build a **wheelhouse** (all wheels + transitive deps) on an internet-connected host,
   targeting the **cluster's** Python/OS (not the host's).
2. Upload the wheelhouse to a **Unity Catalog Volume**.
3. `%pip install --no-index --find-links=/Volumes/.../wheels ...` inside the notebook.
4. Call the engine classes directly (`Analyzer.analyze`, `TriggerReconService.trigger_recon`).
5. Pre-create the reconcile backend (catalog/schema/volume) yourself — the bits
   `configure-reconcile` normally makes.

Nothing about the *data path* to a source system needs new cluster egress — federation
(`remote_query`) is handled by the Databricks compute plane via a UC connection (§8).

---

## 1. Prerequisites

**Connected host** (has internet — your laptop/build box):
- Databricks CLI configured with a profile for the target workspace (here `capri-ws`).
- Python + `pip` (only used to *download* wheels).

**Target workspace:**
- A **classic cluster** or **Pro/Serverless SQL warehouse**. Use a **classic cluster for
  reconcile** — serverless is unsupported for the reconcile persist step
  (`PERSIST TABLE not supported on serverless`). DBR **17.3+** if you'll use Redshift/`remote_query`.
- Unity Catalog enabled; a catalog you can write to (here `kp_capri`).
- Permission to create schemas, volumes, and (for external sources) a UC connection.

**Match the wheelhouse to the cluster runtime:**
- DBR 17.3 ⇒ **Python 3.12**, Linux **x86_64**. Download `cp312` / `manylinux` wheels.
- Confirm with: `databricks clusters get <cluster-id> -p <profile> | grep spark_version`.

---

## 2. Set variables

```bash
export PROFILE=capri-ws
export CLUSTER_ID=0729-064211-m5g0e77z
export CATALOG=kp_capri
export WHEELS_VOL=/Volumes/$CATALOG/default/lakebridge/wheels
export SQL_WAREHOUSE_ID=aa438606b544d7b4     # Pro warehouse, for running setup SQL
export USER_HOME=/Users/kavya.parashar@databricks.com
```

Sanity-check auth and compute:

```bash
databricks current-user me -p $PROFILE
databricks clusters get $CLUSTER_ID -p $PROFILE --output json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['spark_version'],d['state'])"
```

---

## 3. Build the wheelhouse (connected host)

```bash
rm -rf /tmp/lb_wheels && mkdir -p /tmp/lb_wheels
pip download databricks-labs-lakebridge openpyxl \
  --dest /tmp/lb_wheels \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform any \
  --python-version 312 --implementation cp --only-binary=:all:
ls /tmp/lb_wheels/*.whl | wc -l          # ~90 wheels
```

**Watch for missing transitive binary deps.** `pip download` on a mac/py3.13 host can skip
platform-specific wheels. In testing, **`greenlet`** (a `sqlalchemy` dep) was missing and
had to be fetched explicitly for cp312/linux:

```bash
pip download greenlet --dest /tmp/lb_wheels \
  --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
  --python-version 312 --implementation cp --only-binary=:all:
```

The Analyzer engine (`databricks.labs.bladespector`) ships in the **`databricks-bb-analyzer`**
wheel, which is pulled in as a dependency — confirm `databricks_bb_analyzer-*.whl` is present.

> Tip: if the offline install later errors with
> `Could not find a version that satisfies the requirement <pkg>`, that package is missing
> from the wheelhouse — download it with the same `--platform/--python-version` flags and
> re-upload. This is the main iteration loop.

---

## 4. Upload the wheelhouse to a UC Volume

```bash
# create the volume + folder (once)
databricks volumes create $CATALOG default lakebridge MANAGED -p $PROFILE
databricks fs mkdir dbfs:$WHEELS_VOL -p $PROFILE

# upload (parallelised — serial upload of ~90 wheels is slow)
ls /tmp/lb_wheels/*.whl | xargs -P 6 -I {} \
  databricks fs cp "{}" "dbfs:$WHEELS_VOL/$(basename {})" --overwrite -p $PROFILE

databricks fs ls dbfs:$WHEELS_VOL -p $PROFILE | wc -l    # should equal local count
```

---

## 5. Pre-create the reconcile backend

`configure-reconcile` normally creates these; do it by hand. The metadata **catalog +
schema must pre-exist** (result tables `main`/`metrics`/`details` auto-create via
`saveAsTable`). A **UC Volume is required even on classic compute** — intermediate data is
persisted to the volume whenever `DATABRICKS_RUNTIME_VERSION` is set, not just on serverless.

```bash
run_sql () { databricks api post /api/2.0/sql/statements -p $PROFILE --json \
  "{\"warehouse_id\":\"$SQL_WAREHOUSE_ID\",\"statement\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1"),\"wait_timeout\":\"30s\"}"; }

run_sql "CREATE SCHEMA IF NOT EXISTS $CATALOG.lb_recon"
databricks volumes create $CATALOG lb_recon reconcile_volume MANAGED -p $PROFILE
```

So the metadata config will be: catalog `kp_capri`, schema `lb_recon`, volume `reconcile_volume`.

---

## 6. Analyzer — in-workspace, offline

### 6a. Stage source metadata (exported SQL / ETL files) on a Volume

```bash
databricks fs mkdir dbfs:/Volumes/$CATALOG/default/lakebridge/input  -p $PROFILE
databricks fs mkdir dbfs:/Volumes/$CATALOG/default/lakebridge/output -p $PROFILE
# upload your .sql / ETL export files into .../input
databricks fs cp ./my_source.sql dbfs:/Volumes/$CATALOG/default/lakebridge/input/my_source.sql -p $PROFILE
```

### 6b. Analyzer notebook (`lakebridge_analyzer.py`)

```python
# Databricks notebook source
# Offline install from the UC-Volume wheelhouse (no internet on the cluster).
%pip install --no-index --find-links=/Volumes/kp_capri/default/lakebridge/wheels databricks-labs-lakebridge openpyxl
dbutils.library.restartPython()

# COMMAND ----------
import shutil, tempfile, json
from pathlib import Path
from databricks.labs.bladespector.analyzer import Analyzer     # NOT ApplicationContext

SOURCE_DIR = "/Volumes/kp_capri/default/lakebridge/input"
OUTPUT_DIR = "/Volumes/kp_capri/default/lakebridge/output"
PLATFORM   = "Oracle"     # must be in Analyzer.supported_source_technologies()

src, vol_out = Path(SOURCE_DIR), Path(OUTPUT_DIR)
local_out  = Path(tempfile.mkdtemp(prefix="lakebridge_"))   # seekable local scratch
local_xlsx = local_out / "report.xlsx"
local_json = local_out / "report.json"

assert src.is_dir() and any(src.iterdir()), f"empty/missing source dir: {src}"
vol_out.mkdir(parents=True, exist_ok=True)
assert PLATFORM in Analyzer.supported_source_technologies()

# write to LOCAL scratch first, then copy to the Volume (see gotcha below)
Analyzer.analyze(src, local_xlsx, PLATFORM, False, local_json)
assert local_xlsx.stat().st_size > 5000, "report looks corrupt (empty dir / wrong platform?)"
shutil.copy(local_xlsx, vol_out / "report.xlsx")
if local_json.exists(): shutil.copy(local_json, vol_out / "report.json")
print("done:", [p.name for p in vol_out.iterdir()])
```

### 6c. Run it as a one-off job on the classic cluster

```bash
databricks workspace import $USER_HOME/lakebridge_analyzer \
  --file ./lakebridge_analyzer.py --language PYTHON --format SOURCE --overwrite -p $PROFILE

cat > /tmp/analyzer_job.json <<EOF
{"run_name":"lakebridge-analyzer","tasks":[{"task_key":"analyze",
  "existing_cluster_id":"$CLUSTER_ID",
  "notebook_task":{"notebook_path":"$USER_HOME/lakebridge_analyzer"}}]}
EOF
databricks jobs submit --no-wait --json @/tmp/analyzer_job.json -p $PROFILE
# poll: databricks jobs get-run <run_id> -p $PROFILE --output json
```

**Verified result:** 4 Oracle files → `report.xlsx` (18.1 KB) + `report.json`, **14
worksheets** (Summary, SQL Programs, Loops & Cursors, Functions, Program-Object Xref, …).

---

## 7. Reconciler — in-workspace, offline (Databricks-to-Databricks)

This is the path proven live. External sources (Redshift) differ only in the `source`
block + a UC connection — see §8.

### 7a. Reconcile notebook (`lakebridge_reconcile.py`)

```python
# Databricks notebook source
%pip install --no-index --find-links=/Volumes/kp_capri/default/lakebridge/wheels databricks-labs-lakebridge
dbutils.library.restartPython()

# COMMAND ----------
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
    report_type="all",     # schema + row + data ("schema"|"data"|"row"|"all"|"aggregate")
    source=SourceConnectionConfig(
        dialect="databricks", catalog="kp_capri", schema="default",
        uc_connection_name=None),                 # None => databricks dialect
    target=TargetConnectionConfig(catalog="kp_capri", schema="default"),
    metadata_config=ReconcileMetadataConfig(
        catalog="kp_capri", schema="lb_recon", volume="reconcile_volume"),
)
table_recon = TableRecon(tables=[
    Table(source_name="customers_src", target_name="customers_tgt", join_columns=["id"]),
])

try:
    out = TriggerReconService.trigger_recon(ws, spark, table_recon, reconcile_config)
    print(json.dumps({"ok": True, "recon_id": out.recon_id, "repr": repr(out)[:2000]}))
    dbutils.notebook.exit(out.recon_id)
except ReconciliationException as e:
    print("RECON EXCEPTION:", e)
    raise
```

### 7b. Run it (same submit pattern as §6c, pointing at `lakebridge_reconcile`).

### 7c. Inspect results

```bash
run_sql "SELECT recon_metrics.row_comparison, recon_metrics.column_comparison
         FROM $CATALOG.lb_recon.metrics m
         JOIN $CATALOG.lb_recon.main mn ON m.recon_table_id = mn.recon_table_id
         WHERE mn.recon_id = '<recon_id>'"
```

**Verified result** (`recon_id=e360b2ba...`), with deliberate diffs planted in the demo data:
- `missing_in_target: 1` (row only in source), `missing_in_source: 1` (row only in target),
- `absolute_mismatch: 1, mismatch_columns: balance` (a changed value),
- schema matched (`schema=True`), so `status.row=False, column=False, schema=True`.

Result tables land in `kp_capri.lb_recon.{main, metrics, details}` keyed by `recon_id`.

---

## 8. Reconciling against an external Redshift source

Only the **source** side and one **UC connection** change; everything above (wheelhouse,
backend, target read, metadata) is identical.

### 8a. How it connects (important)

Despite the `JdbcReaderOptions` name, the Redshift connector does **not** open JDBC from the
notebook driver. Every read is rewritten into a Databricks **Lakehouse Federation**
`remote_query()` call and executed via `spark.sql`:

```sql
SELECT * FROM remote_query('<uc_connection>', database => '<db>', query => 'SELECT ... FROM schema.table')
```

The Databricks **compute plane** (not your notebook) connects to Redshift, runs the
read-only query in Redshift's engine, and returns a Spark DataFrame. Target-side reads and
the comparison/metadata writes are unchanged from §7. Net effect: **no extra cluster egress
for data** — only network reachability from Databricks compute to Redshift, plus the
already-solved offline package install.

### 8b. One-time: create the UC connection to Redshift

```sql
CREATE CONNECTION my_redshift_conn TYPE redshift
OPTIONS (
  host '<redshift-endpoint>',
  port '5439',
  user     secret('<scope>','<user-key>'),
  password secret('<scope>','<pwd-key>')
);
```

Requirements: UC metastore enabled; `CREATE CONNECTION` to create it, `USE CONNECTION` to
query it; **`remote_query` is a public-preview feature** needing **DBR 17.3+** (clusters) or
a Pro/Serverless SQL warehouse `2025.35+`; and **network routing (VPC/security groups)** from
Databricks compute to the Redshift cluster. `remote_query` is **read-only** (no
INSERT/UPDATE/DDL/procedures) — fine for reconcile.

### 8c. Change only the source block in the reconcile notebook

```python
source=SourceConnectionConfig(
    dialect="redshift",
    catalog="<redshift_database>",       # maps to remote_query's `database =>`
    schema="<redshift_schema>",
    uc_connection_name="my_redshift_conn",   # non-null => routes to RedshiftDataSource
),
target=TargetConnectionConfig(catalog="<dbx_catalog>", schema="<dbx_schema>"),
...
table_recon = TableRecon(tables=[
    Table(source_name="<redshift_table>", target_name="<dbx_table>", join_columns=["<pk>"]),
])
```

`initialise_data_source` uses a non-null `uc_connection_name` to select the
`RedshiftDataSource` adapter; leaving it `None` forces the `databricks` dialect.

Supported external dialects (same pattern, different `TYPE`/connection): `oracle`, `snowflake`,
`mssql`/`synapse`, `redshift`, `teradata`, `bigquery`.

---

## 9. Gotchas & fixes (all hit during verification)

| Symptom | Cause | Fix |
|---|---|---|
| `[Errno 101] Network is unreachable` on `%pip install` | Cluster has no internet | Offline wheelhouse on a UC Volume + `--no-index --find-links` (§3–4) |
| `%pip` fails with only `CalledProcessError ... exit status 1` | The `%pip` magic swallows pip's real stderr | Reproduce with `subprocess.run([sys.executable,"-m","pip",...], capture_output=True)` and print `stderr` |
| `Could not find a version that satisfies the requirement greenlet` (or other) | Transitive binary wheel missing from wheelhouse | `pip download <pkg>` with matching `--platform/--python-version`, re-upload |
| `NotADirectoryError: Cannot find project root` | Imported `ApplicationContext` | Call `databricks.labs.bladespector.analyzer.Analyzer.analyze(...)` directly |
| `report.xlsx` is ~390 bytes / corrupt | Wrote `.xlsx` straight to a UC Volume (FUSE can't do random-access seeks) | Write to local scratch (`tempfile.mkdtemp()`), then `shutil.copy` to the Volume |
| `/local_disk0` read-only | Serverless | Use `tempfile.mkdtemp()` (writes under `/tmp`); prefer classic cluster |
| `PERSIST TABLE not supported on serverless` (reconcile) | Reconcile on serverless | Run reconcile on a **classic cluster** / Pro warehouse |
| Reconcile fails writing intermediate data | Missing `reconcile_volume` even on classic | Create the UC Volume (§5) — required whenever `DATABRICKS_RUNTIME_VERSION` is set |
| Redshift recon: `remote_query` not recognised | Preview not enabled / old runtime | Enable `remote_query` preview; DBR 17.3+ or SQL warehouse `2025.35+` |
| `openpyxl` import error when inspecting the workbook | Not preinstalled on serverless | Add `openpyxl` to the `%pip install` line |

---

## 10. What lives where after a run

- **Notebooks:** `<USER_HOME>/lakebridge_analyzer`, `<USER_HOME>/lakebridge_reconcile`.
- **Wheelhouse:** `/Volumes/<catalog>/default/lakebridge/wheels` (~90 wheels).
- **Analyzer I/O:** `.../lakebridge/input` (sources), `.../lakebridge/output` (`report.xlsx` + `report.json`).
- **Reconcile backend:** schema `<catalog>.lb_recon` (tables `main`/`metrics`/`details`) + volume `reconcile_volume`.
- **UC connections** (external sources only): e.g. `my_redshift_conn`.

---

## 11. Reusing across a new workspace / release

1. Rebuild the wheelhouse for the target cluster's Python/OS (pin the Lakebridge version).
2. Re-upload wheels; re-create `lb_recon` schema + `reconcile_volume`.
3. For external sources, create the UC connection + enable `remote_query`.
4. Import the two notebooks; submit as one-off jobs on a classic cluster.

No CLI install, no `configure-reconcile`, no desktop app required at any point.
