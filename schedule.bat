@echo off
cd /d "%~dp0"
echo Registering "Job Engine" to find and prepare roles every 3 hours (it never submits on its own).
schtasks /Create /SC HOURLY /MO 3 /TN "Job Engine" /TR "\"%~dp0run_all.bat\"" /F
if %ERRORLEVEL% EQU 0 (echo Done. To remove it: schtasks /Delete /TN "Job Engine" /F) else (echo Could not create the task.)
pause
