# Regular in-workspace run (internet-connected compute)

Run the Lakebridge **Analyzer**, **Transpiler**, and **Reconciler** directly inside a
Databricks workspace notebook — no Databricks CLI (`labs install` / `configure-reconcile`),
no desktop app — on compute that **has outbound internet** (so `%pip install` reaches PyPI).

For **air-gapped** compute (no cluster internet), use the sibling
[`../airgapped-in-workspace`](../airgapped-in-workspace) folder instead.

## Notebooks

| File | Stage | Compute | Status |
|---|---|---|---|
| `lakebridge_analyzer.py`  | Assessment / Analyzer | Serverless or classic | ✅ Verified end-to-end (AWS + Azure) |
| `lakebridge_reconcile.py` | Reconciler            | **Classic cluster** (not serverless) | ✅ Verified end-to-end (D2D) |
| `lakebridge_transpile.py` | Transpiler (sqlglot engine) | Serverless or classic | ✅ Verified end-to-end (Azure); SQL-only — PL/SQL → Morpheus/Switch |

Each notebook has a **CONFIG cell** at the top; edit it and Run All.

## Why these work (shared gotchas)

1. **Call the engine directly — not `ApplicationContext`.** Importing
   `databricks.labs.lakebridge.contexts.application` fails in a notebook
   (`NotADirectoryError: Cannot find project root`). Analyzer → call
   `databricks.labs.bladespector.analyzer.Analyzer.analyze(...)`; Reconciler → call
   `TriggerReconService.trigger_recon(...)`.
2. **Analyzer report: write to local scratch, then copy to the Volume.** UC Volumes (FUSE)
   can't do the random-access writes the `.xlsx` (zip) writer needs — a direct write
   truncates to a ~390-byte corrupt stub. Write to `tempfile.mkdtemp()` then `shutil.copy`.
   (`/local_disk0` is read-only on serverless; `tempfile.mkdtemp()` uses `/tmp`.)
3. **Reconcile needs a classic cluster + pre-created backend.** Serverless fails the
   persist step (`PERSIST TABLE not supported on serverless`). Pre-create the metadata
   schema (`<catalog>.lb_recon`) and a UC Volume (`reconcile_volume`) — the bits
   `configure-reconcile` normally makes.
4. **Transpiler uses the pure-Python `sqlglot` engine** — no `install-transpile`, no Java.
   Wrap the async engine call with `nest_asyncio` (notebooks already run an event loop, so
   a bare `asyncio.run()` raises `cannot be called from a running event loop`). sqlglot is
   SQL-only; for PL/SQL procedural code use **Morpheus** (needs Java 21) or **Switch** (LLM
   job, token-metered). The productized **agentic converter** (`/migrate`) is recommended
   going forward.

## Reconciler notes

- External sources (Oracle/Snowflake/MSSQL/Synapse/Redshift/Teradata/BigQuery): set
  `DIALECT` and point `UC_CONNECTION` at a pre-created UC connection. Reads are executed
  by the Databricks compute plane via Lakehouse Federation `remote_query()` (read-only;
  needs DBR 17.3+ or SQL warehouse `2025.35+`). See `../airgapped-in-workspace/RUNBOOK.md`
  §8 for the external-source details.
- Results land in `<catalog>.lb_recon.{main, metrics, details}` keyed by `recon_id`.
