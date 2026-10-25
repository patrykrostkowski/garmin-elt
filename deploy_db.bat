@echo off
setlocal enabledelayedexpansion

:: Configuration
set "SERVER_NAME=localhost"
set "DB_NAME=mygarmin"
set "CURRENT_DIR=%~dp0"
set "SEED_PATH=%CURRENT_DIR%database_setup\seeds\acc.SrcTableConfig.csv"

echo [INFO] Creating database...
sqlcmd -S "%SERVER_NAME%" -E -C -i "database_setup\00_create_database.sql"
if %ERRORLEVEL% neq 0 goto :ERROR_HANDLER

echo [INFO] Installing tables...
sqlcmd -S "%SERVER_NAME%" -d "%DB_NAME%" -E -C -i "database_setup\10_tables.sql"
if %ERRORLEVEL% neq 0 goto :ERROR_HANDLER

echo [INFO] Loading config table...
sqlcmd -S "%SERVER_NAME%" -d "%DB_NAME%" -E -C -v SeedFilePath="%SEED_PATH%" -i "database_setup\11_load_config.sql"
if %ERRORLEVEL% neq 0 goto :ERROR_HANDLER

echo [INFO] Installing views...
sqlcmd -S "%SERVER_NAME%" -d "%DB_NAME%" -E -C -i "transform\20_views.sql"
if %ERRORLEVEL% neq 0 goto :ERROR_HANDLER

echo [INFO] Installing procedures...
sqlcmd -S "%SERVER_NAME%" -d "%DB_NAME%" -E -C -i "transform\30_procedures.sql"
if %ERRORLEVEL% neq 0 goto :ERROR_HANDLER

echo [INFO] Loading calendar table...
sqlcmd -S "%SERVER_NAME%" -d "%DB_NAME%" -E -C -Q "EXEC [dim].[p_LoadCalendar]"
if %ERRORLEVEL% neq 0 goto :ERROR_HANDLER

echo [SUCCESS] Database deployment completed successfully.
pause
exit /b 0

:ERROR_HANDLER
echo [ERROR] Deployment failed with ERRORLEVEL: %ERRORLEVEL%
pause
exit /b %ERRORLEVEL%