# NextX 完整产品与技术架构设计

**状态：** 已由 2026-08-07 全部产品讨论批准  
**产品阶段：** v0.1，本地优先、单一 X 账号  
**一句话定位：** 把外部信号压成“做 / 缓 / 毙”，把“做”交给 Agent 变成可发草稿，并把发布结果写回判断模型。

## 1. 第一性原理

X 运营的核心不是采集更多信息，也不是一次生成更多文案，而是缩短并改善这个闭环：

```text
正确的外部信号
  -> 与当前账号的匹配判断
  -> 明确裁决
  -> 可发布内容
  -> 结果观察
  -> 下一次更好的判断
```

因此 NextX 只优化五个变量：

1. 信号质量，而不是采集数量。
2. 从“该发了”到“可发草稿”的时间。
3. 裁决是否有证据、有理由、可复查。
4. 文案是否忠于账号定位和真实声纹。
5. 结果能否形成经过人工批准的可迁移规则。

不直接改善这五项的功能不进入 v0.1。

## 2. 产品形态

NextX 不是纯终端产品，也不开发独立 Web 前端：

- **Agent 对话**是主要操作入口：Codex CLI、Claude Code、Grok Build。
- **Obsidian**是数据、看板、人工编辑和审计界面。
- **`nextx` CLI**是隐藏执行内核，供 Agent 和系统调度器调用。
- **Markdown/JSON**是本地存储，不需要数据库。

用户日常可以直接说：

- “同步今天的热点和收藏。”
- “给我今天最值得判断的 12 条。”
- “拆解第三条，判断做不做。”
- “把这个角度写成三温度版本。”
- “记录这条已发布，明天帮我看结果。”
- “做本周复盘，下周只改一件事。”

## 3. 北极星指标

主指标：从“该发了”到“可发草稿”的平均时延，目标不超过 20 分钟。

辅指标：滚动四周已发帖的曝光、互动、收藏、转发中位数是否相对改善。

护栏指标：

- 每日自动进入裁决台的 Signal 不超过 10 条，保留 2 条人工位置。
- 所有 `do` Decision 至少引用一个 Signal。
- 所有 Artifact 必须引用一个 `do` Decision。
- Playbook 每周最多批准一项变化。

## 4. 四个产品原语

### Self

账号在当前阶段“应该说什么、怎样说、不能说什么”。包含：

- 一句话定位。
- 目标受众与当前阶段。
- 3–4 个内容柱。
- 禁区和风险边界。
- 真实语言样本、声纹和反模式。
- 监控账号、关键词和 List。
- 已批准的 Playbook。

### Signal

所有可引用的外部或内部观察。来源包括：

- Grok Build 开放式热点发现。
- agent-reach/twitter-cli 对标账号、指定帖子、List 和指标。
- X Bookmarks 1–5 分钟准实时同步。
- 用户手动粘贴 URL、文本或想法。
- 自己已发布 Artifact 的结果快照。

Signal 只记录事实、来源和初步相关性，不直接代表“应该发”。

### Decision

对一个或多个 Signal 的裁决。判定只有：

- `do`：值得现在做，并有明确原创增量。
- `defer`：可能值得，但证据、时机或表达条件未成熟。
- `kill`：不符合定位、没有新增价值、风险过高或已经过时。

Decision 记录四问、证据、角度、风险、建议形态和理由码。

### Artifact

从 `do` Decision 产生的草稿或已发帖。生命周期独立于 Decision：

```text
draft -> ready -> published -> measured
```

Outcome 是 Artifact 的快照，不创建第五个原语。Learn 是读取四个原语的流程和视图，不创建持久化对象。

## 5. 核心循环

### 每日循环

```text
Self 过滤
  -> 多源 Collector
  -> Signal 归一化、去重、证据校验
  -> Today 最多 12 条
  -> topic-engine 做/缓/毙
  -> do Decision 的写作 Brief
  -> x-tweet-writer 三温度草稿
  -> 人工确认发布
  -> Artifact 记录发布 URL
```

### 每周循环

```text
Decision 统计
  + Artifact 两极帖
  + Outcome 24h/7d 快照
  -> 观察
  -> 最多 5 条 Playbook 建议
  -> 用户只批准一条
  -> 写入 Self/Playbook
```

样本少于三条只能叫“观察”，不能升级为规则。建议必须记录支持样本、反例、置信度和失效日期。

## 6. 系统架构

```text
                         +-------------------+
                         | Codex / Claude /  |
                         | Grok Build Agent  |
                         +---------+---------+
                                   |
                                   v
+----------------+       +---------+---------+       +----------------+
| Grok Discovery |------>|                   |------>| Obsidian Vault |
+----------------+       |    nextx CLI      |       | Self           |
+----------------+       | validation/state  |       | Signal         |
| agent-reach /  |------>| orchestration I/O |       | Decision       |
| twitter-cli    |       |                   |       | Artifact       |
+----------------+       +---------+---------+       | Views          |
+----------------+                 |                 +----------------+
| Manual / Files |-----------------+
+----------------+
```

