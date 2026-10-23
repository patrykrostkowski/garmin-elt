@echo off
setlocal enabledelayedexpansion

:: ==========================================
:: PATH CONFIGURATION & VALIDATION
:: ==========================================
:: Resolve canonical absolute path for project root
for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"

set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOGFILE=%LOG_DIR%\garmin_pipeline_run.log"
set "ENV_FILE=%PROJECT_DIR%\.env"

:: Create logs directory if it does not exist (Fail-Safe)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Check if .env configuration file exists
if not exist "%ENV_FILE%" (
    echo [!] CRITICAL ERROR: Configuration file .env not found at %ENV_FILE%
    echo [!] CRITICAL ERROR: Configuration file .env not found at %ENV_FILE% > "%LOGFILE%"
    pause
    exit /b 1
)

:: Parse external path configuration from .env file (ignoring comments starting with #)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if /i "%%A"=="GARMIN_DB_CLI_DIR" set "GARMIN_DB_CLI_DIR=%%B"
)

:: Validate required environment variables
if "%GARMIN_DB_CLI_DIR%"=="" (
    echo [!] CRITICAL ERROR: GARMIN_DB_CLI_DIR is missing or empty in .env file.
    echo [!] Please configure your .env file.
    pause
    exit /b 1
)

:: Initialize log file
echo =================================================== > "%LOGFILE%"
echo [%DATE% %TIME%] PIPELINE START >> "%LOGFILE%"
echo =================================================== >> "%LOGFILE%"

:: ==========================================
:: STEP 1: Garmin Connect Extraction (SQLite)
:: ==========================================
echo [1/2] RUNNING: Garmin Connect Extraction...
echo [1/2] RUNNING: Garmin Connect Extraction... >> "%LOGFILE%"

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
echo [2/2] RUNNING: ELT Pipeline (Extract ^& Stage + SQL Master Procedure)...
echo [2/2] RUNNING: ELT Pipeline (Extract ^& Stage + SQL Master Procedure)... >> "%LOGFILE%"

set "PYTHON_ENV=%PROJECT_DIR%\venv\Scripts\python.exe"
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

echo. >> "%LOGFILE%"
echo =================================================== >> "%LOGFILE%"
echo [+] PIPELINE COMPLETED SUCCESSFULLY.
echo [+] PIPELINE COMPLETED SUCCESSFULLY. >> "%LOGFILE%"
echo =================================================== >> "%LOGFILE%"

endlocal
pause