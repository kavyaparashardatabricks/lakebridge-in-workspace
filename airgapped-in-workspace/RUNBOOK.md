# Running Lakebridge in an air-gapped Databricks workspace — step by step

This is a plain, follow-along guide for running the four Lakebridge tools **inside a Databricks
workspace whose clusters have no internet**:

- **Analyzer** — scans your old SQL/ETL files and scores the migration effort (Excel report).
- **Transpiler** — rewrites source SQL (Redshift, Oracle, …) into Databricks SQL.
- **Reconciler** — checks that a source table and a Databricks table hold the same data.
- **Profiler** — connects to your source database and captures sizing/usage stats (for TCO).

No Databricks CLI `labs install`, no `configure-reconcile`, no desktop app. Everything runs as
notebooks. The only trick for an air-gapped cluster is **how you install Lakebridge**: because the
cluster can't reach the internet, you download the package once on a normal machine, copy it into
the workspace, and install it from there.

> ✅ Verified end-to-end on **Lakebridge 0.15.0**, DBR 17.3, a classic cluster in an air-gapped
> (no-internet) workspace — Analyzer, Transpiler, Reconciler (Databricks-to-Databricks), and
> Profiler (against a private Redshift) all pass.

---

## Before you start

You need:

1. **A machine with internet** (your laptop) that has Python + `pip` and the
   [Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html) configured with a
   profile for your workspace. In the commands below that profile is called `WS`.
2. **A classic cluster** in the workspace running **DBR 17.3 or newer**. (Serverless won't work for
   the Reconciler or Profiler.) Note its **cluster id**.
3. **A Unity Catalog volume** you can write to. We'll use `/Volumes/<catalog>/default/lakebridge/`
   in the examples — replace `<catalog>` with your catalog name everywhere.

Two facts that explain the whole approach:

- The cluster's Python is **3.12** on **Linux x86_64** (that's what DBR 17.3 ships). The offline
  package files ("wheels") you download must match that, so we tell `pip` to fetch `cp312` /
  `manylinux` wheels.
- Unity Catalog Volumes are a network file share that can't do the "random-access" writes some file
  formats need. So whenever a tool writes a report/extract, we write it to the cluster's local disk
  first and then copy the finished file onto the Volume.

---

## Part A — One-time setup

Do this once. It gets Lakebridge onto the cluster and creates the folders the tools use.

### Step 1 — Download Lakebridge on your laptop (the "wheelhouse")

On your internet-connected laptop:

```bash
mkdir -p /tmp/lb_wheels
pip download databricks-labs-lakebridge openpyxl greenlet \
  --dest /tmp/lb_wheels \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
  --python-version 312 --implementation cp --only-binary=:all:
ls /tmp/lb_wheels/*.whl | wc -l      # ~90 files
```

That folder ("wheelhouse") holds Lakebridge plus every library it depends on. A few notes:

- The three `--platform` flags matter: newer dependencies (e.g. `duckdb`, used by the Profiler)
  only ship `manylinux_2_28` wheels. Leaving that flag out gives a "no matching distribution" error.
- `greenlet` is a dependency that `pip download` sometimes skips on a Mac — listing it explicitly
  makes sure it's included.
- **Don't pin extra versions** (like `duckdb==…`) on this line — let Lakebridge choose its own; the
  Profiler's needs (`redshift_connector`, `duckdb`, `sqlalchemy`) come along automatically.

### Step 2 — Copy the wheelhouse into the workspace

```bash
export WHEELS=/Volumes/<catalog>/default/lakebridge/wheels
databricks fs mkdir "dbfs:$WHEELS" -p WS
# upload all the wheels (parallel; a serial upload of ~90 files is slow)
ls /tmp/lb_wheels/*.whl | xargs -P 6 -I {} \
  databricks fs cp "{}" "dbfs:$WHEELS/$(basename {})" --overwrite -p WS
# sanity check: the count here should equal the local count
databricks fs ls "dbfs:$WHEELS" -p WS | grep -c '\.whl$'
```

> Tip: parallel uploads occasionally drop a file or two — if the counts don't match, re-run the
> upload for the missing ones.

### Step 3 — Create the folders and the reconcile backend

