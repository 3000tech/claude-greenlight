@echo off
REM Start the monitor with a visible console: if Python crashes,
REM the traceback stays on screen instead of vanishing (as pythonw does).
python "%~dp0monitor.py"
echo.
echo === monitor exited (exit code %errorlevel%) ===
pause
