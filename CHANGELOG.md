# Changelog

本文件记录所有已发布版本的应用变更。

## [v1.1.8] - 2026-08-04

### 新增

- **单实例防护（章节八十七）**：启动时创建 `app.lock`（含 PID）杜绝重复启动；`find_available_port` 不再自动换端口，配置端口被占用即提示退出（避免多实例并存导致配置互相覆盖）
- **LLM 与 TTS 超时分离（章节八十七）**：TTS 合成独立 20 秒预算（config `tts.synthesis_timeout`），超时则先回复文字并提示"语音合成超时（>20s），已先回复文字"，不再阻塞文字展示
- **CI 质量增强**：CI 新增 bandit 安全扫描；新增无外部依赖冒烟测试（启动 app 校验 HTTP 200 与关键端点）；锁定 openai 版本

### 修复

- **导出会话无响应（章节八十七）**：`export_file` 改 `visible=bool(path)`，有会话导出显示下载链接、无会话/失败给 `gr.Info` 弹窗提示

## [v1.1.7] - 2026-08-04

### 修复

- **并发数配置未生效**：`demo.queue(default_concurrency_limit=2)` 硬编码，高级设置 `performance.max_llm_concurrency` 保存后从未接线；现队列并发改用该配置（R10 真实生效；TTS 由 TTSSerializer 全局串行化，天然并发=1）
- **移动端分隔条残留占位**：移动端媒体查询只隐藏 `#sidebar-resizer`，其容器 `#sidebar-resizer-wrap` 仍占 5px；补隐藏
- **配置向导 max_tokens/temperature 存 float**：`build_config` 统一 `int(max_tokens)` / `float(temperature)`（与侧栏保存一致）

## [v1.1.6] - 2026-08-04

### 修复

- **LLM 调用失败（"没有可用的 LLM 提供商"）**：会话级提供商下拉选择「跟随全局」时，前端把标签文本而非空值写入 `provider.txt`，`get_session_provider` 返回无效提供商名 → 调用失败；现下拉 value 改用空串、`set_session_provider` 归一化"跟随全局"→空值
- **配置保存无弹窗提示**：各保存按钮（配置/高级设置/训练配置/角色）保存后新增 `gr.Info` 弹窗（toast）即时反馈，原状态文字保留

### 新增

- **LLM 调用步骤级日志**：每次调用记录 发送准备（提供商数量/active/session 提供商）/ 尝试提供商（base_url/model）/ 调用开始 / 成功或失败（错误类型+详情）/ token 用量 / 最终提供商与回复长度，便于快速定位失败环节

## [v1.1.5] - 2026-08-04

### 修复

- **侧栏展开后折叠栏内容跑到右侧/消失**：`#sidebar-col` 默认 `flex-wrap:wrap`，打开内容较高的折叠栏（如「配置」表格）后内容超高触发横向换列（左 65→380→695），框体文字被挤到右侧并产生横向滚动；强制 `flex-wrap:nowrap` + `overflow-x:hidden` 后单列竖排、仅纵向滚动

## [v1.1.4] - 2026-08-04

### 修复

- **LLM 调用失败（API Key 含空白）**：粘贴 API Key 时带入的首尾空白/换行会使 httpx 拒绝发送请求（`Illegal header value`），表现为"连接错误 / LLM 调用失败"；现于配置保存与 LLMClient 处统一 `.strip()` 清理
- **侧栏折叠按钮无响应 + 无法拖动调整宽度**：折叠事件原以 `gr.State` 作为输入，Gradio 4.44.1 对 `gr.State` 不生成 API 参数（`/info` 中 `params=[]`），浏览器提交报 "Too many arguments" 且服务端不执行 → 折叠不生效；改用隐藏 `gr.Number(sidebar-collapse-state)` 同步组件 + JS 切换 DOM 持久化；侧栏改为 `visible=True`，初始折叠由 INIT_JS 依据隐藏组件值控制（Gradio `visible=False` 的隐藏无法被 JS 覆盖，会导致初始折叠后无法展开）
- **侧栏右部空白挤占聊天窗**：Gradio 内联 `flex-grow:1` 覆盖 CSS `flex:0 0 320px` 致侧栏变宽；主行内隐藏组件形成的 `form` 与分隔条容器也被 `flex-grow` 占位；修复 `#sidebar-col` 禁增长、隐藏组件移入聊天列、分隔条容器固定 5px，聊天窗恢复剩余空间
- **TTS 合成失败（无参考音频）**：角色无 `recommended_settings` 音色预设时既不设权重也不设参考音频，`/tts` 请求 `ref_audio_path` 为空返回 400；`apply_preset` 回退到扫描默认 GPT/SoVITS 权重，并从训练实验日志（`5-wav32k` 首条 + `2-name2text.txt` 文本）推导参考音频，TTS 即可用

## [v1.1.3] - 2026-08-04

### 修复

- **首次启动「完成配置」按钮无响应**：`INIT_JS`（章节八十五侧栏拖动初始化脚本）原为立即执行函数（IIFE），被 Gradio 4.44.1 以 `(js)()` 包装后产生 `Unexpected token ';'` 语法错误，页面加载即抛异常，导致前端事件系统初始化失败、所有按钮无响应；改为函数表达式后恢复（含侧栏拖动/折叠、语言/主题切换等）

## [v1.1.2] - 2026-08-03

### 新增

- **角色卡导入**：支持 TavernAI（PNG/JSON，含 chara_card_v2）、RisuAI、Chub、Character.AI 角色卡自动格式检测导入，映射为项目角色（含头像提取与 lorebook/备选问候语）
- **移动端/响应式适配**：≤900px 窄屏自动上下堆叠布局（侧栏整行可滚动、隐藏拖动分隔条、顶栏换行）

## [v1.1.1] - 2026-08-03

### 新增

- **侧栏可拖动调整宽度**：侧栏与主区间新增可拖动分隔条，拖动调整宽度（200~600px），宽度持久化（localStorage + config.app.sidebar_width）

### 修复

- **侧栏无法折叠**：折叠按钮 JS 后处理补 `return new_state`，修复 `gr.State` 被写为 undefined 导致折叠状态不稳定；折叠/展开联动隐藏分隔条

## [v1.1.0] - 2026-08-03

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
