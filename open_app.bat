@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
set "UI_DIR=%PROJECT_DIR%ui\dist"
set "WORKSPACE_DIR=%PROJECT_DIR%workspace"
set "APP_URL=http://127.0.0.1:4173/"
set "LLAMA_SERVER=D:\Documents\Models\llama.cpp-b10516-cuda13.3\llama-server.exe"
set "LLAMA_MODEL=D:\Documents\Models\m5p-downloads\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
set "COMFY_ROOT=D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI"
set "COMFY_PYTHON=%COMFY_ROOT%\.venv\Scripts\python.exe"
set "COMFY_MODEL_CONFIG=C:\Users\lpak\AppData\Roaming\ComfyUI\extra_models_config.yaml"

if not "%~1"=="" set "WORKSPACE_DIR=%~f1"

if not exist "%UI_DIR%\index.html" (
    echo [ERROR] Khong tim thay giao dien tai:
    echo         %UI_DIR%\index.html
    echo.
    pause
    exit /b 1
)

set "PYTHON_CMD="
if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    "%PROJECT_DIR%.venv\Scripts\python.exe" -c "import audio_story" >nul 2>&1
    if not errorlevel 1 set PYTHON_CMD="%PROJECT_DIR%.venv\Scripts\python.exe"
)

if defined PYTHON_CMD goto python_ready

py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.11 -c "import audio_story" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3.11"
)

if defined PYTHON_CMD goto python_ready

python -c "import sys; assert sys.version_info >= (3, 11); import audio_story" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

:python_ready

if not defined PYTHON_CMD (
    echo [ERROR] Khong tim thay Python de chay may chu giao dien.
    echo         Hay cai Python 3.11 tro len va cai project bang pip install -e .
    echo.
    pause
    exit /b 1
)

echo Audio Story Studio
echo ------------------
echo Dia chi: %APP_URL%
echo Workspace: %WORKSPACE_DIR%
echo Nhan Ctrl+C de dung ung dung.
echo.

start "" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%PROJECT_DIR%scripts\wait_open_studio.ps1" -Url "%APP_URL%" -TimeoutSeconds 180
pushd "%UI_DIR%"
%PYTHON_CMD% -m audio_story.cli studio --workspace "%WORKSPACE_DIR%" --ui-directory "%UI_DIR%" --host 127.0.0.1 --port 4173 --llama-server "%LLAMA_SERVER%" --llama-model "%LLAMA_MODEL%" --comfy-python "%COMFY_PYTHON%" --comfy-root "%COMFY_ROOT%" --comfy-model-config "%COMFY_MODEL_CONFIG%"
set "SERVER_EXIT=%ERRORLEVEL%"
popd

if not "%SERVER_EXIT%"=="0" (
    echo.
    echo [ERROR] Khong the khoi dong Audio Story Studio.
    echo         Kiem tra xem cong 4173 co dang duoc su dung hay khong.
    pause
)

exit /b %SERVER_EXIT%
