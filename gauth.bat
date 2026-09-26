@echo off
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" goto :nopython
echo ============================================================
echo    HANGEUL BOT  -  GOOGLE LOGIN  (one time)
echo ============================================================
echo.
echo [1/2] Making sure the Google libraries are installed...
"%PY%" -m pip install --quiet --disable-pip-version-check google-api-python-client google-auth-httplib2 google-auth-oauthlib
echo.
echo [2/2] A browser window will open.
echo       - Sign in as  rahmansaem@gmail.com
echo       - If you see "Google hasn't verified this app", click  Advanced  ^>  Go to Hangeul Bot (unsafe)
echo       - Click  Allow  on both permission screens.
echo.
"%PY%" -m src.sheets.progress_builder --auth
echo.
echo If it said 'Google login OK', you are done. You can close this window.
pause
exit /b

:nopython
echo [ERROR] "%PY%" is missing.
echo Create the Python 3.12 environment in this folder first (see the top of requirements.txt).
pause
exit /b 1
