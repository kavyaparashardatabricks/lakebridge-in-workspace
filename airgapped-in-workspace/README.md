# Air-gapped in-workspace run (no internet on the cluster)

Run all three Lakebridge tools inside a Databricks workspace whose clusters **have no internet** —
no Databricks CLI install, no desktop app. Everything is a notebook you import and run.

The only difference from the [`../regular-in-workspace`](../regular-in-workspace) folder is **how
Lakebridge gets installed**: the cluster can't reach PyPI, so you download the package once on a
laptop, copy it to a Unity Catalog volume, and install it from there.

## 👉 Start with [`RUNBOOK.md`](./RUNBOOK.md)

It's a plain, step-by-step walkthrough — from downloading the package to running each tool. Follow
it top to bottom the first time.

## The notebooks

| Notebook | What it does |
|---|---|
| [`lakebridge_analyzer_offline.py`](./lakebridge_analyzer_offline.py)   | **Analyzer** — scans source SQL/ETL files, scores the migration (Excel report) |
| [`lakebridge_reconcile_offline.py`](./lakebridge_reconcile_offline.py) | **Reconciler** — checks a source table and a Databricks table match |
| [`lakebridge_profiler_offline.py`](./lakebridge_profiler_offline.py)   | **Profiler** — captures source DB sizing/usage into a DuckDB extract (for TCO) |

For each one: **import it → edit the CONFIG cell at the top → Run All** on a classic cluster.

## The essentials (all explained in the RUNBOOK)

- **Install offline.** Download the package on a laptop, upload the "wheelhouse" to a UC volume,
  and install with `%pip install --no-index --find-links=/Volumes/.../wheels ...`.
- **Use a classic cluster, DBR 17.3+.** Serverless can't run the Reconciler or Profiler.
- **Reports write to local disk first, then copy to the volume** (UC Volumes can't do the
  in-place writes the Excel/DuckDB writers need).
- **Reaching an outside database:** the Reconciler uses a UC connection (Lakehouse Federation);
  the Profiler connects directly, so the cluster needs a network route to that database. See the
  RUNBOOK's "Connecting to an outside database" section.

> ✅ Verified end-to-end on **Lakebridge 0.15.0**, DBR 17.3, in an air-gapped workspace —
> Analyzer, Reconciler, and Profiler (against a private Redshift) all pass.
