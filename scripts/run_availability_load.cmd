@echo off
setlocal
cd /d "%~dp0.."

echo [1/5] Ensuring containers are up...
docker compose -f deploy\dockercompose.yml up --build -d
if errorlevel 1 goto :error

echo [2/6] Waiting for database to accept connections...
timeout /t 8 >nul

echo [3/6] Applying 'availability' preset...
python scripts\apply_env_preset.py availability
if errorlevel 1 goto :error

echo [4/6] Restocking product 2 (set stock = 100000)...
docker compose -f deploy\dockercompose.yml exec -T db sh -c "psql -U postgres -d retail_db -c \"update \\\"Product\\\" set stock = 100000 where \\\"productID\\\" = 2;\""
if errorlevel 1 goto :error

echo [5/6] Restarting web container...
docker compose -f deploy\dockercompose.yml restart web
if errorlevel 1 goto :error

echo [6/6] Giving web container time to warm up...
timeout /t 10 >nul

echo Running Availability A.1 burst (80 runs, delay 0.03s, concurrency 2)...
python scripts\performance_scenario_runner.py --base-url http://localhost:5000 --runs 80 --delay 0.03 --concurrency 2 --product-id 2
goto :eof

:error
echo.
echo Availability load script failed. See errors above.
exit /b 1

