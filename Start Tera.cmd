@echo off
cd /d "%~dp0"
python src\terabox.py
if errorlevel 1 pause
