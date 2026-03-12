@echo off
setlocal
set "ROOT=%~dp0"
set "APP_DIR=%ROOT%django_app"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "PORT=8000"
set "RUNSERVER_FLAGS="
set "DRY_RUN="
if /I "%~1"=="--noreload" set "RUNSERVER_FLAGS=--noreload"
if /I "%~1"=="--dry-run" set "DRY_RUN=1"
if /I "%~2"=="--dry-run" set "DRY_RUN=1"

echo Chiudo tutte le istanze Django runserver attive...
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\\.exe)?$' -and $_.CommandLine -match '\\brunserver\\b' -and $_.CommandLine -match 'manage\\.py' } | Select-Object -ExpandProperty ProcessId"`) do (
    echo   - stop PID %%P
    taskkill /F /PID %%P >nul 2>&1
)

echo Chiudo eventuali listener residui sulla porta %PORT%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)

timeout /t 1 /nobreak >nul

if not exist "%VENV_PY%" (
    echo ERRORE: interpreter non trovato: %VENV_PY%
    exit /b 1
)

if defined RUNSERVER_FLAGS (
    echo Avvio server Django ^(HTTP^) su 0.0.0.0:%PORT% con flag: %RUNSERVER_FLAGS%
) else (
    echo Avvio server Django ^(HTTP^) su 0.0.0.0:%PORT% con autoreload attivo...
)
cd /d "%APP_DIR%"
set DJANGO_SETTINGS_MODULE=config.settings.dev
if defined DRY_RUN (
    echo Dry run completato. Server non avviato.
    exit /b 0
)
"%VENV_PY%" manage.py runserver 0.0.0.0:%PORT% %RUNSERVER_FLAGS%
