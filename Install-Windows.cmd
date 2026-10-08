@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m venv .venv
goto venv_result
:use_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv .venv
:venv_result
if not exist ".venv\Scripts\python.exe" goto setup_failed
:dependencies
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3,10)"
if errorlevel 1 goto setup_failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto setup_failed
".venv\Scripts\python.exe" install_native.py
if errorlevel 1 goto setup_failed
echo.
echo One-time setup is complete. This window can be closed.
pause
exit /b 0
:missing_python
echo Ask your IT team to install Python 3.10 or later, then run this installer again.
pause
exit /b 1
:setup_failed
echo Setup did not finish. Give this window to your IT team so they can check Python and package access.
pause
exit /b 1
