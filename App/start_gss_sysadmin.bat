@echo off
setlocal enabledelayedexpansion
title GSS - System Admin
cd /d "%~dp0"

echo ============================================================
echo  GSS - System Admin launcher
echo ============================================================
echo  This starts the same GSS server as start_gss.bat, and makes
echo  sure the platform-wide SystemAdmin login below always works
echo  by (re)creating it and locking its password on every start.
echo  Do not run this at the same time as another GSS launcher --
echo  they all share one server on port 5000.
echo ============================================================
echo.

rem --- Locate a REAL Python interpreter ------------------------------------
rem Windows ships fake "python"/"python3" stubs under WindowsApps (the App
rem Execution Alias feature) that exist on PATH even when Python is not
rem installed - they just print a Microsoft Store nag and do nothing. So
rem "where python" alone is not a reliable check; each candidate's actual
rem "--version" output is checked instead. The "py" launcher (installed by
rem the official python.org installer, at C:\Windows\py.exe) is tried first
rem since it isn't affected by that alias.
set "PYEXE="

for /f "delims=" %%v in ('py -3 --version 2^>^&1') do set "PYOUT=%%v"
echo !PYOUT! | findstr /b /r "Python [0-9]" >nul
if not errorlevel 1 set "PYEXE=py -3"

rem The Store stub's own nag text is "Python was not found; run without
rem arguments to install..." - which itself starts with the word "Python ",
rem so matching on that alone would wrongly accept it. A real interpreter's
rem "--version" output is "Python 3.x.y" - a digit right after "Python " is
rem required so the fake message ("Python was...") is correctly rejected.
if not defined PYEXE (
    for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYOUT=%%v"
    echo !PYOUT! | findstr /b /r "Python [0-9]" >nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    for /f "delims=" %%v in ('python3 --version 2^>^&1') do set "PYOUT=%%v"
    echo !PYOUT! | findstr /b /r "Python [0-9]" >nul
    if not errorlevel 1 set "PYEXE=python3"
)

if not defined PYEXE (
    echo ERROR: A working Python installation was not found on this machine.
    echo ^(Windows may show a "python"/"python3" command that only opens the
    echo Microsoft Store - that does not count as an install.^)
    echo.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    echo and make sure "Add python.exe to PATH" is checked during install.
    echo If "python" opens the Microsoft Store even after installing, disable
    echo the alias at Settings -^> Apps -^> Advanced app settings -^>
    echo App execution aliases -^> turn off "python.exe" / "python3.exe".
    echo.
    pause
    exit /b 1
)

echo Using Python:
%PYEXE% --version

rem --- Create the virtual environment on first run ------------------------
if not exist "venv\Scripts\activate.bat" (
    echo Creating Python virtual environment ^(first run only^)...
    %PYEXE% -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call "venv\Scripts\activate.bat"

rem --- Install / update dependencies ---------------------------------------
echo Checking dependencies...
pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)

set "FLASK_APP=app.py"

rem --- First-run database setup ---------------------------------------------
rem Only creates the schema here -- it deliberately does NOT seed the first
rem tenant (that's start_gss_tenant.bat's job). A SystemAdmin belongs to no
rem tenant, so it doesn't need one to exist first.
if not exist "instance\gss.db" (
    echo.
    echo First run detected - creating the database...
    flask init-db
    echo.
)

rem --- Ensure the SystemAdmin login exists, and lock its password ----------
rem create-system-admin only creates the account once (a second run just
rem reports it already exists, harmlessly); set-password then forces the
rem password below every single time this launcher starts, so the printed
rem login always works even if it was changed from inside the app since the
rem last run.
echo Ensuring the SystemAdmin login exists...
flask create-system-admin --username Zbhatti2 --display-name Zbhatti2 --password Zebragss1
flask set-password --username Zbhatti2 --password Zebragss1

echo.
echo ============================================================
echo  Log in as System Admin with:
echo    Username: Zbhatti2
echo    Password: Zebragss1
echo  This takes you straight to Tenant Management, not a
echo  tenant's Dashboard -- a SystemAdmin belongs to no tenant.
echo ============================================================
echo.

echo Starting the GSS server...
echo   Local access:    http://127.0.0.1:5000
echo   Network access:  http://%COMPUTERNAME%:5000   ^(other computers on your network^)
echo.
echo Press CTRL+C in this window to stop the server.
echo.

rem Open the browser a couple seconds after launch, without blocking the
rem server. /B runs this in the background with no console window of its
rem own (rather than flashing open a second window that closes itself a
rem couple seconds later) -- one less window to notice or clean up.
start /B "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000/login"

rem Deliberately the LAST command in this script -- nothing follows it, so
rem Ctrl+C here closes this window directly. Anything after flask run
rem (an echo, a pause) is exactly what makes Windows pop up its own
rem "Terminate batch job (Y/N)?" confirmation on Ctrl+C (that prompt only
rem appears when there's more script left to run after the interrupted
rem command) and would otherwise leave the window sitting on a "press any
rem key to continue" pause after you've already stopped the server.
flask run --host=0.0.0.0 --port=5000
