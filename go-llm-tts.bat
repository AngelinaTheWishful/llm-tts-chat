@echo off
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%venv\Scripts\python.exe"

echo [INFO] 请确保 GPT-SoVITS API (api_v2.py) 已在运行中
echo [INFO] 启动 LLM 角色扮演聊天...

if not exist "%VENV_PY%" (
    echo [ERROR] 未找到虚拟环境，请先运行 install_deps.bat
    pause
    exit /b 1
)

"%VENV_PY%" "%SCRIPT_DIR%app.py" %*
pause
