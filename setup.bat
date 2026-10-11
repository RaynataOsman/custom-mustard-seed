@echo off
cd /d "%~dp0"
echo === Mustard Seed one-time setup ===
python -m pip install --upgrade python-docx requests playwright
echo.
echo Checking the browser the engine drives (uses your installed Chrome; Chromium is the backup)...
python -m playwright install chromium
echo.
if not exist config.json (
  copy config.example.json config.json >nul
  echo Created your config.json - fill in your details in the dashboard Settings tab.
)
if not exist masters mkdir masters
if not exist keys.env (
  echo # Paste free keys in the dashboard Settings tab instead of editing this file.>keys.env
)
if exist "C:\Program Files\LibreOffice\program\soffice.exe" (
  echo LibreOffice found - PDFs will be created.
) else (
  echo LibreOffice not found. Installing it so every tailored resume also gets a clean PDF...
  winget install --id TheDocumentFoundation.LibreOffice -e --accept-package-agreements --accept-source-agreements
)
echo.
echo Setup finished. Double-click start.bat to open the dashboard.
pause
