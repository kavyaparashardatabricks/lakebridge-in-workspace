# Lakebridge Analyzer — in workspace

Run the [Databricks Lakebridge](https://databrickslabs.github.io/lakebridge/) **Assessment / Analyzer**
directly inside a Databricks workspace, from a **serverless Python notebook** — no
Databricks CLI and no desktop app required.

The Analyzer scans exported source-system metadata (SQL files, or ETL repo exports such
as Informatica / SSIS / DataStage XML/JSON), scores job/query complexity, inventories
objects, and maps interdependencies. It produces an Excel report (`.xlsx`) and,
optionally, a JSON report.

## What's here

- **`lakebridge analyzer in workspace.py`** — a Databricks notebook (source format) that
  installs Lakebridge, runs the Analyzer against a folder of source files staged on a
  Unity Catalog Volume, and writes the report back to a Volume.

## Prerequisites

- A Databricks workspace with **serverless** notebook compute.
- A **Unity Catalog Volume** to hold the input source files and the output report.
- Exported source metadata staged in the input Volume folder (e.g. Oracle `.sql` files).

## Usage

1. Import the notebook into your workspace:
   - **UI:** Workspace → Import → select `lakebridge analyzer in workspace.py`, or
   - **CLI:**
     ```bash
     databricks workspace import "/Users/<you>/lakebridge analyzer in workspace" \
       --file "lakebridge analyzer in workspace.py" \
       --language PYTHON --format SOURCE
     ```
2. Attach the notebook to **Serverless** compute.
3. Edit the **CONFIG** cell:
   - `SOURCE_DIR`  — Volume folder of source files, e.g. `/Volumes/<catalog>/<schema>/<volume>/input`
   - `OUTPUT_DIR`  — Volume folder for the report, e.g. `/Volumes/<catalog>/<schema>/<volume>/output`
   - `PLATFORM`    — source technology (must match `Analyzer.supported_source_technologies()`,
                     printed at runtime), e.g. `"Oracle"`, `"Snowflake"`, `"Teradata"`, `"SSIS"`, …
   - `GENERATE_JSON` — `True` to also emit `report.json`
4. **Run All.** The report lands at `OUTPUT_DIR/report.xlsx` (and `report.json`).

## Why it's built this way (serverless gotchas)

These three points are the difference between a working run and a silent failure:

1. **Call the `bladespector` engine directly — not `ApplicationContext`.**
   Importing `databricks.labs.lakebridge.contexts.application` triggers blueprint's
   `find_project_root()`, which fails in a notebook (`NotADirectoryError: Cannot find
   project root`) because the package lives in `site-packages` with no project marker.
   That context object only exists to wire up interactive CLI prompts. The notebook calls
   `Analyzer.analyze(source_dir, results_file_path, platform, is_debug, json_result)`
   instead.

2. **Write the report to local scratch first, then copy to the Volume.**
   Unity Catalog Volumes are a FUSE mount that can't do the random-access seeks the
   `.xlsx` (zip) writer needs. Writing straight to a Volume truncates the file to a
   ~390-byte corrupt stub. The notebook writes to local scratch and then `shutil.copy`s
   the finished files to the Volume.

3. **Use `tempfile.mkdtemp()` for scratch, not `/local_disk0`.**
   `/local_disk0` is read-only on serverless compute. `tempfile.mkdtemp()` writes under
   `/tmp`, which is writable.

Also: `openpyxl` isn't preinstalled on serverless, so it's added to the `%pip install`
line for the workbook-inspection cell.

## Report contents

The generated workbook contains worksheets such as: **Summary**, **SQL Programs**
(per-script complexity), **SQL Script Categories**, **Functions** / **Functions by
Script**, **Referenced Objects**, **Program-Object Xref**, **Loops & Cursors**,
**Conditionals**, and **SQL Data Types**.

## Verified

Confirmed working end-to-end on serverless notebook compute against 125 Oracle `.sql`
files, producing a ~58 KB `report.xlsx` (14 worksheets) and a ~116 KB `report.json`.
bladespector engine v5.6.6. No JDK was required (the Analyzer path is pure Python).
