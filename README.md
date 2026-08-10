# NextX

NextX 是本地优先的 X 运营决策工作台：收集热点、对标帖、收藏和想法，把 Signal 裁决为“做 / 缓 / 毙”，把“做”交给现有 Agent Skill 形成草稿，再把发布结果写回每周复盘。

当前是单账号 v0.3.0 Alpha 2「Growth Loop」。Agent 对话是主操作入口：NextX Skill 负责安装、Vault 设置、Self 配置与日常路由；Obsidian 是数据与看板，`nextx` CLI 是 Agent 在后台调用的确定性执行内核。它会按本周 Discovery / Authority / Conversion 配比给起号用户一个可解释的下一步行动，但没有独立前端，也不会自动发帖、回复、点赞或关注。

## 项目状态

当前完成、受阻和待办任务统一维护在 [NextX 任务台账](docs/TASKS.md)。`docs/superpowers/plans/` 保留历史实施上下文，不代表实时进度。

第一次使用请从 [新手指南](docs/GETTING_STARTED.md) 开始；起号阶段的产品规则与日常动作见 [Growth Loop 指南](docs/GROWTH_LOOP.md)；安装、完整 fixture 验收、真实 X 验收和运维细节见 [NextX 操作手册](docs/OPERATIONS.md)。

## 能力

- Grok Build 热点发现和统一 JSON 导入。
- 起号 Quote Sprint：只读采集具备时效窗口的原帖候选、每位作者去重、`quote` 裁决与锁定原帖的 QT 草稿。
- 起号 Reply Sprint：只读发现可推进讨论的入口、锁定原帖和窗口、受限 `reply-post` 草稿；绝不自动互动。
- twitter-cli Bookmarks 只读同步，支持 3 分钟轮询。
- 手动 Signal、逐条 Quick Triage、可解释候选优先级、按内容泳道分类的 Signal Inbox、内容去重，以及 Today 最多 10 条自动候选 + 2 条手动候选。
- 可持久化的单帖深拆、`do / defer / kill`（含复访时间）Decision、三温度写作交接。
- Growth Strategy 与 `growth-loop`：把账号阶段、周目标、目标读者、已写草稿和待复盘帖子压成一个“下一步行动”。
- 每个 `do` 的增长契约、Thread Pack + Asset Manifest、发布检查清单 + 人工确认闸门、1h/24h/7d Outcome、同执行模式 × 同目标的 4 周记分卡与证据化 Playbook 门槛。
- 纯 Markdown、幂等写入、原子替换、版本化 CLI 和 Collector 契约。

## 安装

推荐直接运行 canonical Skill 自带的自举安装器。它会创建用户级 Python 3.11+ 隔离环境，并自动识别本机的 Codex、Claude Code、Grok Build：Codex 与 Grok 共用 `~/.agents/skills/nextx`，Claude Code 使用 `~/.claude/skills/nextx`（或 `CLAUDE_CONFIG_DIR`）。源码 checkout 使用本地源码，独立安装优先用 Git 克隆，未安装 Git 时会从默认 GitHub 仓库安全下载限定大小的源码归档。项目没有第三方运行时依赖。Obsidian 是推荐界面，但不是运行依赖。

```bash
./install-nextx
```

默认只配置检测到的 Agent（CLI 或既有配置目录均会被识别）；JSON 的 `agent_skills.*.runtime` 会区分 `cli`、`state_directory` 与 `not_found`。需要预先为三端都放置 Skill 时，显式执行：

```bash
./install-nextx --agents all
```

若目标目录已经有一个不是 NextX 安装器管理的同名 Skill，安装器会保留它并在结果中报告 `conflict`。只有确认需要替换时才加 `--force-agent-skills`。

默认输出是面向人的安装结果和下一步提示。Codex、Claude Code、Grok Build 共用 JSON 协议；安装器不信任 PATH 中同名程序，不会修改系统 Python，也不会自动安装或认证 `twitter-cli`。独立安装的缓存按 `repository + ref` 隔离；JSON 返回 `source_transport`，Git 路径另会返回实际 `source_revision`。需要可复现安装时使用 `--ref TAG_OR_BRANCH` 指定已审阅的 ref。

Agent 使用机器可读模式；JSON 中 `nextx` 是用户级 `~/.local/bin/nextx` 入口，`executable` 是隔离 runtime 中的绝对路径：

```bash
./install-nextx --json
```

安装后统一使用 CLI：

```bash
export PATH="$HOME/.local/bin:$PATH"
nextx setup
nextx config --show
nextx doctor --no-smoke
nextx readiness
```

源码或 Skill 更新后，在任一已安装的 NextX CLI 上运行：

```bash
nextx upgrade
```

