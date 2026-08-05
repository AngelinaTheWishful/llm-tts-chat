@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  LLM 角色扮演 + TTS 一键启动（章节八十九）
rem  自动探测同级 GPT-SoVITS 目录 -> 启动 TTS API -> 启动 app
rem  全部使用相对路径（基于 %~dp0），报告写入 logs\startup_report_*
rem ============================================================
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_ROOT=%SCRIPT_DIR:~0,-1%"
set "VENV_PY=%SCRIPT_DIR%venv\Scripts\python.exe"
rem 规范化父目录（去除 ..\，否则 start /D 无法解析含 ..\ 的目录）
for %%I in ("%SCRIPT_DIR%..") do set "PARENT=%%~fI"
set "GSV_DIR="
set "FOUND="

echo ============================================
echo   LLM 角色扮演 + TTS 一键启动
echo ============================================

rem ---------- 1. venv 校验（STP-005） ----------
if not exist "%VENV_PY%" (
    echo [ERROR] [STP-005] 未找到虚拟环境（venv\Scripts\python.exe），请先运行 install_deps.bat
    pause
    exit /b 1
)
pushd "%SCRIPT_DIR%"
"%VENV_PY%" -m modules.report_cli startup_report OK "一键启动开始" --detail "%SCRIPT_ROOT%"

rem ---------- 2. 探测同级 GPT-SoVITS 目录（STP-001/STP-002） ----------
for /d %%D in ("%PARENT%\GPT-SoVITS*") do (
    if not defined FOUND (
        if exist "%%D\api_v2.py" (
            set "GSV_DIR=%%D"
            set "FOUND=1"
        )
    )
)
if not defined FOUND (
    echo [ERROR] [STP-001] 未检测到 GPT-SoVITS 目录（%PARENT%\GPT-SoVITS*，需含 api_v2.py）
    "%VENV_PY%" -m modules.report_cli startup_report FAIL "探测 GPT-SoVITS 目录" --code STP-001 --detail "%PARENT%"
    popd
    pause
    exit /b 1
)
"%VENV_PY%" -m modules.report_cli startup_report OK "探测 GPT-SoVITS 目录" --detail "%GSV_DIR%"

rem ---------- 3. runtime python 校验（STP-003） ----------
if not exist "%GSV_DIR%\runtime\python.exe" (
    echo [ERROR] [STP-003] 未找到 runtime Python：%GSV_DIR%\runtime\python.exe
    "%VENV_PY%" -m modules.report_cli startup_report FAIL "校验 runtime python" --code STP-003 --detail "%GSV_DIR%\runtime\python.exe"
    popd
    pause
    exit /b 1
)
"%VENV_PY%" -m modules.report_cli startup_report OK "校验 runtime python" --detail "%GSV_DIR%\runtime\python.exe"

rem ---------- 4. 检查 TTS 端口 9880（STP-006） ----------
netstat -ano | findstr ":9880" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] TTS API（9880）已在运行，跳过启动
    "%VENV_PY%" -m modules.report_cli startup_report OK "检查 TTS 端口 9880" --detail "已监听，跳过启动"
    goto :start_app
)
"%VENV_PY%" -m modules.report_cli startup_report OK "检查 TTS 端口 9880" --detail "未监听，准备启动"

rem ---------- 5. 新窗口启动 api_v2.py ----------
echo [INFO] 启动 GPT-SoVITS TTS API（api_v2.py，新窗口）...
start "GPT-SoVITS TTS API" /D "%GSV_DIR%" runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880
"%VENV_PY%" -m modules.report_cli startup_report OK "启动 TTS API (api_v2.py)" --detail "新窗口"

rem ---------- 6. 等待 9880 就绪（STP-004，最长约 120s） ----------
echo [INFO] 等待 TTS API 就绪（模型加载约 30~90s）...
set /a WAIT_COUNT=0
:wait_tts
netstat -ano | findstr ":9880" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto :tts_ready
set /a WAIT_COUNT+=1
if !WAIT_COUNT! GEQ 60 (
    echo [WARN] [STP-004] TTS API 启动超时（约 120s），app 仍继续启动（TTS 可能离线）
    "%VENV_PY%" -m modules.report_cli startup_report WARN "等待 TTS API 就绪" --code STP-004 --detail "超时"
    goto :start_app
)
ping 127.0.0.1 -n 3 >nul
goto :wait_tts
:tts_ready
"%VENV_PY%" -m modules.report_cli startup_report OK "TTS API 就绪" --detail "9880 已监听"

:start_app
rem ---------- 7. 新窗口启动 app ----------
echo [INFO] 启动 LLM 角色扮演聊天（新窗口）...
start "LLM 角色扮演聊天" /D "%SCRIPT_DIR%" "%VENV_PY%" app.py %*
"%VENV_PY%" -m modules.report_cli startup_report OK "启动 app" --detail "新窗口"

echo.
echo [INFO] 已完成一键启动：
echo   - GPT-SoVITS TTS API（若未在运行）
echo   - LLM 角色扮演聊天
echo [INFO] 启动报告：%SCRIPT_ROOT%\logs\startup_report_*.txt（及 .jsonl）
popd
endlocal
exit /b 0
