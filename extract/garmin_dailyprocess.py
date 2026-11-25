import os
import sys
import urllib.parse
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SAWarning
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=SAWarning)

def log(message: str, is_error: bool = False) -> None:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = "[!]" if is_error else "[i]"
    print(f"[{timestamp}] {prefix} {message}")

# --- Load config
load_dotenv()

DB_SERVER = os.getenv("SQL_SERVER")
DB_NAME = os.getenv("SQL_DATABASE")
DB_DRIVER = os.getenv("SQL_DRIVER")
SQLITE_DIR = os.getenv("GARMIN_SQLITE_DIR")

if not all([DB_SERVER, DB_NAME, DB_DRIVER, SQLITE_DIR]):
    log("Missing environment variables in .env file.", is_error=True)
    sys.exit(1)

params = urllib.parse.quote_plus(
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"Trusted_Connection=yes;"
    f"TrustServerCertificate=yes;"
)
sql_engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)

log("Fetching Stage configuration from SQL Server...")

config_query = text("""
    SELECT SourceDB, SourceTableName, StageSchema, StageTableName, 
           TargetSchema, TargetTableName, LoadType, MergeKey, 
           WatermarkColumn, WatermarkType
    FROM [acc].[SrcTableConfig] 
    WHERE ActiveInd = 1
""")

try:
    with sql_engine.connect() as conn:
        result = conn.execute(config_query)
        config_rows = [dict(row._mapping) for row in result]
except Exception as e:
    log(f"CRITICAL ERROR fetching configuration: {e}", is_error=True)
    sys.exit(1)

if not config_rows:
    log("No active configuration found in [acc].[SrcTableConfig]. Exiting.")
    sys.exit(0)

# --- EXTRACT & LOAD
total_tables = len(config_rows)

for index, row in enumerate(config_rows):
    source_db_name = row['SourceDB']
    source_table = row['SourceTableName']
    stage_schema = row['StageSchema']
    stage_table = row['StageTableName']
    target_schema = row['TargetSchema']
    target_table = row['TargetTableName']
    load_type = str(row['LoadType']).lower()
    
    wm_col = row['WatermarkColumn']
    wm_type = str(row['WatermarkType']).lower() if row['WatermarkType'] is not None else None
    
    sqlite_path = os.path.join(SQLITE_DIR, f"{source_db_name}.db")
    
    log(f"[{index+1}/{total_tables}] Processing: {source_db_name}.{source_table} -> [{stage_schema}].[{stage_table}]")
    
    if not os.path.exists(sqlite_path):
        log(f"SKIPPED: SQLite DB file not found at '{sqlite_path}'", is_error=True)
        continue
    
    sqlite_query = f"SELECT * FROM [{source_table}]"
    
    # Incremental extraction based on Watermark
    if load_type == 'merge' and wm_col and wm_type in ('date', 'id'):
        try:
            watermark_query = text(f"SELECT MAX([{wm_col}]) FROM [{target_schema}].[{target_table}]")
            with sql_engine.connect() as conn:
                max_val = conn.execute(watermark_query).scalar()
            
            if max_val is not None:
                if wm_type == 'date':
                    cutoff_date = pd.to_datetime(max_val) - timedelta(days=3)
                    cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S') if len(str(max_val)) > 10 else cutoff_date.strftime('%Y-%m-%d')
                    sqlite_query = f"SELECT * FROM [{source_table}] WHERE [{wm_col}] >= '{cutoff_str}'"
                    log(f"MODE 2 (Date Delta). Watermark cutoff: {cutoff_str}")
                elif wm_type == 'id':
                    sqlite_query = f"SELECT * FROM [{source_table}] WHERE [{wm_col}] > {max_val}"
                    log(f"MODE 3 (ID Delta). Watermark cutoff: > {max_val}")
        except Exception as e:
            log(f"Watermark evaluation failed for [{target_schema}].[{target_table}]: {e}", is_error=True)
            sys.exit(1)

    # Read from SQLite
    try:
        with sqlite3.connect(sqlite_path) as sqlite_conn:
            df_source = pd.read_sql_query(sqlite_query, sqlite_conn)
            rows_count = len(df_source)
    except Exception as e:
        log(f"SQLite extraction failed for {source_table}: {e}", is_error=True)
        continue

    if rows_count == 0:
        log("No new or updated records found. Skipping.")
        continue

    # Load to SQL Server (Stg Schema)
    # 1. Dynamically downcast float64 columns back to nullable Int64 if they contain only integers
    for col in df_source.select_dtypes(include=['float64']).columns:
        if df_source[col].dropna().apply(lambda x: x.is_integer()).all():
            df_source[col] = df_source[col].astype('Int64')
    
    # 2. Clean purely temporal NaT without forcing the entire DataFrame into an 'object' type
    df_source = df_source.replace({pd.NaT: None})

    try:
        with sql_engine.begin() as conn:
            df_source.to_sql(
                name=stage_table, 
                con=conn, 
                schema=stage_schema, 
                if_exists='replace', 
                index=False
            )
        log(f"Loaded {rows_count} rows into [{stage_schema}].[{stage_table}].")
    except Exception as e:
        log(f"ERROR writing to SQL Server [{stage_schema}].[{stage_table}]: {e}", is_error=True)
        sys.exit(1)

# --- TRIGGER MASTER ELT PROCEDURE ---
trigger_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
print(f"\n[{trigger_time}] Triggering Master ELT Procedure in SQL Server...")
try:
    with sql_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("EXEC [dbo].[p_MasterDataLoad]"))
    end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{end_time}] [+] Master ELT Procedure executed successfully.")
except Exception as e:
    err_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{err_time}] [!] ERROR executing Master ELT Procedure: {e}")
    sys.exit(1)