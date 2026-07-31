; LLM 角色扮演聊天 + GPT-SoVITS TTS 安装器
; 编译方式: makensis build_installer.nsi（需安装 NSIS）

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define APP_NAME "LLM 角色扮演聊天"
!define APP_VERSION "1.0.0"
!define APP_EXE "go-llm-tts.bat"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\LLMTTS"

Name "${APP_NAME}"
OutFile "llm-tts-chat-${APP_VERSION}-setup.exe"
InstallDir "$PROFILE\llm-tts-chat"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin

; 默认安装语言
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "主程序" SEC_MAIN
    SetOutPath "$INSTDIR"
    File /r "build\*"

    ; 创建桌面快捷方式
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

    ; 写卸载信息
    WriteUninstaller "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

    ; 检测 GPT-SoVITS（提示，不阻断）
    ${If} ${FileExists} "$INSTDIR\..\GPT-SoVITS-v2pro-20250604\runtime\python.exe"
        MessageBox MB_OK "检测到 GPT-SoVITS。请确认 api_v2.py 服务已启动。"
    ${Else}
        MessageBox MB_OK|MB_ICONINFORMATION "未检测到 GPT-SoVITS。请在首次启动向导中指定其本体路径。"
    ${EndIf}
SectionEnd

Section "卸载" SEC_UNINST
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$INSTDIR\uninstall.exe"
    DeleteRegKey HKLM "${UNINST_KEY}"
    ; 保留用户数据目录（characters/conversations/config.json）
    RMDir /r "$INSTDIR\logs"
    RMDir /r "$INSTDIR\__pycache__"
    RMDir /r "$INSTDIR\venv"
    RMDir "$INSTDIR"
SectionEnd
