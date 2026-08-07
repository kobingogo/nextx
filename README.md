# NextX

NextX 是本地优先的 X 运营决策工作台：收集热点、对标帖、收藏和想法，把 Signal 裁决为“做 / 缓 / 毙”，把“做”交给现有 Agent Skill 形成草稿，再把发布结果写回每周复盘。

当前是单账号 v0.1。Agent 对话是主操作入口，Obsidian 是数据与看板，`nextx` CLI 是确定性执行内核。没有独立前端，也不会自动发帖。

## 能力

- Grok Build 热点发现和统一 JSON 导入。
- twitter-cli Bookmarks 只读同步，支持 3 分钟轮询。
- 手动 Signal、今日最多 10 条自动候选 + 2 条手动候选。
- 单帖深拆、`do / defer / kill` Decision、三温度写作交接。
- Artifact 发布记录、24h/7d Outcome、Weekly Review。
- 纯 Markdown、幂等写入、原子替换、版本化 CLI 和 Collector 契约。

## 安装

要求 Python 3.11+。Obsidian 是推荐界面，但不是运行依赖。

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
nextx --help
```

Bookmarks 还需要已经登录的 `twitter-cli`；选题与写作工作流需要安装仓库外的 `topic-engine` 和 `x-tweet-writer` Skill。Grok Build 是首选热点发现器，但 NextX 不绑定它的私有运行接口。

## 首次配置

```bash
nextx init --vault "/absolute/path/to/NextX Vault"
nextx doctor --vault "/absolute/path/to/NextX Vault" --no-smoke
```

随后在 Obsidian 完成：

- `00. Self/Profile.md`：定位、受众、阶段和禁区。
- `00. Self/Pillars.md`：3–4 个内容柱。
- `00. Self/Voice.md`：真实表达样本和反模式。
- `00. Self/Monitoring.md`：关键词、账号和 List。
- `00. Self/Playbook.md`：只保存人工批准的规则。

仓库里的 `skills/nextx/` 是 canonical Agent Skill。将它安装到 Codex、Claude Code 或兼容 Skill 的 Agent 后，可以直接说“同步收藏并生成今天的裁决队列”。

## 采集

### Grok Build 热点

把 `prompts/grok-collector.md` 交给 Grok Build，让它输出符合 `schemas/collector-envelope.v1.json` 的 JSON，保存为本地文件后导入：

```bash
nextx collect --vault "$NEXTX_VAULT" --source grok --input-json /path/to/grok.json
```

NextX 故意采用文件/进程契约，而不绑定未稳定的 Grok Build SDK。换采集 Agent 时无需迁移 Vault。

### X Bookmarks

第一次先验证，不写入：

```bash
nextx collect --vault "$NEXTX_VAULT" --source bookmarks --limit 1 --dry-run
```

正式同步：

```bash
nextx collect --vault "$NEXTX_VAULT" --source bookmarks
```

初次默认读取 200 条，后续默认 50 条；同一个 tweet ID 不重复建文件。`sync-bookmarks` 是兼容别名。

### 手动 Signal

```bash
nextx add-signal --vault "$NEXTX_VAULT" --text "一个待验证的想法" --source-url "https://x.com/user/status/123"
```

## 每日工作流

```bash
nextx today --vault "$NEXTX_VAULT"
nextx analysis-brief --vault "$NEXTX_VAULT" x:123
nextx decision-brief --vault "$NEXTX_VAULT" x:123
nextx save-decision --vault "$NEXTX_VAULT" --input-json /path/to/decision.json
nextx artifact-brief --vault "$NEXTX_VAULT" decision:ID
nextx save-artifact --vault "$NEXTX_VAULT" --input-json /path/to/artifact.json
```

`analysis-brief` 只加载被选中的 Signal。`decision-brief` 交给 `topic-engine`；只有 `do` 可以进入 `artifact-brief` 并交给 `x-tweet-writer`。用户选择定稿后保存 Artifact，并在 X 人工发布：

```bash
nextx record-published --vault "$NEXTX_VAULT" artifact:ID --url "https://x.com/user/status/456"
```

## 结果与周复盘

Outcome JSON 必须包含 `schema_version=1`、`account_key=primary`、`window=24h|7d`，以及非负数值 `views`、`likes`、`replies`、`reposts`、`bookmarks`。

```bash
nextx record-outcome --vault "$NEXTX_VAULT" artifact:ID --input-json /path/to/outcome.json
nextx weekly-review --vault "$NEXTX_VAULT"
```

7d Outcome 把 Artifact 标为 `measured`。周报生成 `04. Views/Weekly Review.md`，提供两极帖、转化和最多五个学习提案槽；它不会自动修改 Playbook。

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
00. Self/       定位、声纹、内容柱、监控和 Playbook
01. Signal/     所有来源归一化后的素材
02. Decision/   做 / 缓 / 毙及理由
03. Artifact/   草稿、发布记录和 Outcome
04. Views/      可重建的 Today、Bookmark Inbox、Decision Board、Weekly Review
.nextx/         配置、状态、可重建索引、运行清单和写锁
```

不要在 `04. Views/` 保存唯一信息，因为 View 会被重建覆盖。

## 隐私与安全

- Vault、状态和运行清单保存在本机；Cookie、Token 和 OAuth 密钥不得写入 Vault。
- 本地存储不等于本地推理。使用 Codex、Claude 或 Grok 分析时，当前选中的内容会发送给对应模型提供方。
- NextX 默认只发送当前 Brief 所需的最小上下文，不应发送整个收藏库或 Self。
- X 接口只读；NextX 不点赞、不转发、不关注、不删除、不自动发布。

## 排障

- `doctor` 显示 `unsupported`：使用 Python 3.11+。
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
