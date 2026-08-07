# Changelog

本文件记录所有已发布版本的应用变更。

## [v1.3.6] - 2026-08-07

### 新增

- **TTS 根路径统一自动探测与前端刷新**（章节九十四）：GPT-SoVITS 根路径 `gsv_root` 启动自动探测 + 前端一键全量刷新
  - 探测优先级三级：① `config.json` 已有值且目录有效（含 `api_v2.py`）→ 直接使用；② 读启动报告 `logs/startup_report_*.jsonl` 提取一键启动脚本已探测目录；③ 只读同级扫描 `上级\GPT-SoVITS*`（不改动 `go-llm-tts.bat`）
  - 探测/刷新成功自动写回 `config.json.gsv_root`（写锁 + 原子写入），启动探测成功即写回
  - 前端「重新探测」按钮两处（侧栏「配置」面板 + 状态栏区域），同一 handler 全量刷新 = 重探测根路径 + 重扫 GPT/SoVITS 权重 + 重解析当前角色参考音频 + 重应用音色预设
  - 探测失败顶部提示 `[CFG-008]`，保留旧值，仍可手动输入保存
  - 训练模块联动：`gsv_training.gsv_root` 为空时自动继承主 `gsv_root`
- **角色运行时路径字段永不落盘**（章节九十四）：`save_character` 保存前剥离 `_dir`/`_portrait`/`_ref_audio`/`_background` 等 `_` 前缀运行时注入字段，仅加载时内存注入，彻底消除本机绝对路径泄漏与跨机失效

### 测试

- pytest 全量 **216** 项（新增 13 项：test_path_resolver 三级探测/写回/失败兜底/训练联动 10 项，save_character 剥离运行时字段，ui_service refresh_gsv_root 成功/失败）
- e2e_live **54/54**（新增 B26：刷新未配置失败提示 / 配置有效成功回填）

## [v1.3.5] - 2026-08-07

### 新增

- **聊天窗口左上角角色头像**（章节九十三）：聊天框左上角固定头部显示当前角色 `portrait.png` 头像 + 角色名
  - 独立固定头部（`gr.HTML`），不随消息滚动、不遮挡聊天背景（组件外层 `.block` 透明处理，与 v1.3.3 同款）
  - 头像经 `gr.set_static_paths` 单文件注册 + `/file=` 加载（与聊天背景同款，防 403、不暴露目录/config.json）
  - 切换角色即时生效（角色下拉 change → 隐藏组件 → JS 改 `img src`），无页面刷新
  - 无 `portrait.png` 时回落**角色名首字圆形占位**，不显示空白
  - 侧栏「聊天背景」折叠栏新增「头像尺寸」下拉（128px/256px），即时生效并持久化到 `theme_config.json` 的 `chat_avatar` 节（写锁与主题切换共用）

### 测试

- pytest 全量 **203** 项（新增：theme chat_avatar 默认/合并/非法值回落/CSS 注入/保存，ui_service select_character 头像路径存在/缺失）
- e2e_live **50/50**（新增 B24a-d：头像路径返回、头像状态含角色名、尺寸持久化、头像经 `/file=` 加载）

### 修复

- **头像尺寸同步组件暴露为可见数字框**（发布后缺陷）：`chat-avatar-size-state`（`gr.Number`）漏加隐藏 CSS，聊天区上方显示只读数字框（128/256）；已补 `display:none` 并新增 e2e B25 回归用例（e2e **51/51**）

## [v1.3.4] - 2026-08-06

### 文档

- **GitHub 账户改名**：在线仓库地址更新为 `github.com/AngelinatheMellowWish/llm-tts-chat` 与 `github.com/AngelinatheMellowWish/Object1687`（账户由 AngelinaTheWishful 改名）；README 三语/使用百科全书/全部开发记录中的仓库链接与 Git 身份同步更新
- 三语 README 版本徽章统一至 v1.3.4

## [v1.3.3] - 2026-08-06

### 新增

- **角色「予愿安洁莉娜」入库**（章节九十二配套）：`characters/予愿安洁莉娜/character.json` 随包发布（含人设/问候语/口癖/背景/喜好/厌恶/行为准则/CoT/Lorebook/音色预设）；媒体文件（头像/背景/参考音频）不入库
- **予愿安洁莉娜专属音色**（本地）：GPT-SoVITS v2Pro 训练（中配·溯浔，38 段官方语音），GPT/SoVITS 权重与归档见机密目录（`dev_archive/secret/`、`gsv_training/`）

### 修复

- **聊天背景不显示**：Gradio 组件外层 `.block` 有不透明背景（`--block-background-fill`），盖住 `#chat-area` 的背景图与遮罩；已对 `#chat-area` 内 `.block/.chatbot/.chatbot-wrap/.messages` 统一透明，背景与遮罩透明度即时生效
- **背景上传字段规范化**（v1.3.1 遗留）：上传背景时 `character.json.background` 误写为原始上传文件名，现改为规范化 `background.{ext}`，与落盘文件一致

