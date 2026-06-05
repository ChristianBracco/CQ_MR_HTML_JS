@echo off
title MRI QC Analyzer — Launcher
echo.
echo  ============================================
echo   MRI QC Analyzer — Phantom ACR
echo   PSG / PIU / SNR / SNRU
echo  ============================================
echo.
echo  Avvio backend su http://localhost:8181 ...
echo  Frontend su http://localhost:8181/frontend/
echo.
echo  Premi Ctrl+C per chiudere.
echo  ============================================
echo.

cd /d "%~dp0"

start "" http://localhost:8181/frontend/

python -m uvicorn backend.api:app --host 127.0.0.1 --port 8181 --reload --app-dir "%~dp0"
