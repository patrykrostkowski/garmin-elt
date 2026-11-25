# Language: Python 3.10+
import argparse
import os
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from sqlalchemy import create_engine, text

# Full Drive scope is required to list and update files inside a pre-existing folder
# created manually outside this OAuth app (drive.file cannot see externally created folders).
SCOPES = ["https://www.googleapis.com/auth/drive"]

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "export" / "output"

EXPORT_SPECS = [
    (
        "daily_health_90d.csv",
        "SELECT * FROM [dbo].[v_Export_DailyHealth_90d] ORDER BY [day] DESC",
    ),
    (
        "activities_90d.csv",
        "SELECT * FROM [dbo].[v_Export_Activities_90d] ORDER BY [start_time] DESC",
    ),
    (
        "weekly_summary_16w.csv",
        "SELECT * FROM [dbo].[v_Export_WeeklySummary_16w] ORDER BY [week_start_date] DESC",
    ),
]


def log(message: str, is_error: bool = False) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = "[!]" if is_error else "[i]"
    print(f"[{timestamp}] {prefix} {message}", flush=True)


def resolve_path(path_value: str | None, default_rel: str) -> Path:
    raw = Path(path_value) if path_value else Path(default_rel)
    return raw if raw.is_absolute() else (PROJECT_DIR / raw)


def build_sql_engine():
    db_server = os.getenv("SQL_SERVER")
    db_name = os.getenv("SQL_DATABASE")
    db_driver = os.getenv("SQL_DRIVER")

    if not all([db_server, db_name, db_driver]):
        log("Missing SQL_* environment variables in .env file.", is_error=True)
        sys.exit(1)

    params = urllib.parse.quote_plus(
        f"DRIVER={{{db_driver}}};"
        f"SERVER={db_server};"
        f"DATABASE={db_name};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")


def get_drive_service(credentials_path: Path, token_path: Path):
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                log(f"OAuth token refresh failed ({exc}); re-authenticating...", is_error=True)
                creds = None

        if not creds or not creds.valid:
            if not credentials_path.exists():
                log(f"OAuth credentials file not found: {credentials_path}", is_error=True)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def export_views_to_csv(sql_engine, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files: list[Path] = []

    with sql_engine.connect() as conn:
        for filename, sql_query in EXPORT_SPECS:
            log(f"Exporting {filename} from SQL Server...")
            df = pd.read_sql_query(text(sql_query), conn)
            if df.empty:
                raise ValueError(
                    f"Query for {filename} returned 0 rows. Aborting to protect existing Drive snapshot."
                )

            target_path = output_dir / filename
            df.to_csv(target_path, index=False, encoding="utf-8", lineterminator="\n")
            log(f"Saved {len(df)} rows -> {target_path}")
            generated_files.append(target_path)

    return generated_files


def upsert_csv_to_drive(service, folder_id: str, local_path: Path) -> None:
    filename = local_path.name
    escaped_name = filename.replace("'", "\\'")
    query = (
        f"name = '{escaped_name}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )

    response = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name, modifiedTime)",
            orderBy="modifiedTime desc",
            pageSize=10,
        )
        .execute()
    )
    matches = response.get("files", [])
    media = MediaFileUpload(str(local_path), mimetype="text/csv", resumable=False)

    if matches:
        if len(matches) > 1:
            log(
                f"WARNING: Found {len(matches)} files named '{filename}' in target folder; "
                f"updating the most recently modified copy.",
                is_error=True,
            )
        target_id = matches[0]["id"]
        updated = (
            service.files()
            .update(fileId=target_id, media_body=media, fields="name, modifiedTime")
            .execute()
        )
        log(f"Updated in place on Drive: {updated['name']} (modifiedTime={updated['modifiedTime']})")
    else:
        metadata = {"name": filename, "parents": [folder_id]}
        created = (
            service.files()
            .create(body=metadata, media_body=media, fields="name, modifiedTime")
            .execute()
        )
        log(f"Created new file on Drive: {created['name']} (modifiedTime={created['modifiedTime']})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Garmin SQL views to CSV and sync to Google Drive.")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Generate local CSV snapshots in export/output/ without uploading to Google Drive.",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_DIR / ".env")

    sql_engine = build_sql_engine()
    try:
        csv_files = export_views_to_csv(sql_engine, DEFAULT_OUTPUT_DIR)
    except Exception as exc:
        log(f"SQL export failed: {exc}", is_error=True)
        return 1
    finally:
        sql_engine.dispose()

    if args.local_only:
        log("Local-only mode enabled. Skipping Google Drive upload.")
        return 0

    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        log("Missing GDRIVE_FOLDER_ID in .env file.", is_error=True)
        return 1

    credentials_path = resolve_path(os.getenv("GDRIVE_CREDENTIALS_PATH"), "export/credentials.json")
    token_path = resolve_path(os.getenv("GDRIVE_TOKEN_PATH"), "export/token.json")

    try:
        service = get_drive_service(credentials_path, token_path)
        for csv_path in csv_files:
            upsert_csv_to_drive(service, folder_id, csv_path)
    except Exception as exc:
        log(f"Google Drive upload failed: {exc}", is_error=True)
        return 1

    log("[+] Google Drive CSV export completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())