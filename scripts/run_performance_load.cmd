@echo off
setlocal
cd /d "%~dp0.."

echo [1/5] Applying 'performance' preset...
python scripts\apply_env_preset.py performance
if errorlevel 1 goto :error

echo [2/5] Restarting web container...
docker compose -f deploy\dockercompose.yml restart web
if errorlevel 1 goto :error

echo [3/5] Restocking product 2 (set stock = 100000)...
docker compose -f deploy\dockercompose.yml exec -T db sh -c "psql -U postgres -d retail_db -c \"update \\\"Product\\\" set stock = 100000 where \\\"productID\\\" = 2;\""
if errorlevel 1 goto :error

echo [4/5] Giving web container time to warm up...
timeout /t 8 >nul

echo [5/5] Running Performance P.1 burst (~1000 RPS: 60 runs, delay 0.01s, concurrency 10)...
python scripts\performance_scenario_runner.py --base-url http://localhost:5000 --runs 60 --delay 0.01 --concurrency 10 --product-id 2
goto :eof

:error
echo.
echo Performance load script failed. See errors above.
exit /b 1