```bash
# input/output folders the notebooks use
databricks fs mkdir "dbfs:/Volumes/<catalog>/default/lakebridge/input"  -p WS
databricks fs mkdir "dbfs:/Volumes/<catalog>/default/lakebridge/output" -p WS

# the Reconciler needs a metadata schema + a volume (this is what `configure-reconcile` normally makes)
databricks schemas create lb_recon <catalog> -p WS
databricks volumes create <catalog> lb_recon reconcile_volume MANAGED -p WS
```

You're set up. From here, each tool is just: **import the notebook → edit the CONFIG cell → Run All.**

---

## How to run any of the notebooks

Each tool below is a notebook in this folder. For every one:

1. Import it into the workspace (UI: **Workspace → Import**, or the CLI below).
2. Open it, edit the **CONFIG** cell at the top (paths, catalog, etc.).
3. Attach it to your **classic cluster** and **Run All** — or submit it as a one-off job:

```bash
databricks workspace import "/Users/<you>/lakebridge_analyzer" \
  --file ./lakebridge_analyzer_offline.py --language PYTHON --format SOURCE --overwrite -p WS

databricks jobs submit -p WS --json '{
  "run_name": "lakebridge-analyzer",
  "tasks": [{"task_key":"run","existing_cluster_id":"<cluster-id>",
             "notebook_task":{"notebook_path":"/Users/<you>/lakebridge_analyzer"}}]}'
```