业务规则归属：

- NextX：采集调度、归一化、状态、持久化、审计、Brief 组装。
- `topic-engine`：选题判断和选题卡，不写正文。
- `x-tweet-writer`：推文正文、三温度和发布前检查。
- Grok Build：X 开放式热点发现与补充研究。
- agent-reach/twitter-cli：精确账号读取、Bookmarks、原帖详情和结果指标。

NextX 不复制现有两个内容 Skill 的提示词和判断规则。

## 7. Collector 设计

### 统一采集契约

所有 Collector 输出：

```json
{
  "collector": "grok-build",
  "query": "AI agents",
  "retrieved_at": "2026-08-07T10:00:00Z",
  "items": [
    {
      "source_id": "x:123",
      "platform": "x",
      "source_url": "https://x.com/user/status/123",
      "author_handle": "user",
      "published_at": "2026-08-07T09:00:00Z",
      "text": "...",
      "metrics": {},
      "media": [],
      "source_confidence": "high",
      "discovery_reason": "为什么进入候选"
    }
  ]
}
```

没有可验证 URL 或原帖 ID 的 Grok 结论只能作为低置信观察，不能单独支撑 `do` Decision。

### 路由

| 任务 | 首选 | 备用 |
|---|---|---|
| 开放式热点发现 | Grok Build | 手动研究 |
| 对标账号 24–72h | agent-reach/twitter-cli | Grok |
| 指定帖子/Thread/指标 | agent-reach/twitter-cli | URL 手动导入 |
| X 收藏 | twitter-cli Bookmarks | 官方 X API（Phase 2） |
| 私人想法/素材 | 手动文本或文件 | 无 |

### Bookmarks

Bookmarks 是 Signal 子类型。工作电脑在线时每 180 秒调用一次单次同步；初次读取 200 条，增量读取 50 条；`x:<tweet-id>` 幂等去重。默认只入库和轻判，用户选择后才深拆。完整细节见 `2026-08-07-bookmark-sync-and-analysis-design.md`。

## 8. Signal 质量与 Today 队列

写入前执行：

1. 输入结构校验。
2. URL、tweet ID 或内容 hash 幂等。
3. 来源、采集器、查询和采集时间记录。
4. 相同原帖跨 Collector 合并，不复制文件。
5. 不让互动量替代 Self 匹配和原创增量。

Today 不使用不可解释的单一热度分。排序依次考虑：

- 人工置顶。
- Self 内容柱与禁区。
- 时效性。
- 是否与近 30 天内容重复。
- 证据强度。
- 新颖度和可增加价值。
- 传播动量。
- 作者和内容柱多样性。

自动候选最多 10 条，同一作者最多 2 条，同一内容柱最多 4 条，另留 2 条手动位置。

## 9. Decision 工作流

`topic-engine` 输出结构化 Decision，NextX 负责校验和持久化：

```yaml
id: "decision:20260807-001"
type: "decision"
verdict: "do"
signal_ids: ["x:123"]
angle: "..."
reason_code: "timely_self_fit_original_value"
recommended_format: "quote-tweet"
risk_level: "low"
evidence_sufficient: true
created_at: "..."
```

`do` 必须回答：

1. 发生了什么？
2. 为什么是现在？
3. 为什么适合这个账号说？
4. 我们增加什么，而不是复述什么？
5. 事实、时效和声誉风险是什么？

`defer` 和 `kill` 只要求简短理由码，避免在不值得做的素材上消耗分析时间。

## 10. Artifact 工作流

NextX 从 `do` Decision 生成给 `x-tweet-writer` 的 Brief，包含 Self 摘要、Decision 角度、证据链接、风险和建议形态。Agent 返回正文后保存为 Artifact：

```yaml
id: "artifact:20260807-001"
type: "artifact"
decision_id: "decision:20260807-001"
status: "draft"
format: "single-post"
created_at: "..."
published_url: null
```

NextX 不发帖。用户人工发布后记录 URL 和发布时间，状态变为 `published`。

## 11. Outcome 与 Learn

Outcome 快照追加在 Artifact 中：

```yaml
window: "24h"
captured_at: "..."
views: 12000
likes: 180
replies: 32
reposts: 20
bookmarks: 90
```

指标可由 twitter-cli 读取，也可人工输入。7 天快照后状态变为 `measured`。

周复盘至少输出：

