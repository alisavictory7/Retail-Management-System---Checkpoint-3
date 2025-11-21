@echo off
setlocal
cd /d "%~dp0.."

echo Applying 'availability-failure' preset...
python scripts\apply_env_preset.py availability-failure
if errorlevel 1 goto :error

echo Restarting web container...
docker compose -f deploy\dockercompose.yml restart web
if errorlevel 1 goto :error

echo.
echo =================================================================
echo  Availability Failure Demo
echo =================================================================
echo 1. Open http://localhost:5000/admin/returns
echo 2. Walk RMA-CP3-DEMO-001 through Receive ^> Inspection ^> Refund.
echo 3. Leave refund method as Card / Original Method so the payment
echo    service goes through the circuit breaker path.
echo 4. Wait ~60 seconds and retry refund to capture MTTR ^< 5 minutes.
echo.
powershell -NoLogo -NoProfile -Command "Write-Host 'Press Enter after completing the dashboard steps...'; Read-Host ^| Out-Null"
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Failed to toggle availability failure preset.
exit /b 1

