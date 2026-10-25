# Garmin ELT Pipeline

A data pipeline for extracting, loading, and transforming Garmin Connect data into a dimensional model on SQL Server using a modern ELT architecture.

## Data Flow & Architecture
The project follows a Metadata-Driven ELT approach, completely separating the Extraction/Load phase from the Transformation logic:

1. **Extraction (GarminDB CLI)**: The pipeline triggers the external `GarminDB` tool to synchronize the newest health and activity data from Garmin Connect APIs into local SQLite databases.
2. **Load (Python)**: An isolated Python module reads configuration data directly from SQL Server, extracts new records from SQLite, and performs a bulk insert (via `fast_executemany`) into the `stg` (Staging) schema in SQL Server.
3. **Transform (T-SQL)**: The transformation logic is fully pushed down to the database engine. A master stored procedure reads the metadata and generates dynamic, set-based `MERGE` statements to upsert data into the `src` (Target) schema.
4. **Aggregation**: Downstream analytical views and summary tables (`dbo` schema) are recalculated based on the latest watermarks.

## Project Structure
```text
├── database_setup/   # DDL scripts, table definitions, and CSV seed files (metadata)
├── extract/          # Python extraction module (loads data from SQLite to SQL Server)
├── logs/             # Pipeline execution logs (ignored by Git)
├── orchestration/    # Batch scripts (.bat) orchestrating the ELT process
├── transform/        # T-SQL scripts containing set-based transformations and views
├── .env.example      # Template for environment variables (DB connections, paths)
├── requirements.txt  # Python virtual environment dependencies
└── README.md         # Project documentation
```

## Prerequisites
* Python 3.10+
* SQL Server (Developer/Express) with ODBC Driver 17+
* [GarminDB](https://github.com/tcgoetz/GarminDB) configured and synced locally.

## Setup Instructions
1. Clone this repository.
2. Create a virtual environment and run `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and configure your database credentials and path settings (e.g. path to GarminDB scripts).
4. Run `deploy_db.bat` to build the SQL Server schemas and tables, and load the initial metadata configuration.

## Execution
Execute `orchestration/master_garmin_daily.bat` to run the daily pipeline.