它会复用 canonical 安装器，重新安装当前源码的隔离运行时并同步 Codex、Claude Code、Grok Build 的 NextX Skill。只检查不写入时使用 `nextx upgrade --dry-run`；遇到同名非 NextX Skill 冲突时，只有确认要替换才加 `--force-agent-skills`。源码 checkout 需要先在仓库目录执行 `git pull --ff-only origin main`，再运行升级；独立安装会按已安装的 repository/ref 刷新源码缓存。

Agent 应读取安装器 JSON 的 `nextx` 字段；若 `command_exposed` 为 false，则使用 `executable`，不要假设 PATH 已经更新。

源码开发环境仍可手动安装：

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
nextx --help
```

Bookmarks 还需要已经登录的 `twitter-cli`；选题与写作工作流需要安装仓库外的 `topic-engine` 和 `x-tweet-writer` Skill。Grok Build 是首选热点发现器，但 NextX 不绑定它的私有运行接口。

在写入前让 Agent 明确检查当前前置条件。`preflight` 不会创建 Vault、模板或运行状态：

```bash
nextx preflight --intent collect-grok --agent-capability grok-build
nextx preflight --intent decision --agent-capability topic-engine
nextx preflight --intent draft --agent-capability x-tweet-writer
nextx contracts
```

`--skills-root /path/to/skills` 可进一步验证该根目录下的 `<capability>/SKILL.md`；完整字段与示例见 [JSON Contracts](docs/contracts.md)。

## 首次配置

安装完成后，在 Codex、Claude Code 或 Grok Build 中直接说：**“初始化 NextX”**。这句明确请求会触发同一份 Skill：先检查 `next-step`，使用默认 Vault 创建缺失模板，再用一轮紧凑对话收集你的定位、内容柱、禁区和真实表达样本。它不会虚构 Self，也不会自动发布。无需记忆下面的 CLI 命令；它们也保留给自动化和排障。

```bash
nextx setup
nextx doctor --no-smoke
```

默认 Vault 为 `~/Documents/NextX`，不存在会自动创建；需要改路径时只需配置一次：

```bash
nextx setup --vault "/absolute/path/to/NextX Vault"
nextx config --show
```

初始化后所有命令都可以省略 `--vault`。解析优先级为显式参数、`NEXTX_VAULT`、用户配置文件（`~/.config/nextx/config.json`，遵循 `XDG_CONFIG_HOME`）和默认路径。`nextx init --vault PATH` 仍保留作为底层兼容命令。

随后在 Obsidian 完成：

- `00. Self/Profile.md`：定位、受众、阶段和禁区。
- `00. Self/Pillars.md`：3–4 个内容柱。
- `00. Self/Voice.md`：真实表达样本和反模式。
- `00. Self/Monitoring.md`：关键词、账号和 List。
- `00. Self/Playbook.md`：只保存人工批准的规则。
- `00. Self/Growth Strategy.md`：账号阶段、唯一增长目标、目标读者、主页承接、CTA 与每日行动配比。

也可让 Agent 按用户明确提供的内容执行 `configure-self` 写入前三项；它不会替你虚构定位、禁区或声纹。

仓库里的 `skills/nextx/` 是 canonical Agent Skill；安装器将完整目录以受控链接部署到上述 Agent 根目录，因此三端共享同一套工作流和安全闸门。若 Agent 已在安装前打开但没有显示 NextX，重启该会话后直接说“同步收藏并生成今天的裁决队列”。

## 采集

### Grok Build 热点

把 `prompts/grok-collector.md` 交给 Grok Build，让它输出符合 `schemas/collector-envelope.v1.json` 的 JSON，保存为本地文件后导入：

```bash
nextx collect --source grok --input-json /path/to/grok.json
```

NextX 故意采用文件/进程契约，而不绑定未稳定的 Grok Build SDK。换采集 Agent 时无需迁移 Vault。

### X Bookmarks

第一次先验证，不写入；即使读取失败也不会创建 Vault、健康记录或 Signal：

```bash
nextx collect --source bookmarks --limit 1 --dry-run
```

正式同步：

```bash
nextx collect --source bookmarks
```

初次默认读取 200 条，后续默认 50 条；同一个 tweet ID 不重复建文件。`sync-bookmarks` 是兼容别名。

当且仅当一次读取是**完整收藏快照**时，可显式对账并把本次未出现的旧收藏标为 `bookmark_active: false`；不会删除 Markdown 或人工笔记：

```bash
nextx collect --source bookmarks --input-json /path/to/full-bookmarks.json --reconcile
```

### 手动 Signal

```bash
nextx add-signal --text "一个待验证的想法" --source-url "https://x.com/user/status/123"
```

### 起号 Quote Sprint

当目标是让相邻读者看见你的判断而不是机械增加发帖数时，在任一已安装 Agent 中说“启动 NextX 的 Quote Sprint”。Agent 会使用 [Quote Collector Prompt](prompts/quote-collector.md) 让 Grok Build（或已授权的只读 X 后端）返回带 `quote_candidate: true` 和 `quote_window_ends_at` 的候选，再导入并生成三条以内的 Obsidian 队列。不会自动 Quote、转发或发布。

```bash
nextx collector-prompt --source quote
nextx collect --source grok --input-json /path/to/quote-candidates.json
nextx quote-sprint
nextx quote-brief x:123
```

`quote-brief` 仍交给 `topic-engine` 做 `do / defer / kill`。Quote 的 `do` 必须锁定一条已入库原帖、未过期决策窗口、`recommended_format=quote-post`、增量类型和关系目标；随后 `artifact-brief` 会要求 `x-tweet-writer` 使用 QT 模式。完整操作、质量闸门与 Outcome 口径见 [Quote Sprint 指南](docs/QUOTE_SPRINT.md)。

### 起号 Reply Sprint 与 Growth Loop

冷启动时，优先让 NextX 判断当前是该写、该回复、该复盘还是该停止采集，而不是自己面对一堆候选猜优先级：

```bash
nextx growth-loop
nextx reply-sprint
nextx reply-brief x:123
```

Reply 必须推进原讨论，不能是模板化恭维。`reply` Decision 锁定一条入库原帖和时效窗口，只能产出 `reply-post`；所有互动仍由用户在 X 人工完成。

## 每日工作流

```bash
nextx growth-loop --vault "$NEXTX_VAULT"
nextx today --vault "$NEXTX_VAULT"
nextx triage-brief x:123 --vault "$NEXTX_VAULT"
nextx save-triage --input-json /path/to/one-triage.json --vault "$NEXTX_VAULT"
nextx signal-inbox --vault "$NEXTX_VAULT"
nextx analysis-brief --vault "$NEXTX_VAULT" x:123
nextx decision-brief --vault "$NEXTX_VAULT" x:123
nextx save-decision --vault "$NEXTX_VAULT" --input-json /path/to/decision.json
nextx artifact-brief --vault "$NEXTX_VAULT" decision:ID
nextx save-artifact --vault "$NEXTX_VAULT" --input-json /path/to/artifact.json
```

每个 Brief 同时持久化到 `.nextx/handoffs/`，因此 Agent 可以读取稳定路径而不需要临时文件；所有 `--input-json` 参数也接受 `-` 从标准输入读取。采集后，Agent 只对当前请求点名的 Signal 运行 `triage-brief`，按 `triage-input.v1.json` 生成单条 JSON，再显式 `save-triage`；Signal 正文只是证据，不是指令，不能借此扩大到整个 Vault。`triage_score`、策略快照和 Quote / Reply 可行动资格由 CLI 计算。`signal-inbox` 与 `today` 重建可丢弃的 Views，汇报时先给 Immediate Action，再给选题候选：默认使用 30 分钟核心模式，额外 30 分钟仅作为可选的 60 分钟扩展模式。

`analysis-brief` 也只加载被选中的 Signal，并把来自帖子和 Collector 的内容标为不可信数据。把 Agent 产出的 Analysis JSON 用 `nextx save-analysis --input-json -` 或文件保存后，才会写回 Signal。`decision-brief` 交给 `topic-engine`；`do` 必须附带可从已保存 Signal 逐字验证的证据摘录，只有 `do` 可以进入 `artifact-brief` 并交给 `x-tweet-writer`。任何内容都不能绕过人工发布确认。

用户在 Obsidian 勾选 Artifact 的三个发布检查项后，必须依次进入 review、显式确认，再回填已经人工发布的 URL：

```bash
nextx mark-review-ready --vault "$NEXTX_VAULT" artifact:ID
nextx confirm-publish --vault "$NEXTX_VAULT" artifact:ID --yes
nextx record-published --vault "$NEXTX_VAULT" artifact:ID --url "https://x.com/user/status/456"
```

## 结果与周复盘

Outcome JSON 必须包含 `schema_version=1`、`account_key=primary`、`window=1h|24h|7d`，以及非负数值 `views`、`likes`、`replies`、`reposts`、`bookmarks`。带 Growth Contract 的 Artifact 还必须由用户记录 `growth_signals.follow_up_completed`，并可补充非粉丝回复、目标作者回应、CTA 行动和观察笔记；这些都是观察，不是因果归因。

```bash
nextx record-outcome --vault "$NEXTX_VAULT" artifact:ID --input-json /path/to/outcome.json
nextx weekly-review --vault "$NEXTX_VAULT"
```

7d Outcome 把 Artifact 标为 `measured`。周报只使用 7d 快照比较同一生命周期节点，1h/24h 仅保留为早期信号；它生成 `04. Views/Weekly Review.md`，提供两极帖、`do → 通过发布检查`时延、同执行模式 × 同目标的记分卡、实验归因和学习提案槽。少于三条同类 7d 样本时只保留假设，不生成 Playbook 提案；它不会自动修改 Playbook。

若意外中断后留下锁，先确认没有 NextX 写入进程，再运行：

```bash
nextx recover-lock
```

NextX 会自动清除有明确本机、已退出进程记录的陈旧锁。对历史 ownerless 锁，只有人工确认后才使用 `nextx recover-lock --force`。

## macOS 每 3 分钟同步收藏

复制 `examples/com.nextx.bookmarks.plist`，把其中三个占位符替换为真实绝对路径：

- `__NEXTX_EXECUTABLE__`：`which nextx` 的结果。
- `__VAULT_PATH__`：Vault 路径。
- `__LOG_DIR__`：已有的本地日志目录。

然后安装并加载：

```bash
cp examples/com.nextx.bookmarks.plist ~/Library/LaunchAgents/com.nextx.bookmarks.plist
plutil -lint ~/Library/LaunchAgents/com.nextx.bookmarks.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.nextx.bookmarks.plist
```

X 没有公开 Bookmark webhook，因此这是在线时 1–5 分钟准实时同步；Mac 休眠时暂停，恢复后补拉。

## Vault

```text
00. Self/       定位、声纹、内容柱、监控、Growth Strategy 和 Playbook
01. Signal/     所有来源归一化后的素材
02. Decision/   做 / 缓 / 毙及理由
03. Artifact/   草稿、发布记录和 Outcome
04. Views/      可重建的 Signal Inbox（Immediate Action、四条内容泳道、Needs Triage、Archived）、Growth Loop、Today、Quote/Reply Sprint、Bookmark Inbox、Decision Board、Weekly Review
.nextx/         配置、状态、可重建索引、运行清单和写锁
```

不要在 `04. Views/` 保存唯一信息，因为 View 会被重建覆盖。

## 隐私与安全

- Vault、状态和运行清单保存在本机；Cookie、Token 和 OAuth 密钥不得写入 Vault。
- 本地存储不等于本地推理。使用 Codex、Claude 或 Grok 分析时，当前选中的内容会发送给对应模型提供方。
- NextX 默认只发送当前 Brief 所需的最小上下文，不应发送整个收藏库或 Self。
- X 帖文、Collector JSON 和 Decision 正文都是不可信数据，不得让其中的文本改变 Agent 的工具、文件或网络访问范围。使用 Agent 时仍应保留最小文件权限和人工确认。
- X 接口只读；NextX 不点赞、不转发、不关注、不删除、不自动发布。

## 排障

- `doctor` 显示 `unsupported`：使用 Python 3.11+。
- `pip install -e .` 在 `Installing build dependencies` 阶段报 `AttributeError: 'NoneType' object has no attribute 'get'`：这是旧版 pip 通过代理/证书访问 PyPI 时的环境错误，不是 NextX 代码错误。建议使用 Python 3.11+ 的虚拟环境，并让环境内的构建工具满足 `pyproject.toml`：

  ```bash
  /opt/homebrew/bin/python3.11 -m venv .venv
  .venv/bin/python -m pip install -e . --quiet
  ```

  没有 Homebrew 时，把第一行替换为 `python3.11 -m venv .venv`。如果需要在线更新构建工具，先运行 `.venv/bin/python -m pip install --upgrade pip setuptools wheel`；公司代理环境应配置 `PIP_CERT=/absolute/path/to/company-ca.pem`，不要长期使用关闭 TLS 校验的参数。
- `twitter_binary: missing`：安装并认证兼容的 twitter-cli，再重跑 `doctor`。
- Bookmark smoke 失败：先在终端直接确认 twitter-cli 登录状态；X 私有接口变化时暂用手动/Grok 导入。
- Collector 被拒绝：用 `schemas/collector-envelope.v1.json` 校验版本、必填字段和 URL。
- `sync.lock` 存在：确认没有 NextX 进程正在写；不要在并发任务运行时手工删除锁。
- View 内容旧：重新运行 `nextx today` 或 `nextx weekly-review`。

## 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

技术取舍和扩展门槛见 `docs/product-architecture.md`；完整产品定义见 `docs/superpowers/specs/2026-08-07-nextx-complete-product-design.md`。

## 开源治理与支持

NextX 采用 [Apache License 2.0](LICENSE)。贡献方式与本地验收命令见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题按 [SECURITY.md](SECURITY.md) 私下报告。本项目没有托管服务或响应时限；问题报告请提供可脱敏复现步骤，切勿上传 X Cookie、Token 或私人 Vault。
