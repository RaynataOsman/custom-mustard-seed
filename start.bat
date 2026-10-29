@echo off
cd /d "%~dp0"
title Mustard Seed CUSTOM dashboard (port 8777) - close this window to stop it
python app.py --port 8777
