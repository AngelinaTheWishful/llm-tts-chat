# Changelog

本文件记录所有已发布版本的应用变更。

## [v1.1.0] - 开发中（2026-08-03）

### 新增

- **训练结果打包/恢复 + 中间素材清理工具（章节八十二）**：
  - 一键打包训练结果（精简权重 + 全量 ckpt）归档至 `gsv_training/archives/`
  - 打包校验成功后清理中间素材（`3-bert/` `4-cnhubert/` `5-wav32k/` `7-sv_cn/` 等）
  - 归档恢复（解压至 `gsv_training/restored/`，可选写回 GPT-SoVITS 权重目录）
  - 三入口：CLI `train_pack.bat`（list/pack/cleanup/restore/list-archives/detect）+ Gradio 侧栏「训练管理」面板 + 自动检测（提醒为主，可开全自动）
  - 角色系统联动：角色编辑可选已恢复训练音色写入音色预设
  - 新增 `gsv_training` 配置节（gsv_root/archive_dir/restore_dir/cleanup_after_pack/auto_detect/auto_full）
- **长期记忆 / RAG（章节八十四）**：
  - 角色级 + 可选全局记忆库（`memories/`），规则提取（可选 LLM 提取）+ jieba 关键词召回，注入 system prompt
  - 高级设置面板提供记忆开关/作用域/召回条数/清空记忆
- **高级设置面板（R10）**：性能（设备/并发数）、会话超时、通知音效、代理全可配置并即时生效；代理真实接线（注入 HTTP(S)_PROXY/NO_PROXY 环境变量，LLM/TTS 生效）
- **会话回收站（R3）**：删除会话移入 `trash/sessions/`（带时间戳），工具面板可恢复/清空；满 30 天提醒清理
- **会话级 LLM 提供商（R12）**：配置面板可按会话指定提供商（持久化 `provider.txt`），其余会话跟随全局
- **新示例角色**：明日方舟「暴行」（含头像 + Lorebook 11 条）

### 修复

- **R1**：用户输入不再在存储/LLM 层做 HTML 转义（避免 `&lt;` 污染上下文），XSS 由渲染层负责
- **R2**：会话文件写操作加 `threading.RLock`，避免 Gradio 并发写 `messages.json` 覆盖
- **R4**：LLM 调用失败时回滚刚保存的用户消息，避免重发重复
- **R5**：消息增加唯一 `msg_id`，收藏改为引用 msg_id；摘要压缩后自动清理孤儿收藏（收藏内容不丢）
- **R7**：TTS 离线时合成前实时探测，失败给出可见提示（不再静默无语音）
- **R8**：会话列表元数据内存缓存，减少全量文件 IO
- **R9**：训练自动检测改为轻量扫描（不计算中间素材大小）
- **R11**：配置面板 API Key 不再回填明文，留空保持不变（简易遮蔽）

## [v1.0.2] - 2026-07-31（开发中）

### 新增

- **前端侧栏改进**：侧栏可折叠（JS 切换 + 持久化）、全部折叠分组、独立滚动条、配置面板可随时重配（即时生效）

### 修复

- **GPT-SoVITS api_v2.py 真实接口适配**：`/tts` 参数（text_lang/ref_audio_path/prompt_lang/speed_factor）、健康检查改根路径、语言映射
- config.json 带 UTF-8 BOM 导致加载失败 → utf-8-sig 读取
- Gradio 音频空值 `""` 被解析为工作目录导致 PermissionError → 改用 None
- 侧栏折叠触发容器重渲染导致 Accordion 内容消失 → JS 纯 CSS 切换

## [v1.0.1] - 2026-07-31

### 修复

- 批处理文件（.bat）UTF-8 无 BOM + LF 行尾导致 cmd.exe 无法解析 → 转为 GBK + CRLF，`go-llm-tts.bat` / `install_deps.bat` / `build_zip.bat` 均正常
- 机密文档处理：需求书/工作流程改为本机专用（机密禁止上传），在线仓库已移除对应文件

### 新增

- 《使用百科全书.md》：面向零基础用户的完整公开使用指南（下载安装配置 GPT-SoVITS v2 → 克隆项目 → 全部功能使用）

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
- 批处理文件（.bat）UTF-8 无 BOM + LF 导致 cmd 无法解析 → 转为 GBK + CRLF

### 已知限制

- 停止生成（HTTP 连接中断）、消息重新生成（多版本切换）待后续版本
- 新增《使用百科全书.md》：面向零基础用户的完整公开指南
