# Regular in-workspace run (internet-connected compute)

Run the Lakebridge **Analyzer** and **Reconciler** directly inside a
Databricks workspace notebook — no Databricks CLI (`labs install` / `configure-reconcile`),
no desktop app — on compute that **has outbound internet** (so `%pip install` reaches PyPI).

For the **Profiler** (which connects directly to a source database and emits a DuckDB extract),
see the offline notebook in [`../airgapped-in-workspace`](../airgapped-in-workspace).

For **air-gapped** compute (no cluster internet), use the sibling
[`../airgapped-in-workspace`](../airgapped-in-workspace) folder instead.

## Notebooks

| File | Stage | Compute | Status |
|---|---|---|---|
| `lakebridge_analyzer.py`  | Assessment / Analyzer | Serverless or classic | ✅ Verified end-to-end (AWS + Azure) |
| `lakebridge_reconcile.py` | Reconciler            | **Classic cluster** (not serverless) | ✅ Verified end-to-end (D2D) |

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

## Reconciler notes

- External sources (Oracle/Snowflake/MSSQL/Synapse/Redshift/Teradata/BigQuery): set
  `DIALECT` and point `UC_CONNECTION` at a pre-created UC connection. Reads are executed
  by the Databricks compute plane via Lakehouse Federation `remote_query()` (read-only;
  needs DBR 17.3+ or SQL warehouse `2025.35+`). See `../airgapped-in-workspace/RUNBOOK.md`
  §8 for the external-source details.
- Results land in `<catalog>.lb_recon.{main, metrics, details}` keyed by `recon_id`.
