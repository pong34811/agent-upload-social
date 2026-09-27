@echo off
setlocal

rem Run from this file's folder, even when started by double-click.
cd /d "%~dp0"

set "APP=%~dp0.venv\Scripts\kt404-youtube.exe"
set "CLIENT=%~dp0client_secrets.json"
set "ACCOUNT="

if not exist "%APP%" (
    echo ERROR: Could not find the project environment:
    echo        %APP%
    echo Install the project environment in this project's .venv folder.
    exit /b 1
)
echo.
echo Using Desktop OAuth JSON: "%CLIENT%"
if not exist "%CLIENT%" (
    echo.
    echo ERROR: OAuth Desktop JSON was not found:
    echo        %CLIENT%
    echo No OAuth browser will be opened. Choose a valid Desktop OAuth JSON first.
    exit /b 1
)

echo.
echo Choose a local credential label for the Google account.
echo Use 1-40 letters, numbers, underscores, or hyphens.
set /p "ACCOUNT=Account label: "
if not defined ACCOUNT (
    echo.
    echo ERROR: An account label is required. No OAuth browser was opened.
    exit /b 2
)

echo.
echo Preparing OAuth for credential label "%ACCOUNT%".
echo This command does not call YouTube API or upload videos.
echo.

"%APP%" auth token --client-secrets "%CLIENT%" --account "%ACCOUNT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo OAuth credential is ready.
) else (
    echo OAuth did not complete. Read the error above.
)
exit /b %EXIT_CODE%
