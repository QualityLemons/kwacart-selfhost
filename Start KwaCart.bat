@echo off
setlocal
cd /d "%~dp0"
py -3.13 -c "import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,15)))" >nul 2>&1
if not errorlevel 1 goto py313
py -3.14 -c "import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,15)))" >nul 2>&1
if not errorlevel 1 goto py314
py -3.12 -c "import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,15)))" >nul 2>&1
if not errorlevel 1 goto py312
py -3 -c "import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,15)))" >nul 2>&1
if not errorlevel 1 goto pydefault
python -c "import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,15)))" >nul 2>&1
if not errorlevel 1 goto pythondefault
echo Python was not found. Install Python 3.13 from python.org, then try again.
echo Select "Add python.exe to PATH" if the installer offers that option.
set KWACART_EXIT=1
goto pausewindow
:py313
py -3.13 "%~dp0start_kwacart.py" %*
goto finished
:py314
py -3.14 "%~dp0start_kwacart.py" %*
goto finished
:py312
py -3.12 "%~dp0start_kwacart.py" %*
goto finished
:pydefault
py -3 "%~dp0start_kwacart.py" %*
goto finished
:pythondefault
python "%~dp0start_kwacart.py" %*
:finished
set KWACART_EXIT=%ERRORLEVEL%
:pausewindow
echo.
pause
exit /b %KWACART_EXIT%
