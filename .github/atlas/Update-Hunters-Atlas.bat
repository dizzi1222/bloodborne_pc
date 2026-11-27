@echo off
setlocal
title Hunter's Atlas Updater for bbport
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%update-atlas.ps1" (
    set "PS_SCRIPT=%SCRIPT_DIR%update-atlas.ps1"
) else if exist "%SCRIPT_DIR%updater\update-atlas.ps1" (
    set "PS_SCRIPT=%SCRIPT_DIR%updater\update-atlas.ps1"
) else (
    echo Could not find update-atlas.ps1 next to this .bat file.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo [Atlas Updater] Finished with error code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
