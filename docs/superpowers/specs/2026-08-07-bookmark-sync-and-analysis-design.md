# NextX 收藏同步与深度拆解设计

**状态：** 已批准  
**日期：** 2026-08-07  
**首版范围：** 单一 X 账号、本地优先、1–5 分钟准实时同步、人工确认发布

## 1. 目标

NextX 把关联账号的 X Bookmarks 自动同步为本地 Obsidian `Signal`，对新增收藏做低成本整理，并允许用户选择单条内容进行深度拆解、选题裁决和推文创作。

成功标准：

- 工作电脑在线时，新收藏在 5 分钟内进入 Obsidian。
- 重复同步不会生成重复 Signal。
- 同步失败不覆盖已有笔记或同步状态。
- 用户可从任意收藏 Signal 发起深度拆解。
- 深度拆解只向所选 Agent 提供当前收藏及必要上下文，不上传整个收藏库。
- “深度拆解”不会自动发布，也不会自动修改 Self 或 Playbook。

## 2. 产品边界

### 首版包含

- 单一已认证 X 账号。
- `twitter-cli` Bookmarks 读取和书签文件夹读取。
- 每 1–5 分钟由操作系统调度 `nextx sync-bookmarks`。
- 初次同步最近 200 条，单次增量同步最近 50 条。
- Markdown Signal、运行清单、同步状态和全局锁。
- 新收藏轻量分类所需的结构化字段。
- 单条收藏的深度拆解 Brief。
- Agent Skill 负责完成语义拆解，并可调用现有 `topic-engine` 与 `x-tweet-writer`。

### 首版不包含

- Web 前端、Obsidian 自定义插件、数据库或常驻自研守护进程。
- 多账号、多平台、团队权限或云同步。
- 自动发布、自动回复、自动私信。
- X OAuth 开发者 App。
- 自建 X 私有 GraphQL 客户端。
- 自动删除本地 Signal。
- 自动把一次表现固化为 Playbook 规则。

## 3. 运行形态

用户通过 Codex、Claude Code 或 Grok Build 对话操作；Obsidian 用于查看、编辑和审计；`nextx` CLI 是 Agent 和操作系统调度器共同调用的执行内核。

```text
X Bookmarks
  -> twitter-cli
  -> nextx sync-bookmarks
  -> normalize / validate / deduplicate
  -> Obsidian Signal
  -> Agent 轻判或深拆
  -> topic-engine Decision
  -> x-tweet-writer Artifact
  -> 人工发布
```

首版“实时”定义为工作电脑在线时 1–5 分钟轮询。X 当前没有明确提供 Bookmark 新增事件的公开推送语义，因此不承诺秒级 Webhook。

## 4. 数据模型

NextX 继续只承认四个产品原语：`Self`、`Signal`、`Decision`、`Artifact`。Bookmark 是 `Signal` 的一种来源，不增加新原语。

### Signal frontmatter

```yaml
id: "x:2084556671712477485"
type: "signal"
signal_type: "x_bookmark"
platform: "x"
source_url: "https://x.com/author/status/2084556671712477485"
author_handle: "author"
published_at: "2026-08-04T08:26:54+00:00"
captured_at: "2026-08-07T18:20:00+08:00"
collector: "twitter-cli"
bookmark_active: true
analysis_status: "pending"
media_types: ["video"]
metrics: {"likes": 58, "reposts": 2, "replies": 61, "views": 80373}
```

正文保留原帖文本、媒体链接、轻判区域、深度拆解区域和关联 Decision。

### 内部状态

`.nextx/bookmarks-state.json` 只保存：

- 已见 tweet ID 集合。
- 最近成功同步时间。
- 最近一次成功运行 ID。

`.nextx/runs/<run-id>.json` 保存本次后端、数量、接受/重复/拒绝统计和错误摘要，不保存 Cookie 或 Token。

## 5. 同步算法

### 初次同步

1. 调用 `twitter bookmarks -n 200 --json`。
2. 校验外层响应和每条收藏的最低字段。
3. 以 `x:<tweet_id>` 作为幂等键。
4. 对每条新收藏生成独立 Markdown。
5. 所有文件先写入临时文件，再以原子替换提交。
6. 所有 Signal 成功写入后才更新 state。

