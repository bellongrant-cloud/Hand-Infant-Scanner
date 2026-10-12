@echo off
rem Ridge Counter: double-click to open, or drag a scan image onto this file.
setlocal
set "APP=%~dp0ridge_counter.py"
if not exist "%APP%" (
  echo ridge_counter.py must be in the same folder as this file.
  pause
  exit /b 1
)
where pyw >/dev/null 2>/dev/null && ( start "" pyw "%APP%" %* & exit /b 0 )
where pythonw >/dev/null 2>/dev/null && ( start "" pythonw "%APP%" %* & exit /b 0 )
where py >/dev/null 2>/dev/null && ( py "%APP%" %* & exit /b )
where python >/dev/null 2>/dev/null && ( python "%APP%" %* & exit /b )
echo Python was not found on this computer.
echo Install it from https://www.python.org/downloads/ and then run this file again.
pause
exit /b 1
