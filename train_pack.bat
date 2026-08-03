@echo off
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [ERROR] 未找到虚拟环境，请先运行 install_deps.bat
    pause
    exit /b 1
)

"%VENV_PY%" "%SCRIPT_DIR%modules\training_cli.py" %*
pause