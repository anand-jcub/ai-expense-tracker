@echo off
cd /d "%~dp0"
start "" /B "%~dp0venv\Scripts\pythonw.exe" "%~dp0tunnel_watchdog.py"
