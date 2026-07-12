@echo off
rem ===========================================================================
rem  run.bat
rem
rem  Single entry point for course workspace provisioning on Windows.
rem
rem  Nothing is installed. No administrator rights are required. Everything this
rem  creates lives beside this file and is disposable:
rem
rem      .\modules     staged PowerShell modules
rem      .\logs        run log
rem
rem  PowerShell 7 (pwsh) is used when present, because it is faster and its
rem  package handling is cleaner. Otherwise Windows PowerShell 5.1, which ships
rem  with Windows and needs no installation, is used instead. The provisioning
rem  script stages the MicrosoftTeams and Microsoft.Graph.Authentication modules
rem  into .\modules with Save-Module, which copies files without installing or
rem  registering anything in your profile.
rem
rem  Usage:
rem      run.bat                Provision (prompts, then confirms before writing)
rem      run.bat --dry-run      Print every intended write without performing it
rem      run.bat --probe        Read-only Class Notebook capability check, writes nothing
rem      run.bat --teams        List existing team names so the group naming policy can be
rem                             inferred. Read-only; creates nothing.
rem      run.bat --logout       Forget the cached sign-in; the next run will prompt
rem      run.bat --clean        Delete .\modules and .\logs, then exit
rem ===========================================================================

setlocal
cd /d "%~dp0"

set "PS_SCRIPT=provision_course_workspaces.ps1"
set "PS_ARGS="

rem ---------------------------------------------------------------------------
rem  Argument handling
rem ---------------------------------------------------------------------------
if /i "%~1"=="--dry-run" set "PS_ARGS=-DryRun"
if /i "%~1"=="-dry-run"  set "PS_ARGS=-DryRun"

if /i "%~1"=="--probe" set "PS_SCRIPT=probe_classnotebook.ps1"
if /i "%~1"=="-probe"  set "PS_SCRIPT=probe_classnotebook.ps1"

if /i "%~1"=="--teams" set "PS_ARGS=-ListTeams"
if /i "%~1"=="-teams"  set "PS_ARGS=-ListTeams"

if /i "%~1"=="--logout" set "PS_ARGS=-Logout"
if /i "%~1"=="-logout"  set "PS_ARGS=-Logout"

if /i "%~1"=="--clean" goto clean
if /i "%~1"=="-clean"  goto clean

if not exist "%PS_SCRIPT%" (
    echo [run.bat] %PS_SCRIPT% was not found in %CD%
    echo [run.bat] Place run.bat and %PS_SCRIPT% in the same folder.
    exit /b 1
)

rem ---------------------------------------------------------------------------
rem  Engine selection: PowerShell 7 if available, else Windows PowerShell 5.1
rem ---------------------------------------------------------------------------
where pwsh >nul 2>&1
if %ERRORLEVEL%==0 (
    echo [run.bat] Engine: PowerShell 7
    pwsh -NoProfile -ExecutionPolicy Bypass -File ".\%PS_SCRIPT%" %PS_ARGS%
    goto done
)

echo [run.bat] Engine: Windows PowerShell 5.1
powershell -NoProfile -ExecutionPolicy Bypass -File ".\%PS_SCRIPT%" %PS_ARGS%
goto done

rem ---------------------------------------------------------------------------
rem  Cleanup
rem ---------------------------------------------------------------------------
:clean
echo [run.bat] Removing .\modules, .\logs, and the cached sign-in from %CD%
if exist ".\modules"        rmdir /s /q ".\modules"
if exist ".\logs"           rmdir /s /q ".\logs"
if exist ".\.tokencache.xml" del /q ".\.tokencache.xml"
echo [run.bat] Done. Nothing was installed, so nothing else needs undoing.
goto end

:done
if %ERRORLEVEL% neq 0 (
    echo.
    echo [run.bat] The script exited with code %ERRORLEVEL%.
)

:end
echo.
pause
endlocal
