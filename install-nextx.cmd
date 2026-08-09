@echo off
setlocal EnableExtensions EnableDelayedExpansion
for %%I in ("%~dp0.") do set "SCRIPT_DIR=%%~fI"
if not "%NEXTX_PYTHON%"=="" (
  "%NEXTX_PYTHON%" "%SCRIPT_DIR%\skills\nextx\scripts\bootstrap.py" --output human %* --source "%SCRIPT_DIR%"
  exit /b %ERRORLEVEL%
)
for %%V in (3.13 3.12 3.11) do (
  py -%%V -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul
  if not errorlevel 1 (
    py -%%V "%SCRIPT_DIR%\skills\nextx\scripts\bootstrap.py" --output human %* --source "%SCRIPT_DIR%"
    exit /b !ERRORLEVEL!
  )
)
echo NextX requires Python 3.11 or newer; set NEXTX_PYTHON to a compatible interpreter. 1>&2
exit /b 1
