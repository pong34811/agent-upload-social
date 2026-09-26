@echo off
setlocal

rem Run from this file's folder, even when started by double-click.
cd /d "%~dp0"

set "APP=%~dp0.venv\Scripts\kt404-youtube.exe"
set "CLIENT=%~dp0client_secrets.json"
set "ACCOUNT=lamaixcom3481"
if not "%~1"=="" set "CLIENT=%~f1"
if not "%~2"=="" set "ACCOUNT=%~2"
if not exist "%APP%" (
    echo ERROR: Could not find the project environment:
    echo        %APP%
    echo Install the project environment in this project's .venv folder.
    pause
    exit /b 1
)

if not exist "%CLIENT%" (
    echo OAuth Desktop JSON was not found at:
    echo        %CLIENT%
    echo Put the selected Desktop OAuth JSON at the path above, or pass its path as the first argument.
    echo Use a valid Desktop OAuth JSON downloaded from Google Cloud. The launcher cannot create Google credentials.
    echo.
    set /p "CLIENT=Enter the full path to the new Desktop OAuth JSON, or press Enter to stop: "
    set "CLIENT=%CLIENT:"=%"
)

if not exist "%CLIENT%" (
    echo.
    echo ERROR: OAuth Desktop JSON was not found:
    echo        %CLIENT%
    echo No OAuth browser will be opened. Download a new Desktop OAuth JSON first.
    pause
    exit /b 1
)

echo Starting Google OAuth.
echo It reuses the saved credential for account "%ACCOUNT%" or opens Google if needed.
echo This command does not ask for a privacy-policy URL, call YouTube API, or upload videos.
echo To add another Google account, pass its new name as the second argument.
echo.

"%APP%" auth token --client-secrets "%CLIENT%" --account "%ACCOUNT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo OAuth credential is ready.
) else (
    echo OAuth did not complete. Read the error above.
)
pause
exit /b %EXIT_CODE%
