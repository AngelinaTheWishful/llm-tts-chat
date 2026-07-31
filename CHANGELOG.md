# Changelog

本文件记录所有已发布版本的应用变更。

## [v1.0.0] - 2026-07-31

### 新增

- **Phase 1 项目骨架**：config 管理（写锁/原子写入/数据版本/迁移框架）、双文件日志、BaseManager 基类、首次启动配置向导、venv 独立环境
- **Phase 2 TTS + LLM 客户端**：
  - GPT-SoVITS REST 调用（串行化队列/指数退避重试/长文本分片合成/音量标准化/Markdown 剥离/模型本地扫描）
  - OpenAI 兼容 API 调用（非流式/多提供商故障转移/限流重试/实际 token 用量记录）
- **Phase 3 角色 + 会话**：
  - 角色管理（CRUD/文件夹与 zip 导入导出/头像 1:1 裁切/预设音色应用/回收站删除）
  - 会话管理（多会话/摘要压缩/内存缓存/zip 导入导出/路径穿越防护）
  - Lorebook 关键词匹配（jieba 分词 + 同义词扩展）、结构化 system prompt 构建、注入防护模式 C
- **Phase 4 Gradio UI**：左右分栏、对话流程（输入校验→上下文→LLM→TTS→保存）、问候语语音、健康检查轮询、Enter 发送
- **Phase 5 角色编辑 + 多语言 + 主题**：WebUI 角色编辑（性格/口癖/背景/CoT/Lorebook/头像）、中/日/英三语热切换、浅色/深色主题
- **Phase 6 收藏/搜索/统计/导入导出**：消息星标收藏、会话内/全局搜索、统计看板、会话 zip 导入导出
- **Phase 7 测试 + CI**：85+ 项单元/集成测试、GitHub Actions CI（ruff + pytest）、Issue 模板
- **Phase 8 打包**：build_zip.bat 一键打包、NSIS 安装器脚本、数据迁移框架

### 修复

- `threading.Lock` 死锁 → 改用 `threading.RLock`
- `decrypt_api_key` 非 base64 明文误解码 → `validate=True`
- 语言/主题下拉存中文显示名导致失效 → 改用 locale/light-dark 代码值
- 无角色发送时产生脏会话 → 先校验角色再创建会话

### 已知限制

- 停止生成（HTTP 连接中断）、消息重新生成（多版本切换）待后续版本
