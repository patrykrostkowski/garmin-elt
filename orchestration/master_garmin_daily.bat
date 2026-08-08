@echo off
setlocal

:: ==========================================
:: PATH CONFIGURATION
:: ==========================================
:: %~dp0 is a orchestration/ folder, so we switch folder to the project root
set PROJECT_DIR=%~dp0..

:: set up garmindb_cli.py path
:: Read external path from .env
for /f "usebackq tokens=1,* delims==" %%A in ("%PROJECT_DIR%\.env") do (
    if "%%A"=="GARMIN_DB_CLI_DIR" set "GARMIN_DB_CLI_DIR=%%B"
)

if "%GARMIN_DB_CLI_DIR%"=="" (
    echo [!] CRITICAL ERROR: GARMIN_DB_CLI_DIR is missing or empty in .env file.
    echo [!] Please configure your .env file based on .env.example.
    pause
    exit /b 1
)

set LOGFILE="%PROJECT_DIR%\logs\garmin_pipeline_run.log"


:: Initialize log file
echo =================================================== > %LOGFILE%
echo [%DATE% %TIME%] PIPELINE START >> %LOGFILE%
echo =================================================== >> %LOGFILE%

echo [1/2] RUNNING: Garmin Connect Extraction...
echo [1/2] RUNNING: Garmin Connect Extraction... >> %LOGFILE%
cd /d %GARMIN_DB_CLI_DIR%

:: Execute with stdout and stderr redirection (2>&1) to the log file
python garmindb_cli.py --all --download --import --analyze --latest >> %LOGFILE% 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo [!] CRITICAL ERROR: garmindb_cli.py failed. Check log file.
    echo [!] ERRORLEVEL: %ERRORLEVEL% >> %LOGFILE%
    exit /b %ERRORLEVEL%
)

echo [+] SQLite extraction completed successfully. >> %LOGFILE%

echo =================================================== >> %LOGFILE%
echo [2/2] RUNNING: ELT Pipeline (Pushdown + MERGE)...
echo [2/2] RUNNING: ELT Pipeline (Pushdown + MERGE)... >> %LOGFILE%

::cd /d %ELT_DIR%

cd /d "%PROJECT_DIR%"
"%PROJECT_DIR%\venv\Scripts\python.exe" extract\garmin_dailyprocess.py >> %LOGFILE% 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo [!] ERROR: ELT process failed. Check log file.
    echo [!] ERRORLEVEL: %ERRORLEVEL% >> %LOGFILE%
    exit /b %ERRORLEVEL%
)

echo. >> %LOGFILE%
echo =================================================== >> %LOGFILE%
echo [+] PIPELINE COMPLETED SUCCESSFULLY. 
echo [+] PIPELINE COMPLETED SUCCESSFULLY. >> %LOGFILE%
echo =================================================== >> %LOGFILE%

endlocal

pause
end