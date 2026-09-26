@echo off
setlocal

rem Run from this file's folder, even when started by double-click.
cd /d "%~dp0"

set "APP=%~dp0.venv\Scripts\kt404-youtube.exe"
set "CLIENT=%~dp0client_secrets.json"
if not "%~1"=="" set "CLIENT=%~f1"
if not exist "%APP%" (
    echo ERROR: Could not find the project environment:
    echo        %APP%
    echo Run this file from the D:\agent-upload-social project folder.
    pause
    exit /b 1
)

if not exist "%CLIENT%" (
    echo ERROR: OAuth Desktop JSON was not found:
    echo        %CLIENT%
    echo Put the Desktop OAuth JSON at the path above, or pass its path as the first argument.
    pause
    exit /b 1
)

echo Starting YouTube OAuth.
echo Select the Google account/channel in the browser. No video upload is started by this command.
echo.

"%APP%" auth token --client-secrets "%CLIENT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo OAuth completed successfully.
) else (
    echo OAuth did not complete. Read the error above.
)
pause
exit /b %EXIT_CODE%
