# Lakebridge in workspace

Run the [Databricks Lakebridge](https://databrickslabs.github.io/lakebridge/) migration
tools — **Analyzer** (assessment), **Transpiler**, and **Reconciler** — directly inside a
Databricks workspace notebook. **No Databricks CLI** (`labs install` /
`configure-reconcile`), **no desktop app** — everything runs as notebooks/jobs in the
workspace by calling the Lakebridge engine classes directly.

## Which folder do I use?

| Your compute | Folder |
|---|---|
| Has outbound internet (`%pip install` reaches PyPI) | **[`regular-in-workspace/`](./regular-in-workspace)** |
| Air-gapped — no internet on the cluster | **[`airgapped-in-workspace/`](./airgapped-in-workspace)** |

The two folders share the same engine-call approach; they differ only in **how Lakebridge
is installed** (PyPI vs an offline wheelhouse on a UC Volume) and the required **compute**
(serverless is fine for the Analyzer; the Reconciler needs a classic cluster).

### `regular-in-workspace/`
- `lakebridge_analyzer.py` — Assessment/Analyzer. ✅ Verified end-to-end on **AWS** and **Azure**.
- `lakebridge_reconcile.py` — Reconciler (`TriggerReconService.trigger_recon`). ✅ Verified (D2D).
- `lakebridge_transpile.py` — Transpiler (pure-Python `sqlglot` engine, no Java). ✅ Verified end-to-end (Azure); SQL-only, route PL/SQL to Morpheus/Switch.

### `airgapped-in-workspace/`
- `RUNBOOK.md` — **the full verified offline procedure** (wheelhouse build/upload, backend
  pre-create, Analyzer + Reconciler, external Redshift source, gotchas). Start here.
- `lakebridge_analyzer_offline.py`, `lakebridge_reconcile_offline.py` — offline-install
  companions to the runbook.

## The three things that make in-workspace runs work

1. **Call the engine directly, not `ApplicationContext`** — importing the CLI's application
   context fails in a notebook (`NotADirectoryError: Cannot find project root`). Use
   `Analyzer.analyze(...)` and `TriggerReconService.trigger_recon(...)`.
2. **Analyzer report: write to local scratch, then copy to the Volume** — a direct `.xlsx`
   write to a UC Volume (FUSE) truncates to a ~390-byte corrupt stub. Use
   `tempfile.mkdtemp()` (`/local_disk0` is read-only on serverless), then `shutil.copy`.
3. **Reconciler: classic cluster + pre-created backend** — serverless can't run the persist
   step (`PERSIST TABLE not supported on serverless`); pre-create the metadata schema
   (`lb_recon`) and a UC Volume (`reconcile_volume`).

## Compute notes

- **Analyzer** runs on serverless or classic. On some workspaces serverless job runs hit a
  transient `Futures timed out after [80 seconds]` kernel-startup error — if that happens,
  run the same notebook on a **classic cluster** with no code changes.
- **Reconciler** requires a **classic cluster** (or Pro SQL warehouse). Use **DBR 17.3+** for
  external sources via `remote_query`/Lakehouse Federation.
- **Transpiler**: the notebook uses the pure-Python **`sqlglot`** engine (no Java, no
  `install-transpile`) — verified on serverless/classic. For PL/SQL procedural code beyond
  sqlglot's SQL scope, use **Morpheus** (needs Java 21) or **Switch** (LLM job, token-metered);
  the productized **agentic converter** (`/migrate`) is recommended going forward.
