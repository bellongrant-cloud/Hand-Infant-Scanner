@echo off
rem Ridge Counter: double-click to open, or drag a scan image onto this file.
setlocal
set "APP=%~dp0ridge_counter.py"
if not exist "%APP%" (
  echo ridge_counter.py must be in the same folder as this file.
  echo Extract the whole ZIP first, then run this file from the extracted folder.
  pause
  exit /b 1
)

rem Find a Python that actually runs: first on PATH, then where installers put it.
set "PY="
for %%P in (pyw pythonw py python) do if not defined PY call :try "%%P"
for %%P in ("%LOCALAPPDATA%\Microsoft\WindowsApps\pyw.exe" "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe") do if not defined PY if exist %%P call :try %%P
for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-*" "%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do if not defined PY if exist "%%~D\pythonw.exe" call :try "%%~D\pythonw.exe"
if not defined PY (
  echo Python was not found on this computer.
  echo Install it from https://www.python.org/downloads/ and then run this file again.
  pause
  exit /b 1
)
start "" %PY% "%APP%" %*
exit /b 0

:try
%1 -c "import sys" <nul >nul 2>&1 && set "PY=%1"
exit /b
