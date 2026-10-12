@echo off
REM Drag-and-drop ridge counter for Windows.
REM Usage: drag a scan image (PNG/BMP/TIFF/JPEG) onto this .bat file.
REM Keep this file in the same folder as ridge_count_standalone.py.

if "%~1"=="" (
    echo Drag a scanner image file onto this .bat file to run it.
    echo ^(Or run from a terminal: run_ridge_count.bat path\to\scan.png^)
    pause
    exit /b 1
)

set SCRIPT_DIR=%~dp0
set IMAGE=%~1
set OUT_DIR=%~dp1ridge_count_out

echo Running ridge count on: %IMAGE%
echo Output will be written to: %OUT_DIR%
echo.

python "%SCRIPT_DIR%ridge_count_standalone.py" "%IMAGE%" --output-dir "%OUT_DIR%"

echo.
if exist "%OUT_DIR%\annotated.png" (
    echo Done. Opening output folder...
    start "" "%OUT_DIR%"
) else (
    echo Something went wrong - see the error above.
)
pause
