:: Language: Windows Batch (.bat)
@echo off
setlocal enabledelayedexpansion

:: ==========================================
:: PATH CONFIGURATION & VALIDATION
:: ==========================================
for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"

set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOGFILE=%LOG_DIR%\garmin_pipeline_run.log"
set "ENV_FILE=%PROJECT_DIR%\.env"
set "ENABLE_GDRIVE_EXPORT=true"
set "SKIP_DRIVE=0"
set "PIPELINE_WARN=0"

if /i "%~1"=="--no-drive" set "SKIP_DRIVE=1"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if not exist "%ENV_FILE%" (
    echo [!] CRITICAL ERROR: Configuration file .env not found at %ENV_FILE%
    echo [!] CRITICAL ERROR: Configuration file .env not found at %ENV_FILE% > "%LOGFILE%"
    pause
    exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if /i "%%A"=="GARMIN_DB_CLI_DIR" set "GARMIN_DB_CLI_DIR=%%B"
    if /i "%%A"=="ENABLE_GDRIVE_EXPORT" set "ENABLE_GDRIVE_EXPORT=%%B"
)

if "%GARMIN_DB_CLI_DIR%"=="" (
    echo [!] CRITICAL ERROR: GARMIN_DB_CLI_DIR is missing or empty in .env file.
    echo [!] Please configure your .env file.
    pause
    exit /b 1
)

echo =================================================== > "%LOGFILE%"
echo [%DATE% %TIME%] PIPELINE START >> "%LOGFILE%"
echo =================================================== >> "%LOGFILE%"

:: ==========================================
:: STEP 1: Garmin Connect Extraction (SQLite)
:: ==========================================
echo [1/3] RUNNING: Garmin Connect Extraction...
echo [1/3] RUNNING: Garmin Connect Extraction... >> "%LOGFILE%"

if not exist "%GARMIN_DB_CLI_DIR%\garmindb_cli.py" (
    echo [!] CRITICAL ERROR: garmindb_cli.py not found in %GARMIN_DB_CLI_DIR% >> "%LOGFILE%"
    echo [!] Process terminated. Check log file for details.
    pause
    exit /b 1
)

cd /d "%GARMIN_DB_CLI_DIR%"
py -3 garmindb_cli.py --all --download --import --analyze --latest >> "%LOGFILE%" 2>&1

if %ERRORLEVEL% NEQ 0 (
    echo [!] CRITICAL ERROR: garmindb_cli.py failed. Check log file for details.
    echo [!] ERRORLEVEL: %ERRORLEVEL% >> "%LOGFILE%"
    pause
    exit /b %ERRORLEVEL%
)

echo [+] SQLite extraction completed successfully.
echo [+] SQLite extraction completed successfully. >> "%LOGFILE%"

:: ==========================================
:: STEP 2: ELT Pipeline (Python -> SQL Server)
:: ==========================================
echo =================================================== >> "%LOGFILE%"
echo [2/3] RUNNING: ELT Pipeline (Extract ^& Stage + SQL Master Procedure)...
echo [2/3] RUNNING: ELT Pipeline (Extract ^& Stage + SQL Master Procedure)... >> "%LOGFILE%"

set "PYTHON_ENV=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "SCRIPT_PATH=%PROJECT_DIR%\extract\garmin_dailyprocess.py"

if not exist "%PYTHON_ENV%" (
    echo [!] CRITICAL ERROR: Python venv not found at %PYTHON_ENV% >> "%LOGFILE%"
    echo [!] CRITICAL ERROR: Python venv not found at %PYTHON_ENV%
    pause
    exit /b 1
)

if not exist "%SCRIPT_PATH%" (
    echo [!] CRITICAL ERROR: ETL script not found at %SCRIPT_PATH% >> "%LOGFILE%"
    echo [!] CRITICAL ERROR: ETL script not found at %SCRIPT_PATH%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
"%PYTHON_ENV%" "%SCRIPT_PATH%" >> "%LOGFILE%" 2>&1

if %ERRORLEVEL% NEQ 0 (
    echo [!] CRITICAL ERROR: ELT process failed. Check log file for details.
    echo [!] ERRORLEVEL: %ERRORLEVEL% >> "%LOGFILE%"
    pause
    exit /b %ERRORLEVEL%
)

echo [+] SQL Server ELT completed successfully.
echo [+] SQL Server ELT completed successfully. >> "%LOGFILE%"

:: ==========================================
:: STEP 3: Export Snapshots to Google Drive
:: ==========================================
echo =================================================== >> "%LOGFILE%"
set "EXPORT_SCRIPT_PATH=%PROJECT_DIR%\export\export_to_gdrive.py"

if "%SKIP_DRIVE%"=="1" (
    echo [3/3] SKIPPED: Google Drive export disabled via --no-drive flag.
    echo [3/3] SKIPPED: Google Drive export disabled via --no-drive flag. >> "%LOGFILE%"
) else if /i not "%ENABLE_GDRIVE_EXPORT%"=="true" (
    echo [3/3] SKIPPED: Google Drive export disabled in .env ^(ENABLE_GDRIVE_EXPORT=%ENABLE_GDRIVE_EXPORT%^).
    echo [3/3] SKIPPED: Google Drive export disabled in .env ^(ENABLE_GDRIVE_EXPORT=%ENABLE_GDRIVE_EXPORT%^). >> "%LOGFILE%"
) else if not exist "%EXPORT_SCRIPT_PATH%" (
    echo [!] WARNING: Export script not found at %EXPORT_SCRIPT_PATH%. Skipping Step 3.
    echo [!] WARNING: Export script not found at %EXPORT_SCRIPT_PATH%. Skipping Step 3. >> "%LOGFILE%"
    set "PIPELINE_WARN=1"
) else (
    echo [3/3] RUNNING: Exporting CSV snapshots to Google Drive...
    echo [3/3] RUNNING: Exporting CSV snapshots to Google Drive... >> "%LOGFILE%"
    "%PYTHON_ENV%" "%EXPORT_SCRIPT_PATH%" >> "%LOGFILE%" 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo [!] WARNING: Google Drive export failed ^(ERRORLEVEL !ERRORLEVEL!^). Local SQL Server data is up to date.
        echo [!] WARNING: Google Drive export failed ^(ERRORLEVEL !ERRORLEVEL!^). Local SQL Server data is up to date. >> "%LOGFILE%"
        set "PIPELINE_WARN=1"
    ) else (
        echo [+] Google Drive export completed successfully.
        echo [+] Google Drive export completed successfully. >> "%LOGFILE%"
    )
)

echo. >> "%LOGFILE%"
echo =================================================== >> "%LOGFILE%"
if "%PIPELINE_WARN%"=="1" (
    echo [ERR] PIPELINE COMPLETED WITH WARNINGS ^(check log file^).
    echo [ERR] PIPELINE COMPLETED WITH WARNINGS. >> "%LOGFILE%"
) else (
    echo [+] PIPELINE COMPLETED SUCCESSFULLY.
    echo [+] PIPELINE COMPLETED SUCCESSFULLY. >> "%LOGFILE%"
)
echo =================================================== >> "%LOGFILE%"

endlocal
pause