@echo off
REM ---------------------------------------------------------------------
REM  Daily reel generation - this is what Windows Task Scheduler runs.
REM
REM  Register it with:   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
REM  Run it by hand:     run_daily.bat
REM
REM  PYTHON_EXE is overridable, e.g. to point at a virtualenv:
REM      set "PYTHON_EXE=D:\Agents\Insta\.venv\Scripts\python.exe"
REM ---------------------------------------------------------------------
setlocal

REM Always operate from the project directory, whatever CWD the scheduler used.
cd /d "%~dp0"

if not defined PYTHON_EXE set "PYTHON_EXE=C:\Users\lenovo\anaconda3\python.exe"

REM Keep emoji in log output from crashing the cp1252 console.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if not exist "logs" mkdir "logs"

echo [%DATE% %TIME%] Starting daily run >> "logs\scheduler.log"
"%PYTHON_EXE%" -m reelbot run-daily >> "logs\scheduler.log" 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] Finished with exit code %EXITCODE% >> "logs\scheduler.log"

exit /b %EXITCODE%
