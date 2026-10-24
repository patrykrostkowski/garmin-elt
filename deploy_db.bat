@echo off
set SERVER_NAME=localhost
set DB_NAME=mygarmin
set CURRENT_DIR=%CD%
set SEED_PATH=%CURRENT_DIR%\database_setup\seeds\acc.SrcTableConfig.csv

echo creating db...
sqlcmd -S %SERVER_NAME% -E -i database_setup\00_create_database.sql

echo installing tables...
sqlcmd -S %SERVER_NAME% -d %DB_NAME% -E -i database_setup\10_tables.sql

echo loading config table
sqlcmd -S %SERVER_NAME% -d %DB_NAME% -E -v SeedFilePath="%SEED_PATH%" -i database_setup\11_load_config.sql

echo installing vies...
sqlcmd -S %SERVER_NAME% -d %DB_NAME% -E -i transform\20_views.sql

echo installing procedures...
sqlcmd -S %SERVER_NAME% -d %DB_NAME% -E -i transform\30_procedures.sql

echo loading calendar table...
sqlcmd -S %SERVER_NAME% -d %DB_NAME% -E -Q "EXEC [dim].[p_LoadCalendar]"

pause
end