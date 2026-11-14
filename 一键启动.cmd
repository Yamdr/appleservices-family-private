@echo off
setlocal
set "TEMP=D:\APP\.runtime\appleservices-family-private\temp"
set "TMP=%TEMP%"
set "PSModuleAnalysisCachePath=D:\APP\.runtime\appleservices-family-private\powershell-analysis-cache"
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-ui.ps1"
if errorlevel 1 (
    echo.
    echo Startup failed. Please share the error message above.
    pause
    exit /b 1
)
endlocal
