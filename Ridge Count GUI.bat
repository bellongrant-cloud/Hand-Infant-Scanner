@echo off
REM Double-click this file to launch the Ridge Count GUI.
REM Keep it in the same folder as ridge_count_gui.py and ridge_count_standalone.py.

set SCRIPT_DIR=%~dp0

where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw "%SCRIPT_DIR%ridge_count_gui.py"
) else (
    python "%SCRIPT_DIR%ridge_count_gui.py"
    if errorlevel 1 pause
)