### 增量同步

1. 默认读取最新 50 条。
2. 本批次按 tweet ID 去重。
3. 已存在文件不覆盖，避免破坏用户批注和 Agent 分析。
4. 只写入未知 ID。
5. 即使窗口中全是已知 ID，也记录一次成功运行。

首版不依赖 X 返回可靠的收藏时间；`captured_at` 表示 NextX 首次发现时间，`published_at` 表示帖子发布时间。

### 取消收藏

增量窗口无法证明旧收藏已被取消。首版保留本地 Signal，不执行删除。后续全量对账功能只能把可确认的记录标记为 `bookmark_active: false`，不能物理删除。

## 6. 深度拆解

### 轻量处理

收藏入库时不自动运行大模型。Signal 初始状态为 `analysis_status: pending`，Today 视图可以按作者、发布时间、媒体类型和已有指标筛选。

### 按需深拆

用户说“拆解这条收藏”后，Agent：

1. 使用 CLI 生成该 Signal 的 Analysis Brief。
2. 必要时读取原帖、引用帖、Thread 和媒体。
3. 输出一句话主张、钩子、结构、证据质量、社交货币、传播动力、可迁移模式、不可照搬部分和可衍生选题。
4. 明确区分原帖事实、作者观点和 Agent 推断。
5. 将结果写入原 Signal 的 `深度拆解` 区域。
6. 只有用户要求生成选题时才调用 `topic-engine` 创建 Decision。
7. 只有 Decision 判为“做”且用户要求写稿时才调用 `x-tweet-writer`。

## 7. CLI 接口

```text
nextx init --vault <path>
nextx doctor --vault <path>
nextx sync-bookmarks --vault <path> [--limit 50] [--input-json <path>] [--dry-run]
nextx analysis-brief --vault <path> <tweet-id-or-signal-id>
```

`--input-json` 是测试和故障恢复入口，可导入既有 `twitter bookmarks --json` 输出。所有命令以非零退出码表示失败；需要给 Agent 使用的结果输出 JSON。

## 8. 可靠性与安全

- Cookie 和 Token 由 `twitter-cli`、系统钥匙串或环境变量管理，NextX 不保存认证数据。
- 同步使用单一 Vault 全局锁；并发运行直接失败，不等待。
- JSON 解析、最低字段、路径和 Vault 可写性都在写入前验证。
- 不覆盖已存在 Signal。
- state 最后更新，避免“状态已前进但文件没写完”。
- 运行清单不包含帖子全文，避免复制敏感收藏内容。
- Agent 深拆只读取用户选择的 Signal。

## 9. Obsidian 结构

```text
NextX Vault/
├── 00. Self/
├── 01. Signal/
├── 02. Decision/
├── 03. Artifact/
├── 04. Views/
│   ├── Today.md
│   └── Bookmark Inbox.md
└── .nextx/
    ├── bookmarks-state.json
    ├── runs/
    └── sync.lock/
```

Signal 文件不会因为处理状态变化而移动目录；状态由 frontmatter 表达。

## 10. 调度

核心只提供一次性 `sync-bookmarks` 命令。macOS 使用 `launchd`、Linux 使用 systemd timer、Windows 使用任务计划程序，每 180 秒调用一次。这样避免维护自研后台服务，同时满足 1–5 分钟同步目标。

## 11. 开源边界

- 核心使用 Python 3.11+ 标准库，不依赖数据库。
- `twitter-cli` 是可替换采集后端，不把其代码复制进仓库。
- Collector 的内部边界是“返回收藏 JSON”，首版只实现一个后端，不创建单实现工厂或插件系统。
- 未来官方 X API 适配器只有在用户确实需要 OAuth 稳定性时再增加。

## 12. 验收测试

- 给定两条新收藏，生成两个 Signal 和正确 state。
- 再次导入相同收藏，不生成重复文件，也不覆盖人工批注。
- 一条收藏缺少 ID 时整次运行失败，state 不更新。
- dry-run 报告新增数量但不写文件。
- 锁已存在时同步失败。
- Analysis Brief 能从 `x:<id>` 和裸 tweet ID 找到同一 Signal。
- `doctor` 能区分二进制存在、认证成功、真实 Bookmark 读取成功。