> **One thing to remember:** the `%pip install` line inside each notebook has the wheelhouse path
> written into it directly (a `%pip` line can't read a Python variable). If you change `WHEELS_DIR`
> in the CONFIG cell, update that `%pip` line to match.

---

## Part B — Run the four tools

### 1. Analyzer — `lakebridge_analyzer_offline.py`

Point it at a folder of exported source SQL files and it produces `report.xlsx` (a multi-tab
Excel workbook scoring the migration) plus `report.json`.

- Put your exported `.sql` files in `.../lakebridge/input`.
- In CONFIG set `PLATFORM` to your source — e.g. `"Redshift"`, `"Oracle"`, `"Snowflake"`
  (the notebook prints the full list of valid names and checks yours).
- Run it. You'll get `report.xlsx` + `report.json` in `.../lakebridge/output`.

### 2. Transpiler — `lakebridge_transpile_offline.py`

Rewrites every `.sql` file in the input folder into Databricks SQL.

- In CONFIG set `SRC_DIALECT` (e.g. `"redshift"`) and leave `TGT_DIALECT="databricks"`.
- Run it. Converted files land in `.../lakebridge/transpiled`, and it prints how many statements
  converted and any errors per file.
- It uses the built-in **sqlglot** engine (pure Python, no Java, no internet). It handles ordinary
  SQL well (e.g. `NVL`→`COALESCE`, `GETDATE()`→`CURRENT_TIMESTAMP()`). Procedural PL/SQL blocks
  come out only partly converted — check the error count and hand those to Morpheus/Switch.

### 3. Reconciler — `lakebridge_reconcile_offline.py`

Compares a source table and a target table (schema, row counts, and values) and writes the results
to `<catalog>.lb_recon.{main, metrics, details}`.

- Simplest case (**Databricks-to-Databricks**): leave `DIALECT="databricks"` and
  `UC_CONNECTION=None`, list your `(source_table, target_table, [join_columns])` in `TABLES`, run it.
- Reading from an **outside database** (Redshift, Oracle, …): see **Part C** below.
- Must run on the **classic cluster** (serverless can't save the results).

### 4. Profiler — `lakebridge_profiler_offline.py`

Connects to your source database and captures sizing/usage stats into a **DuckDB file**
(`profiler_extract_<source>_<version>_<date>.db`) you can feed into the TCO tooling.

- Unlike the other tools, the Profiler **connects directly to the source database** — so the
  cluster needs a **network route to it** (see Part C).
- Put the database connection details in a **secret scope** (the notebook's CONFIG cell shows the
  exact `databricks secrets` commands). Never hard-code the password.
- Run it. It prints the tables captured and copies the `.db` extract to `.../lakebridge/profiler`.

---

## Part C — Connecting to an outside database (Redshift, Oracle, Snowflake, …)

Two of the tools can talk to a non-Databricks source, and they do it **differently**:

| Tool | How it connects | What it needs |
|---|---|---|
| **Reconciler** | Through Databricks **Lakehouse Federation** — a `remote_query()` run by the Databricks compute plane via a **UC connection**. | A UC connection (below), DBR 17.3+. |
| **Profiler** | A **direct** connection from the cluster to the database (e.g. Redshift port 5439). | A **network route** from the workspace's compute network to the database (VPC peering / PrivateLink / a security-group rule). No internet. |

### Create a UC connection (for the Reconciler)

Run this once (SQL editor or a notebook). Store the credentials as Databricks secrets first.

```sql
CREATE CONNECTION my_redshift_conn TYPE redshift
OPTIONS (
  host '<redshift-endpoint>',
  port '5439',
  user     secret('<scope>','<user-key>'),
  password secret('<scope>','<password-key>')
);
```

Then in the Reconciler CONFIG set `DIALECT="redshift"` and `UC_CONNECTION="my_redshift_conn"`.
The same pattern works for `oracle`, `snowflake`, `mssql`/`synapse`, `teradata`, `bigquery`.

### Make sure the network path exists (for the Profiler, and for the Reconciler's reads)

Because the source database is usually private too, the workspace's compute network must be able to
reach it. Typical options (ask your cloud/network admin):

- **VPC peering** between the workspace network and the database's network, plus a firewall/
  security-group rule allowing the database port (Redshift is `5439`).
- Or a **PrivateLink / managed endpoint** to the database.

A quick way to confirm the path works from a notebook cell:

```python
import socket; socket.create_connection(("<db-host>", 5439), timeout=10)
print("reachable")   # no error = the cluster can reach the database
```

---

## Troubleshooting (the things that actually go wrong)

| What you see | Why | Fix |
|---|---|---|
| `%pip install` fails with `[Errno 101] Network is unreachable` | You installed from PyPI, not the offline wheelhouse | Use the `--no-index --find-links=<wheelhouse>` line (that's what the notebooks do) |
| `%pip` only says `CalledProcessError ... exit status 1` | The `%pip` magic hides pip's real error | Re-run the install with `subprocess` and print `stderr` to see the actual missing package |
| `Could not find a version that satisfies the requirement <pkg>` | That package is missing from the wheelhouse (or a wrong platform) | On your laptop, `pip download <pkg>` with the same `--platform/--python-version` flags and re-upload |
| `No matching distribution found for duckdb~=1.4.5` | Missing the newer glibc platform tag | Add `--platform manylinux_2_28_x86_64` to the Step 1 download |
| `NotADirectoryError: Cannot find project root` | You imported the CLI's `ApplicationContext` | Call the engine classes directly (the notebooks already do this) |
| `report.xlsx` is ~390 bytes / corrupt | Wrote the Excel file straight to a Volume | Write to local scratch first, then copy to the Volume (the notebooks do this) |
| `PERSIST TABLE not supported on serverless` (Reconciler) | Ran on serverless | Use a **classic cluster** |
| Reconciler fails writing intermediate data | Missing the `reconcile_volume` | Create it (Part A, Step 3) |
| `WriteToTableException: schema mismatch ... lb_recon.details` | The `lb_recon` result tables were made by an older Lakebridge version | Drop `lb_recon.{main,metrics,details}` and re-run so the new version recreates them |
| Reconciler with a Redshift source: `remote_query` not recognised | Feature not enabled / old runtime | Use DBR 17.3+ (or a Pro/Serverless SQL warehouse `2025.35+`) |
| Profiler: `cannot import name 'DatabaseManager'` | Lakebridge 0.15.0 renamed it | Use `create_connector(...)` (the notebook already handles both versions) |
| Profiler can't connect to the database | No network route from the cluster to the source | Set up VPC peering / PrivateLink + a firewall rule (Part C) |

---

## What lives where after a run

- **Wheelhouse:** `/Volumes/<catalog>/default/lakebridge/wheels`
- **Analyzer:** input `.../input`, output `.../output` (`report.xlsx` + `report.json`)
- **Transpiler:** output `.../transpiled`
- **Reconciler:** results in `<catalog>.lb_recon.{main, metrics, details}`
- **Profiler:** `.../profiler/profiler_extract_<source>_<version>_<date>.db`
- **UC connections** (external sources): e.g. `my_redshift_conn`
