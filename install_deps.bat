@echo off
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%venv"

rem 依次查找可创建 venv 的 Python（runtime 的 3.9 无 venv 模块，故补充系统 Python）
set "PY_CANDIDATES=C:/GPT-SoVITS/GPT-SoVITS-v2pro-20250604\runtime\python.exe C:\Program Files\Python310\python.exe C:\Python314\python.exe"

echo [INFO] 查找可用的 Python...
set "PYTHON="
for %%P in (%PY_CANDIDATES%) do (
    if not defined PYTHON (
        if exist "%%P" (
            "%%P" -c "import venv" >nul 2>&1
            if not errorlevel 1 set "PYTHON=%%P"
        )
    )
)

if not defined PYTHON (
    echo [ERROR] 未找到可用的 Python（需要支持 venv 模块）
    pause
    exit /b 1
)
echo [INFO] 使用 Python: %PYTHON%
"%PYTHON%" --version

echo [INFO] 检查虚拟环境...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [INFO] 创建虚拟环境...
    "%PYTHON%" -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

echo [INFO] 安装依赖...
"%VENV_DIR%\Scripts\pip" install -r "%SCRIPT_DIR%requirements.txt"

echo [INFO] 安装 ruff（代码规范检查）...
"%VENV_DIR%\Scripts\pip" install ruff

echo [INFO] 完成
pause
