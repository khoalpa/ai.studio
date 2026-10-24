@echo off
setlocal

set "APP_DIR=%~dp0"
set "PYTHONPATH=%APP_DIR%src"
set "RUNTIME_ROOT=%APP_DIR%.runtime"
set "APP_URL=http://127.0.0.1:8765"

cd /d "%APP_DIR%"

rem Replace an older server for this workspace so the browser and API use the same code.
powershell -NoProfile -Command "$runtimeRoot = [IO.Path]::GetFullPath($env:RUNTIME_ROOT); Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','py.exe') -and $_.CommandLine -like '*-m ai_story serve*' -and $_.CommandLine -like ('*' + $runtimeRoot + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
powershell -NoProfile -Command "Start-Sleep -Seconds 1"

where py >nul 2>nul
if not errorlevel 1 (
    powershell -NoProfile -Command "Start-Process py -ArgumentList @('-3.10','-m','ai_story','serve','--root',$env:RUNTIME_ROOT,'--host','127.0.0.1','--port','8765') -WorkingDirectory $env:APP_DIR -WindowStyle Hidden"
    goto open_browser
)

where python >nul 2>nul
if not errorlevel 1 (
    powershell -NoProfile -Command "Start-Process python -ArgumentList @('-m','ai_story','serve','--root',$env:RUNTIME_ROOT,'--host','127.0.0.1','--port','8765') -WorkingDirectory $env:APP_DIR -WindowStyle Hidden"
    goto open_browser
)

echo Python 3 was not found.
echo Install Python 3.10 or newer, then run this file again.
pause
exit /b 1

:open_browser
echo Starting AI Story at %APP_URL% ...
powershell -NoProfile -Command "Start-Sleep -Seconds 2"
start "" "%APP_URL%"
endlocal
