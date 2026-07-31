# LLM 角色扮演聊天 + GPT-SoVITS TTS

基于 Gradio 的角色扮演聊天应用，集成 LLM（OpenAI 兼容 API）与 GPT-SoVITS 语音合成。

## 功能概述

- **LLM 角色扮演聊天**：DeepSeek/OpenAI/通义等 OpenAI 兼容 API，多提供商故障转移
- **GPT-SoVITS TTS 语音合成**：角色音色克隆，长文本分片合成，音量标准化
- **多会话管理**：新建/切换/删除/重命名/导出/导入（zip）
- **角色系统**：JSON 配置 + 头像 + 参考音频 + Lorebook 世界观知识库
- **角色编辑**：WebUI 表单编辑（性格/口癖/背景/CoT/Lorebook/头像）
- **消息收藏/搜索/统计**：星标收藏、会话内搜索、全局统计看板
- **多语言界面**：中文/日本語/English 热切换
- **主题**：浅色/深色 + 自定义颜色
- **问候语流程**：新建会话自动播放角色语音问候

## 环境要求

- Windows 10/11
- GPT-SoVITS v2Pro（已配置好 runtime Python 环境）
- LLM API Key

## 安装步骤

1. 确保 GPT-SoVITS API 服务已启动：`runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880`
2. 运行 `install_deps.bat` 安装依赖（创建 venv）
3. 运行 `go-llm-tts.bat` 启动应用
4. 首次启动进入配置向导，填写 GPT-SoVITS 路径、TTS API 地址、LLM 配置

## 使用方法

1. **配置向导**：首次启动填写 GPT-SoVITS 本体路径、TTS API 地址、LLM 提供商（Base URL/API Key/模型）
2. **选择角色**：左栏下拉选择角色，自动应用预设音色模型
3. **新建会话**：点击"新建会话"，自动播放角色问候语
4. **开始聊天**：输入消息，Enter 发送（Shift+Enter 换行）；回复自动合成语音
5. **角色编辑**：左栏"编辑角色"面板可修改性格/背景/Lorebook/上传头像
6. **工具**：导出/导入会话、搜索、统计看板
7. **界面语言**：顶部下拉切换 中/日/英；主题切换浅色/深色

## 常见问题 (FAQ)

- **TTS 无声音**：确认 GPT-SoVITS API 已启动，状态栏显示"🟢 TTS API 在线"
- **API Key 安全**：API Key 经 base64 编码存储于 config.json，请勿分享该文件
- **长回复语音中断**：超过 800 字的回复会自动分片合成

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)

## 贡献指南

- 分支策略: main（稳定） + dev（开发），禁止直接提交 main
- Commit 规范: Conventional Commits（英文标题 + 中文正文）
- 代码规范: PEP 8 + ruff（`ruff check app.py modules/ tests/`）
- 测试: `pytest tests/ -v`（85+ 项单元/集成测试）
- 开发流程详见 [开发工作流程.md](开发工作流程.md)

## 开发文档

- [项目开发需求书.md](项目开发需求书.md) — 完整需求文档（内部文档，不随仓库发布）
- [开发工作流程.md](开发工作流程.md) — 开发流程与版本管理规范

## 许可证

MIT
