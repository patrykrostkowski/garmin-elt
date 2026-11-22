# Garmin ELT Pipeline

A metadata-driven ELT pipeline for extracting, loading, and transforming Garmin Connect data into a dimensional model on SQL Server, with an optional serving layer that publishes curated CSV snapshots to Google Drive for downstream AI health and training analysis (e.g., Google Gemini combined with custom skill and .md training log files, located at Drive).

## Data Flow & Architecture
The project follows a Metadata-Driven ELT approach, separating Extraction/Load, Transformation, and Serving responsibilities:

1. **Extraction (GarminDB CLI)**: Triggers the external `GarminDB` tool to synchronize the latest health and activity data from Garmin Connect into local SQLite databases.
2. **Load (Python)**: `extract/garmin_dailyprocess.py` reads active table metadata from `[acc].[SrcTableConfig]`, extracts incremental or full batches from SQLite, and loads them into the `stg` (Staging) schema in SQL Server using `fast_executemany`.
3. **Transform (T-SQL)**: Transformation logic is pushed down to SQL Server via `[dbo].[p_MasterDataLoad]`, which executes set-based `MERGE` statements into the `src` (Target) schema.
4. **Aggregation & Serving Views (T-SQL)**: Downstream summary tables (`dbo` schema), sport classification metadata (`[acc].[SportCategoryMap]`), and rolling export views (`dbo.v_Export_*`) compute clean daily, activity, and weekly metrics (RHR/HRV baselines, CTL/ATL/TSB, ACWR, readiness, WHO intensity minutes).
5. **Export to Google Drive (Python, Optional)**: `export/export_to_gdrive.py` queries the serving views, writes local CSV snapshots to `export/output/`, and updates the target CSV files **in place** via Google Drive API v3 (preserving Drive `fileId`s for connected AI tools).

## Analytical Serving Layer (Google Drive Snapshots)
Three rolling views in the `dbo` schema feed the CSV snapshots consumed by external analytics or AI coaching assistants (such as Gemini):

| SQL View | Exported File | Scope & Key Metrics |
| :--- | :--- | :--- |
| `dbo.v_Export_DailyHealth_90d` | `daily_health_90d.csv` | 90-day daily recovery & load: sleep stages/score, RHR & 30d baseline, HRV (overnight/7d/28d/status), stress, Body Battery, weight, steps, 42d CTL, 7d ATL, TSB, load & kcal ACWR, custom readiness score, WHO rolling 7d intensity. |
| `dbo.v_Export_Activities_90d` | `activities_90d.csv` | 90-day workout log joined with `[acc].[SportCategoryMap]`: category, macro group, foot impact, duration, distance, ascent, HR, cadence, training load, aerobic/anaerobic TE, self-eval feel/effort, activity description, HR zone method & time in zones. |
| `dbo.v_Export_WeeklySummary_16w` | `weekly_summary_16w.csv` | 16-week ISO macro trends: session counts by discipline and high foot-impact exposure, cycling/hiking volume, weekly training load, WHO goal completion, recovery averages, and week-end ACWR. |

*Note:* Non-workout entries (`transition`, `training/breathing`, and sessions under 60 seconds) are excluded from the export views, and rolling averages use an extended lookback buffer (134–160 days) prior to final filtering to prevent cold-start bias.

## Project Structure
```text
├── database_setup/   # DDL scripts, table definitions, lookup seeds (e.g. SportCategoryMap)
├── export/           # Google Drive CSV export module (credentials, token, output ignored by Git)
├── extract/          # Python extraction module (loads data from SQLite to SQL Server)
├── logs/             # Pipeline execution logs (ignored by Git)
├── orchestration/    # Batch scripts (.bat) orchestrating the 3-step ELT + Export process
├── transform/        # T-SQL scripts containing set-based transformations and analytical views
├── .env.example      # Template for environment variables (DB connections, paths, Drive config)
├── .gitignore        # Excludes secrets (.env, credentials.json, token.json), logs, and local outputs
├── requirements.txt  # Python virtual environment dependencies
└── README.md         # Project documentation
```

## Prerequisites
* Python 3.10+
* SQL Server (Developer/Express) with ODBC Driver 17+
* [GarminDB](https://github.com/tcgoetz/GarminDB) configured and synced locally
* *(Optional, for Step 3)* A Google Cloud project with **Google Drive API** enabled and an OAuth 2.0 **Desktop app** client credential

## Setup Instructions

### 1. Core ELT Setup
1. Clone this repository.
2. Create a virtual environment (`.venv`) and install dependencies:
   ```cmd
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and configure your SQL Server connection details and local GarminDB paths.
4. Run `deploy_db.bat` to build the SQL Server schemas, tables, metadata seeds (`[acc].[SrcTableConfig]`, `[acc].[SportCategoryMap]`, `[acc].[AnalyticsWeights]`), stored procedures, and views.

### 2. Google Drive Export Setup (Optional)
1. In Google Cloud Console, enable **Google Drive API**, configure the OAuth consent screen (`External`), and create an **OAuth Client ID** of type **Desktop app**.
2. Download the client JSON file and save it locally as `export/credentials.json` (git-ignored).
3. In `.env`, set:
   ```dotenv
   ENABLE_GDRIVE_EXPORT=true
   GDRIVE_FOLDER_ID=YOUR_GOOGLE_DRIVE_FOLDER_ID
   GDRIVE_CREDENTIALS_PATH=export/credentials.json
   GDRIVE_TOKEN_PATH=export/token.json
   ```
   *(Use only the raw folder ID from the Drive URL, without query parameters such as `?hl=pl`.)*
4. Run the export script once interactively to complete the OAuth browser flow and generate `export/token.json`:
   ```cmd
   .\.venv\Scripts\python.exe .\export\export_to_gdrive.py
   ```
   *Tip:* Leaving the OAuth consent screen in **Testing** mode causes Google to expire refresh tokens every 7 days. Switching the app to **In production** (no Google verification required for personal use) keeps `token.json` valid long-term.

## Execution

* **Full daily pipeline (GarminDB → SQL Server → Google Drive):**
  ```cmd
  orchestration\master_garmin_daily.bat
  ```
  *Step 3 is non-blocking:* if the Google Drive upload fails (e.g., offline or expired token), the batch script logs a warning while preserving the completed local SQL Server update.

* **Local ELT only (skip Google Drive upload for a single run):**
  ```cmd
  orchestration\master_garmin_daily.bat --no-drive
  ```
  *(To disable Drive sync permanently, set `ENABLE_GDRIVE_EXPORT=false` in `.env`.)*

* **Standalone export / local CSV validation (without re-running GarminDB or SQL ELT):**
  ```cmd
  .\.venv\Scripts\python.exe .\export\export_to_gdrive.py --local-only
  .\.venv\Scripts\python.exe .\export\export_to_gdrive.py
  ```