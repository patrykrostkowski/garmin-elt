import os
import urllib
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# --- Load config
load_dotenv()

DB_SERVER = os.getenv("SQL_SERVER")
DB_NAME = os.getenv("SQL_DATABASE")
DB_DRIVER = os.getenv("SQL_DRIVER")
SQLITE_DIR = os.getenv("GARMIN_SQLITE_DIR")

if not all([DB_SERVER, DB_NAME, DB_DRIVER, SQLITE_DIR]):
    raise ValueError("Missing environment variables. Check .env file.")

params = urllib.parse.quote_plus(f"DRIVER={{{DB_DRIVER}}};SERVER={DB_SERVER};DATABASE={DB_NAME};Trusted_Connection=yes;")
sql_engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)

start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
print(f"[{start_time}] Fetching Stage configuration from SQL Server...")

# --- GET CONFIGURATION ---
config_query = """
    SELECT SourceDB, SourceTableName, StageSchema, StageTableName, 
           TargetSchema, TargetTableName, LoadType, MergeKey, 
           WatermarkColumn, WatermarkType
    FROM [acc].[SrcTableConfig] 
    WHERE ActiveInd = 1
"""

try:
    with sql_engine.connect() as conn:
        df_config = pd.read_sql(text(config_query), conn)
except Exception as e:
    err_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{err_time}] CRITICAL ERROR fetching configuration: {e}")
    exit(1)

# --- EXTRACT & LOAD ---
for index, row in df_config.iterrows():
    source_db_name = row['SourceDB']
    source_table = row['SourceTableName']
    stage_schema = row['StageSchema']
    stage_table = row['StageTableName']
    target_schema = row['TargetSchema']
    target_table = row['TargetTableName']
    load_type = str(row['LoadType']).lower()
    
    wm_col = row['WatermarkColumn']
    wm_type = str(row['WatermarkType']).lower() if pd.notna(row['WatermarkType']) else None
    
    sqlite_path = os.path.join(SQLITE_DIR, f"{source_db_name}.db")
    
    # TIMESTAMP INJECTION FOR EACH TABLE
    step_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{step_time}] [{index+1}/{len(df_config)}] Processing: {source_db_name}.{source_table} -> {stage_table}")
    
    if not os.path.exists(sqlite_path):
        print(f"  [!] SKIPPED: DB file not found: {sqlite_path}")
        continue
    
    sqlite_query = f"SELECT * FROM {source_table}"
    
    if load_type == 'merge' and wm_col and wm_type in ('date', 'id'):
        try:
            watermark_query = f"SELECT MAX({wm_col}) as max_val FROM [{target_schema}].[{target_table}]"
            with sql_engine.connect() as conn:
                df_wm = pd.read_sql(text(watermark_query), conn)
            max_val = df_wm['max_val'].iloc[0]
            
            if pd.notnull(max_val):
                if wm_type == 'date':
                    cutoff_date = pd.to_datetime(max_val) - timedelta(days=3)
                    cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S') if len(str(max_val)) > 10 else cutoff_date.strftime('%Y-%m-%d')
                    sqlite_query = f"SELECT * FROM {source_table} WHERE {wm_col} >= '{cutoff_str}'"
                    print(f"  [i] MODE 2 (Date Delta). Watermark: {cutoff_str}")
                elif wm_type == 'id':
                    sqlite_query = f"SELECT * FROM {source_table} WHERE {wm_col} > {max_val}"
                    print(f"  [i] MODE 3 (ID Delta). Watermark: > {max_val}")
        except Exception as e:
            print(f"  [!] Watermark evaluation failed: {e}")
            sys.exit(1)

    try:
        with sqlite3.connect(sqlite_path) as sqlite_conn:
            df_source = pd.read_sql_query(sqlite_query, sqlite_conn)
            rows_count = len(df_source)
    except Exception as e:
        print(f"  [!] SQLite extraction failed: {e}")
        continue

    if rows_count == 0:
        print("  [+] No new records. Skipping.")
        continue

    try:
        df_source.to_sql(name=stage_table, con=sql_engine, schema=stage_schema, if_exists='replace', index=False)
        print(f"  [+] Loaded {rows_count} rows.")
    except Exception as e:
        print(f"  [!] ERROR writing to SQL Server: {e}")
        sys.exit(1)

# --- TRIGGER MASTER ELT ---
trigger_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
print(f"\n[{trigger_time}] Triggering Master ELT Procedure in SQL Server...")
try:
    with sql_engine.begin() as conn:
        conn.execute(text("EXEC [dbo].[p_MasterDataLoad]"))
    end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{end_time}] [+] Master ELT Procedure executed successfully.")
except Exception as e:
    err_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{err_time}] [!] ERROR executing Master ELT Procedure: {e}")
    sys.exit(1)