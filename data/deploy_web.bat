@echo off
rem Deploy the online dashboard to Vercel production from a clean copy that holds ONLY web\
rem (the engine folder has your database, keys and browser profiles, which must never be uploaded).
set SRC=%~dp0..
set OUT=%TEMP%\mustard-seed-deploy
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
robocopy "%SRC%\web" "%OUT%\web" /E /XF .env* /XD .vercel node_modules /NFL /NDL /NJH /NJS >nul
robocopy "%SRC%\.vercel" "%OUT%\.vercel" project.json README.txt /NFL /NDL /NJH /NJS >nul
cd /d "%OUT%"
if not exist .vercel\project.json call vercel link --yes --project mustard-seed-online --scope 187jjay187s-projects
call vercel deploy --prod --yes --scope 187jjay187s-projects
cd /d "%SRC%"
rmdir /s /q "%OUT%"