@echo off
REM Bypass execution policy and run deploy.ps1
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" %*