## [v1.3.2] - 2026-08-06

### 新增

- **多语言 README**：新增 `README.en.md`（English）与 `README.ja.md`（日本語），与中文 `README.md` 三语互跳（顶部语言切换链接）；采用 GitHub 原生 README 本地化约定，仓库首页自动显示语言切换
- **README 内容对齐**：三语 README 同步补充 v1.3.1 角色聊天背景功能说明；中文 README 修正指向机密文档的失效链接

## [v1.3.1] - 2026-08-06

### 新增

- **角色聊天背景**（章节九十二）：在角色卡文件夹放置背景图片（`background.png` 或 `character.json` 的 `background` 字段），聊天区背景随角色选择即时切换，不刷新页面
  - 多格式支持 png/jpg/jpeg/webp/gif（**支持动图**），单文件 ≤200MB；`background` 字段优先，缺失回落固定文件名
  - 呈现：cover 铺满 + 半透明遮罩，遮罩透明度/颜色可在左侧栏「聊天背景」折叠栏调节，即时生效并持久化（自动随明暗主题，可手动选色）
  - 「启用角色背景」全局开关，关闭后回退主题 `chat_background`
  - 角色编辑面板新增「聊天背景」上传（gr.File 保留动图原始格式）+ 即时预览
  - 背景经 Gradio `/file=` 端点加载（`gr.set_static_paths` 单文件注册，仅暴露该图，不暴露整目录/config.json）
- **e2e 背景用例**：新增 B23a/B23b/B23c（背景路径返回、遮罩持久化、`/file=` 加载）

## [v1.3.0] - 2026-08-06

### 新增

- **AI 回复重新生成**（章节五十七）：🔄 按钮重新生成最后一条 AI 回复，旧回复保留为版本记录（`edited_from`），失败自动恢复旧回复（含音频）
- **消息编辑**：✏️ 编辑最后一条 AI 回复，历史版本可追溯（`edited_from`/`edited_at`）
- **自动备份**（Q8）：启动 + 定时（`backup.interval_hours`，默认 24h）备份会话/角色/记忆/配置到 `backup/`，保留最近 `keep_count` 份，新增 `backup` 配置节
- **训练面板多语言**：训练管理面板与重新生成/编辑按钮改走 i18n，补齐中/日/英
- **e2e 训练面板覆盖**：新增 B15a/B15b/B15c（未选实验预览/打包、训练配置保存）

### 修复

- **TTS 健康检查假阳性**（Q1）：`check_api` 仅 5xx 视为服务异常，404/2xx 视为在线，不再任意响应都算在线
- **日志 Handler 堆积**（Q2）：文件 Handler 全局共享，控制台 Handler 按 logger 独立（修复 `isinstance` 误判文件 Handler 为控制台、app.log 级别被覆盖）
- **主题跟随系统丢自定义色**（Q3）：`mode="system"` 时仅叠加用户显式声明的自定义色，深浅基色不再被整套浅色覆盖
- **错误码 404 误分类**（Q4）：openai 404 仅在消息含 model 关键词时归「模型名不可用」，其余归 CFG-007「接口或服务不可用」
- **会话管理配置接线**（Q5）：`ConvManager` 读取 `app.max_history_rounds`/`app.summarize_trigger_rounds`（原用默认参数）
- **头像大小限制**（Q6）：上传图片超过 80MB 拒绝并友好提示
- **角色卡导入大小限制**（Q11）：单文件超过 50MB 拒绝导入
- **迁移备份完整性**（Q12）：迁移前备份/回滚扩展至 characters/conversations/memories 数据目录
- **报告清理性能**（Q13）：`_cleanup` 每小时至多执行一次，避免每次写入全目录扫描
- **并发会话快照**（Q10）：`send_message` 捕获会话快照，避免并发发送/切换会话时写错会话；`regenerate` 失败路径保留聊天显示与旧音频；导入会话解压异常清理残留；`edit_message` 兼容无 msg_id 的导入会话（编辑最后一条）

### 测试

- pytest 全量 **184** 项（新增：check_api 5xx、头像 80MB、角色卡 50MB、备份、消息编辑、搜索 role 筛选、zip 炸弹/结构校验等）
- e2e_live **43/43**（新增 B15a/B15b/B15c）

## [v1.2.1] - 2026-08-06

### 修复

