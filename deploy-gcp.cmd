@echo off
REM Bypass execution policy and run Google Cloud deploy
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-gcp.ps1" %*