- 做/缓/毙数量和最终转化。
- 发帖时延。
- 表现最高与最低 Artifact。
- 内容柱和形态分布。
- 原判断与 Outcome 的偏差。
- 最多 5 条 Playbook 建议。
- 下周唯一实验。

Playbook 建议由用户批准后才写入 Self。

## 12. Vault 结构

```text
Vault/
├── 00. Self/
│   ├── Profile.md
│   ├── Voice.md
│   ├── Pillars.md
│   ├── Monitoring.md
│   └── Playbook.md
├── 01. Signal/
├── 02. Decision/
├── 03. Artifact/
├── 04. Views/
│   ├── Today.md
│   ├── Bookmark Inbox.md
│   ├── Decision Board.md
│   └── Weekly Review.md
└── .nextx/
    ├── config.json
    ├── state.json
    ├── runs/
    └── sync.lock/
```

文件按类型稳定存放，不按状态移动。Views 是可重建投影，不是第五种原语。

## 13. CLI 定义

首版公开命令：

```text
nextx init --vault PATH
nextx doctor --vault PATH [--no-smoke]
nextx collect --vault PATH --source bookmarks|grok|twitter|file [options]
nextx add-signal --vault PATH --text TEXT [--source-url URL]
nextx today --vault PATH
nextx analysis-brief --vault PATH SIGNAL_ID
nextx save-decision --vault PATH --input-json FILE
nextx artifact-brief --vault PATH DECISION_ID
nextx save-artifact --vault PATH --input-json FILE
nextx record-published --vault PATH ARTIFACT_ID --url URL
nextx record-outcome --vault PATH ARTIFACT_ID --input-json FILE
nextx weekly-review --vault PATH
```

为兼容已经验证的命令，`sync-bookmarks` 保留为 `collect --source bookmarks` 的别名。

所有命令成功时向 stdout 输出一个 JSON 对象，预期失败时向 stderr 输出一个 JSON 对象并返回非零退出码。

## 14. Agent Skill

仓库只维护一份 `skills/nextx/SKILL.md`。它负责：

- 把自然语言意图映射到 CLI。
- 选择 Grok、agent-reach/twitter-cli 或手动 Collector。
- 在深拆时只加载选定 Signal。
- 调用 `topic-engine` 生成 Decision。
- 调用 `x-tweet-writer` 生成 Artifact。
- 将结构化结果交给 CLI 持久化。
- 发布、修改 Playbook 等关键动作保持人工闸门。

不为 Codex、Claude 和 Grok 复制三套规则；各 Agent 只安装同一 Skill。

## 15. 可靠性、安全与隐私

- Markdown 写入使用同目录临时文件和原子替换。
- 单 Vault 全局锁阻止并发写入。
- 所有外部 JSON 在写入前整批校验。
- 已有 Signal、Decision、Artifact 默认不覆盖。
- Cookie、Token、OAuth 密钥不进入 Vault。
- 运行清单不复制帖子全文。
- 本地持久化不等于本地推理：使用 Codex、Claude 或 Grok 深拆时，选定内容会发送给相应提供方。
- 默认不发送整个 Self、收藏库或历史库，只发送当前任务所需最小上下文。
- 只读分析和人工确认发布；NextX 不提供自动发帖。

## 16. 开源结构

```text
NextX/
├── src/nextx/          # 标准库 Python CLI
├── skills/nextx/       # canonical Agent Skill
├── prompts/            # Grok 采集与分析契约
├── templates/          # Self/Signal/Decision/Artifact Markdown
├── examples/           # launchd/systemd 调度示例
├── docs/               # 产品、架构、贡献和安全文档
└── tests/              # stdlib unittest
```

建议正式公开时采用 Apache-2.0。任何来自 AGPL 项目的代码不进入本仓库；只独立实现通用产品模式。

## 17. v0.1 纵向验收

一次完整验收必须做到：

1. 初始化 Vault 和 Self 模板。
2. 导入一条手动 Signal、一批 Grok Signal 和一批 Bookmarks。
3. 幂等去重并生成 Today 12 条以内视图。
4. 将一条 Signal 保存为 `do` Decision。
5. 生成 `x-tweet-writer` Brief 并保存一个 draft Artifact。
6. 记录人工发布 URL。
7. 记录 24h Outcome。
8. 生成 Weekly Review 和 Playbook 建议区。
9. 所有数据可在 Obsidian 中阅读、编辑和追溯。
10. 全流程无数据库、无自动发布、无额外模型 API。

## 18. 后续阶段

只有在 v0.1 每周真实使用后再评估：

- 官方 X OAuth Bookmarks 适配器。
- 多账号。
- Obsidian 插件或独立前端。
- 媒体自动下载和视频转写。
- 自动 Outcome 调度。
- MCP Server。
- 团队协作和权限。

这些能力在出现可验证需求前不预留抽象层。
