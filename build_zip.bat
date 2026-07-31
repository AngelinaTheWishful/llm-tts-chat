@echo off
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
set "VERSION=v1.0.2"
set "ZIP_NAME=llm-tts-chat-%VERSION%.zip"
set "BUILD_DIR=%TEMP%\llm-tts-chat-build"
set "OUT_DIR=%SCRIPT_DIR%exports"

echo [INFO] 打包版本: %VERSION%

echo [INFO] 清理旧构建目录...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

echo [INFO] 复制项目文件...
copy "%SCRIPT_DIR%app.py" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%requirements.txt" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%pyproject.toml" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%pytest.ini" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%go-llm-tts.bat" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%install_deps.bat" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%config.example.json" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%README.md" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%CHANGELOG.md" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%使用百科全书.md" "%BUILD_DIR%\" >nul
copy "%SCRIPT_DIR%.gitignore" "%BUILD_DIR%\" >nul

xcopy "%SCRIPT_DIR%modules" "%BUILD_DIR%\modules\" /e /i /y >nul
xcopy "%SCRIPT_DIR%locales" "%BUILD_DIR%\locales\" /e /i /y >nul
xcopy "%SCRIPT_DIR%tests" "%BUILD_DIR%\tests\" /e /i /y >nul
xcopy "%SCRIPT_DIR%migrations" "%BUILD_DIR%\migrations\" /e /i /y >nul
xcopy "%SCRIPT_DIR%characters" "%BUILD_DIR%\characters\" /e /i /y >nul

echo [INFO] 清理用户数据目录...
for /d /r "%BUILD_DIR%" %%D in (__pycache__) do if exist "%%D" rmdir /s /q "%%D"
for %%D in (logs conversations exports trash temp_audio venv __pycache__ backup) do (
    if exist "%BUILD_DIR%\%%D" rmdir /s /q "%BUILD_DIR%\%%D"
)

echo [INFO] 打包为 zip...
if exist "%OUT_DIR%\%ZIP_NAME%" del "%OUT_DIR%\%ZIP_NAME%"
powershell -Command "Compress-Archive -Path '%BUILD_DIR%\*' -DestinationPath '%OUT_DIR%\%ZIP_NAME%' -Force"

echo [INFO] 清理构建目录...
rmdir /s /q "%BUILD_DIR%"

echo [INFO] 完成: exports\%ZIP_NAME%
pause