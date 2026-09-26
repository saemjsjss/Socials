@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo    HANGEUL BOT  -  INSTALL PROGRESS-SHEET FEATURE
echo ============================================================
echo.
if not exist "src\sheets" mkdir "src\sheets"
type nul > "src\sheets\__init__.py"
set "SRC="
if exist "%~dp0progress_builder.py" set "SRC=%~dp0progress_builder.py"
if not defined SRC (
  for /f "delims=" %%F in ('dir /b /o-d "%USERPROFILE%\Downloads\progress_builder*.py" 2^>nul') do (
    set "SRC=%USERPROFILE%\Downloads\%%F"
    goto :found
  )
)
:found
if defined SRC (
  copy /Y "!SRC!" "src\sheets\progress_builder.py" >nul
  echo   installed  src\sheets\progress_builder.py
) else (
  echo   ERROR: progress_builder.py not found.
  echo   Put progress_builder.py into E:\BOT and run this again.
  pause
  exit /b 1
)
echo   created    src\sheets\__init__.py
echo.
echo Installing Google libraries (one-time)...
python -m pip install --quiet --disable-pip-version-check google-api-python-client google-auth-httplib2 google-auth-oauthlib
echo.
echo DONE.  Next steps:
echo   1) make sure credentials.json is in E:\BOT
echo   2) double-click  gauth.bat        (one-time Google login)
echo   3) double-click  build_sheets.bat (build the four sheets)
echo.
pause
