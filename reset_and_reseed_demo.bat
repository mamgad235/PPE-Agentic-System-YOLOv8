@echo off
REM ============================================================
REM   PPE Guard - reset & reseed the demo database
REM   Deletes backend\agent\ppe_guard.db (plus WAL/SHM if any)
REM   then runs `python -m agent.seed --reset --days 7`.
REM
REM   Double-click this file, or run from any terminal.
REM   The backend (uvicorn) should be stopped first - the
REM   SQLite file is held open while the API is running.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0backend"

echo.
echo ============================================================
echo   PPE Guard - demo reset and reseed
echo ============================================================
echo   Working dir : %CD%
echo   Target DB   : %CD%\agent\ppe_guard.db
echo ============================================================
echo.
echo If the backend (uvicorn) is currently running, stop it now
echo (Ctrl+C in that terminal) so the SQLite file can be deleted.
echo.
echo Press any key to continue, or close this window to abort...
pause >nul
echo.

REM ---------- 1. Delete the existing DB (and WAL / SHM journals) ----------
set "REMOVED=0"
if exist "agent\ppe_guard.db" (
    del /q "agent\ppe_guard.db"
    if exist "agent\ppe_guard.db" (
        echo [reset] ERROR: could not delete agent\ppe_guard.db
        echo [reset] Is the backend still running? Stop uvicorn and try again.
        echo.
        pause
        exit /b 1
    )
    set "REMOVED=1"
)
if exist "agent\ppe_guard.db-wal" del /q "agent\ppe_guard.db-wal"
if exist "agent\ppe_guard.db-shm" del /q "agent\ppe_guard.db-shm"
if "%REMOVED%"=="1" (
    echo [reset] removed agent\ppe_guard.db ^(plus WAL/SHM if present^)
) else (
    echo [reset] no existing agent\ppe_guard.db to remove - first-time setup
)
echo.

REM ---------- 2. Activate the venv if one exists ----------
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
    echo [reset] activated venv: %VIRTUAL_ENV%
) else (
    echo [reset] WARNING: venv\Scripts\activate.bat not found - using system Python
)
echo.

REM ---------- 3. Run the seeder ----------
echo [reset] reseeding 7 days of synthetic demo data...
echo ------------------------------------------------------------
python -m agent.seed --reset --days 7
set "EXITCODE=%ERRORLEVEL%"
echo ------------------------------------------------------------
echo.

if "%EXITCODE%"=="0" (
    echo ============================================================
    echo   DONE. Restart uvicorn to pick up the fresh DB.
    echo     cd backend
    echo     uvicorn main:app --reload
    echo ============================================================
) else (
    echo ============================================================
    echo   FAILED - seeder exited with code %EXITCODE%
    echo   Check the output above for the error.
    echo ============================================================
)
echo.
pause
endlocal
exit /b %EXITCODE%
