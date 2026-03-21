@echo off
title Portale Novicrom — Setup Wizard PROD
:: Richiede privilegi amministratore
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Avvio come Amministratore...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo.
echo  ============================================================
echo   ATTENZIONE: stai per configurare l'ambiente di PRODUZIONE
echo  ============================================================
echo.
echo  Assicurati di aver:
echo    1. Testato la release in TEST
echo    2. Eseguito il backup del DB di produzione
echo    3. Comunicato agli utenti la finestra di manutenzione
echo.
set /p CONFIRM="Digita CONFERMO per continuare: "
if /i not "%CONFIRM%"=="CONFERMO" (
    echo Operazione annullata.
    pause
    exit /b
)
echo Avvio Setup Wizard Portale Novicrom [Ambiente: PROD]...
python "%~dp0setup_wizard.py" --env prod
if errorlevel 1 (
    echo.
    echo ERRORE: Python non trovato oppure tkinter mancante.
    pause
)
