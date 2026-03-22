@echo off
:: Avvia il wizard in modalità Disinstallazione con elevazione automatica
:: Uso: doppio clic oppure da terminale

net session >nul 2>&1
if %errorLevel% == 0 (
    :: Già amministratore — avvia direttamente
    goto :run
) else (
    :: Ri-esegui con elevazione UAC
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:run
setlocal

:: Usa il .exe compilato se esiste, altrimenti python diretto
set "WIZARD_EXE=%~dp0dist\SetupWizard.exe"
set "WIZARD_PY=%~dp0setup_wizard.py"

if exist "%WIZARD_EXE%" (
    start "" "%WIZARD_EXE%" --mode uninstall
) else (
    python "%WIZARD_PY%" --mode uninstall
)
