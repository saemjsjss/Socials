@echo off
cd /d "%~dp0"
echo ============================================================
echo    HANGEUL BOT  -  GOOGLE LOGIN  (one time)
echo ============================================================
echo.
echo [1/2] Making sure the Google libraries are installed...
python -m pip install --quiet --disable-pip-version-check google-api-python-client google-auth-httplib2 google-auth-oauthlib
echo.
echo [2/2] A browser window will open.
echo       - Sign in as  rahmansaem@gmail.com
echo       - If you see "Google hasn't verified this app", click  Advanced  ^>  Go to Hangeul Bot (unsafe)
echo       - Click  Allow  on both permission screens.
echo.
python -m src.sheets.progress_builder --auth
echo.
echo If it said 'Google login OK', you are done. You can close this window.
pause