- **训练模块产物清理计数虚增**：`cleanup_intermediates` 原在 `shutil.rmtree(ignore_errors=True)` 静默失败时仍计入 `cleaned`；现删除后以 `target.exists()` 复核，仅统计实际删除成功的项
- **训练模块实验名时间戳后缀误剥离**：`restore_archive` 从 zip 文件名解析实验名时，实验名自身以 `_YYYYMMDD_HHMMSS` 结尾会被错误剥离；现贪婪匹配末尾 15 位时间戳，实验名完整保留
- **训练模块归档检测 glob 元字符误匹配**：`has_archive` 原直接拼接实验名到 glob 模式，实验名含 `[`/`*` 时误匹配；现用 `glob.escape` 转义
- **训练 CLI 配置加载依赖工作目录**：`training_cli._build_ops` 原用 `ConfigManager()` 相对 CWD 加载 `config.json`，从其他目录运行 `train_pack.bat` 时 `gsv_training` 配置（gsv_root/archive_dir/restore_dir）丢失；现显式基于项目根加载
- **train_pack.bat 无 pushd + 退出码丢失**：原脚本不切换工作目录且以 `pause` 结尾吞掉 CLI 退出码；现 `pushd` 到项目根、保存 `%ERRORLEVEL%`、`exit /b` 返回，便于自动化判断成败
- **训练音色串角色**：切换角色时「训练音色」下拉未重置，保存新角色会把上一角色的音色权重写入其音色预设；现 `load_character_to_editor` 补第 13 项输出将下拉重置为 None

### 新增

- **训练模块回归测试**：新增 5 项（时间戳后缀实验名解析 / glob 特殊字符 / 清理计数仅统计实际删除 / CLI 项目根配置加载 + 命令行优先 / 角色加载重置训练音色），pytest 全量 165 项

## [v1.2.0] - 2026-08-05

### 新增

- **一键启动（章节八十九）**：`go-llm-tts.bat` 改造为同时启动 TTS API 与 app：
  - 自动探测同级 GPT-SoVITS 目录（含 `api_v2.py`）并校验 runtime Python
  - 9880 已监听则跳过 TTS 启动，避免重复启动
  - TTS API 与 app 各开一个独立窗口；TTS 未就绪时 app 仍启动（不阻塞，显示离线）
  - 全部相对路径（`%~dp0`），与 GPT-SoVITS 目录保持同级即可
  - 每步写入 `logs/startup_report_*.txt/.jsonl`，带 `STP-xxx` 错误码
- **全系统错误码系统（章节九十）**：`modules/error_codes.py`
  - 模块前缀 + 编号错误码（LLM-001/TTS-003/STP-004/CFG-006 等 40+ 码）
  - `classify()` 将 openai/requests/业务异常归类为稳定错误码；不改变异常类型（兼容既有测试）
  - WebUI 错误横幅/提示带 `[错误码]`，如 `[LLM-004] 没有可用的 LLM 提供商`
- **按次运行报告（章节九十）**：`modules/reporter.py` + `report_cli.py`
  - `startup_report`（一键启动/应用启动步骤）+ `run_report`（每次发送消息全流程步骤与耗时）
  - 文本 `.txt` + JSON Lines `.jsonl` 双份，按天命名并保留 7 天
  - 发送消息 12 个步骤（输入校验→角色→会话→记忆→上下文→Lorebook→LLM→摘要→TTS→保存）逐条记录，失败带错误码
- **连通性测试与角色卡导入报错带码**：LLM/TTS 分项结果、导入失败等均显示 `[CODE]` 友好文案
- **新增测试**：`test_error_codes.py`（14 项）+ `test_reporter.py`（5 项）；e2e 新增 B21 报告文件与错误码断言
- **操作指引面板改进（章节八十八.4）**：主界面「使用帮助」宽度限制为侧栏宽度（`max-width` 跟随 `sidebar_width`，默认 320px），不再占满整行；主界面与侧栏帮助面板均新增「✖ 关闭」按钮

### 修复

- **修复 e2e 报告断言 bug**：B21 错误码匹配由子串比较改为正则 `\[(?:LLM|CFG|TTS|...)-\d+\]`
- **`start /D` 目录含 `..\` 导致 api_v2.py 无法启动**：父目录用 `%~fI` 规范化，去除 `..\`（一键启动实测 TTS 就绪）

## [v1.1.9] - 2026-08-04

### 新增

- **配置连通性测试按钮（章节八十八）**：配置面板一键测试 LLM/TTS 连通性，即时显示 ✅/❌ 与具体错误（超时/401/模型不存在/连接失败等）；API Key 留空自动回退已保存 Key
- **提供商预设模板（章节八十八）**：下拉选 DeepSeek/OpenAI/通义千问/智谱，自动填入 base_url 与模型名，只需填 API Key
- **操作指引按钮（章节八十八）**：主界面「❓ 使用帮助」与侧栏「❓ 侧栏说明」内置按钮，点击显示简明操作流程
- **主题跟随系统**：主题下拉新增「跟随系统」，自动适配深浅色
- **失败一键重发**：LLM/TTS 发送失败时保留输入框内容，点击「发送」即可重试（消息已回滚不重复）

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
