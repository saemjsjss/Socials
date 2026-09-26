@echo off
cd /d "%~dp0"
echo ============================================================
echo    HANGEUL BOT  -  BUILD PROGRESS SHEETS  (live portal data)
echo ============================================================
echo.
echo Building all four program sheets into the ALL STUDENTS Drive folder...
echo (Korean Language, EAP, Bachelor, Master - each into its intake folder.)
echo.
python -m src.sheets.progress_builder --all
echo.
echo Done. Open your ALL STUDENTS Drive folder to see the sheets.
pause
