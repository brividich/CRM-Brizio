@echo off
title Portale Novicrom — Gestione Release
:: Richiede privilegi amministratore (junction + IIS recycle)
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Avvio come Amministratore...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo Avvio Gestione Release Portale Novicrom...
python "%~dp0setup_wizard.py" --mode release
if errorlevel 1 (
    echo.
    echo ERRORE: Python non trovato oppure tkinter mancante.
    pause
)
