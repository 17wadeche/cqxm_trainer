@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0GCH-Helper.exe" goto missing_bundle
"%~dp0GCH-Helper.exe" --install
if errorlevel 1 goto setup_failed
echo.
echo Setup is complete. Reload the extension in Chrome, then refresh GCH.
pause
exit /b 0
:missing_bundle
echo This folder is missing the bundled Windows application.
echo Download the GCH-Check-My-Work-Windows-x64 release ZIP and extract ALL files.
echo Do not use GitHub's Source code ZIP or copy a .venv folder from another PC.
echo Python does not need to be installed on this computer.
pause
exit /b 1
:setup_failed
echo Setup did not finish. Keep this window open and give the error to your IT team.
pause
exit /b 1
