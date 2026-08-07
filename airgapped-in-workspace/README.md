# Air-gapped in-workspace run (no cluster internet)

Run the Lakebridge **Analyzer** and **Reconciler** entirely inside a Databricks workspace
notebook on a workspace whose **compute has no outbound internet** — no Databricks CLI
(`labs install` / `configure-reconcile`), no desktop app.

The difference from [`../regular-in-workspace`](../regular-in-workspace) is **how the
package is installed**: instead of `%pip install databricks-labs-lakebridge` (which fails
with `[Errno 101] Network is unreachable`), you build a **wheelhouse** on a connected host,
upload it to a **UC Volume**, and install offline with
`%pip install --no-index --find-links=/Volumes/.../wheels ...`.

## Start here: `RUNBOOK.md`

**[`RUNBOOK.md`](./RUNBOOK.md)** is the full, verified end-to-end procedure. It covers:

- **§3–4** Build the wheelhouse (match the *cluster's* Python/OS — e.g. DBR 17.3 ⇒ cp312 /
  manylinux x86_64) and upload it to a UC Volume. Watch for missing transitive wheels
  (e.g. `greenlet`); the Analyzer engine ships in the `databricks_bb_analyzer` wheel.
- **§5** Pre-create the reconcile backend (metadata schema + `reconcile_volume`) — the bits
  `configure-reconcile` normally makes.
- **§6** Analyzer, offline. **§7** Reconciler, offline (Databricks-to-Databricks).
- **§8** Reconciling an external **Redshift** source via a UC connection + `remote_query`
  (DBR 17.3+); same pattern for oracle/snowflake/mssql/synapse/teradata/bigquery.
- **§9** Gotchas & fixes (all hit during verification).

> Verified end-to-end on 2026-07-30 (workspace `dbc-e8d3f54c-ce8c`, classic cluster,
> DBR 17.3, Databricks-to-Databricks). The Redshift path is documented from the connector
> source but was not run live.

## Notebooks (companions to the runbook)

| File | Stage | Notes |
|---|---|---|
| `lakebridge_analyzer_offline.py`  | Analyzer   | Offline `--no-index --find-links` install; RUNBOOK §6 |
| `lakebridge_reconcile_offline.py` | Reconciler | Offline install; classic cluster; RUNBOOK §5, §7, §8 |

Edit the CONFIG cell (wheelhouse path, catalog/schema/volume, tables) and run each as a
one-off job on the classic cluster. The offline `%pip` line has the wheelhouse path
hard-coded in the magic (magics can't read Python vars) — update it to match `WHEELS_DIR`.

## Key differences vs the regular folder

- **Install:** offline wheelhouse on a UC Volume, not PyPI.
- **Compute:** **classic cluster** required (serverless can't persist reconcile results and
  can't host a JDK). DBR **17.3+** if using `remote_query`/external sources.
- Everything else (engine calls, local-scratch-then-copy for the report, the reconcile
  backend layout) is identical to the regular path.
