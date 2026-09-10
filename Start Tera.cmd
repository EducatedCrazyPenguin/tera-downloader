@echo off
cd /d "%~dp0"
python terabox.py
if errorlevel 1 pause
