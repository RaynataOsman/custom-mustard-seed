@echo off
cd /d "%~dp0"
docker start searxng >nul 2>&1
python pipeline.py all
