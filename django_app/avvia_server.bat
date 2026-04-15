@echo off
setlocal
set "ROOT=%~dp0"
set "APP_DIR=%ROOT%"
set "VENV_PY=%ROOT%..\.venv\Scripts\python.exe"
set "PORT=8000"
set "RUNSERVER_FLAGS="
set "DRY_RUN="
if /I "%~1"=="--noreload" set "RUNSERVER_FLAGS=--noreload"
if /I "%~1"=="--dry-run" set "DRY_RUN=1"
if /I "%~2"=="--dry-run" set "DRY_RUN=1"

echo Chiudo tutte le istanze Django runserver attive...
echo Verifico eventuali listener residui sulla porta %PORT%...
set "FOUND_PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo   - stop PID %%P
    taskkill /F /PID %%P >nul 2>&1
    set "FOUND_PORT_PID=1"
)
if not defined FOUND_PORT_PID echo   - nessun listener attivo trovato sulla porta %PORT%...

ping -n 2 127.0.0.1 >nul 2>&1

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
