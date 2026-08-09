# Quote Sprint：起号阶段的高质量引用工作流

Quote Sprint 的目的不是增加“蹭热点”频率，而是在一个已有讨论中提供足够独立、可核验的判断，让相邻读者有理由点进你的主页。它是 NextX 的 `quote` 执行模式，不是新的数据对象：原帖仍是 Signal，取舍仍是 Decision，草稿仍是 Artifact。

## 什么时候用

- 账号仍在冷启动或爬坡期，需要让正确的相邻读者第一次看见你的判断。
- 有一条仍在讨论窗口内的原帖，且你能补上实施细节、反例、翻译、建设性分歧或高质量问题。
- 你的结论能被已入库原帖的事实边界支撑。

不要用于“同意”“说得好”、换词复述、拿争议帖博曝光、或原帖已过讨论窗口。那类内容应当是 `kill`，或重新采集到有新事实的 Signal。

## 对话优先的日常用法

在 Codex、Claude Code 或 Grok Build 新会话直接说：

> 启动 NextX 的 Quote Sprint，帮我找今天值得高质量 Quote 的原帖。

NextX Skill 会先检查本地能力，再读取运行时内的 Quote Collector Prompt。Grok Build 是首选发现器；已经由用户授权并能只读访问 X 的 `twitter-cli` / agent-reach 可以作为替代发现后端。采集器只能返回 JSON，不直接改 Vault；NextX 校验后才写入。

高级排障或自动化时，可显式运行：

```bash
nextx preflight --intent collect-quote --agent-capability grok-build
nextx collector-prompt --source quote
nextx collect --source grok --input-json /absolute/path/quote-candidates.json
nextx quote-sprint
```

`Quote Sprint.md` 位于 `04. Views/`，可随时重建，不能存放唯一笔记。它最多显示三条、每名原作者最多一条，避免把当天变成同一圈层的刷屏。

## Collector 必须保留的证据

每条候选都使用普通 `collector-envelope.v1`，并额外要求：

- `quote_candidate: true`
- 规范 X 状态 URL、`author_handle`、`published_at` 与实际可见的 `text`
- 采集时不超过 72 小时的 `published_at`，以及晚于采集、最长 48 小时的 `quote_window_ends_at`
- `source_confidence`、`discovery_reason`、`why_today`、`self_fit`、`novelty`

缺少任一原帖身份或窗口信息时，NextX 整批拒绝，不把它悄悄降级成可 Quote 的素材。候选只是排序输入；不表示值得发布。

## 决策和草稿

选中候选后说“裁决这个 Quote”，或者执行：

```bash
nextx quote-brief x:123456789
```

`topic-engine` 需要给出普通 `do / defer / kill` 字段及逐字证据。若是 `do`，还必须给出：

```json
{
  "execution_mode": "quote",
  "recommended_format": "quote-post",
  "quote_angle_type": "implementation",
  "relationship_goal": "reader_discovery",
  "quote_window_ends_at": "2026-08-09T08:00:00+00:00"
}
```

`quote_angle_type` 只能是 `extend`、`constructive_disagree`、`translate`、`implementation` 或 `question`；`relationship_goal` 只能是 `reader_discovery`、`author_dialogue` 或 `credibility`。`defer` 的复访时间必须仍在窗口内，过期后使用 `kill`；`quote` Decision 一次只能关联一条 Signal。

之后运行 `artifact-brief`。NextX 会把原帖 URL、作者和截止时间从 Decision 关联的 Signal 派生到 Artifact，并强制 `format=quote-post`。`x-tweet-writer` 在 QT 模式给出三温度版本，但不得把原帖复述成普通单帖。用户选择一版后保存草稿，仍需在 X 手动选择原帖并发布；原有检查清单、明确确认与 URL 回填都不变。

## 质量闸门

发布前用四个问题淘汰弱 Quote：

1. 第一行是否给出自己的可验证增量，而不是认同或改写？
2. 这个增量是否对目标读者有用，而不只是对原作者礼貌？
3. 原帖事实、来源和归因能否仍从 Signal 复核？
4. 现在公开站队是否值得；否则为什么不是 `defer` 或 `kill`？

## 复盘，不伪造因果

普通 1h/24h/7d `views`、`likes`、`replies`、`reposts`、`bookmarks` 的口径不变。Quote Artifact 可以在 Outcome 中可选记录人工观察：`target_author_replied`、`target_community_replies`、`profile_visits`、`new_followers`。带 Growth Contract 的 Artifact 还必须记录 `growth_signals.follow_up_completed`。这些字段只允许作为人工观察；周报会单列 Quote Sprint 数量和目标作者回复，并明确标记为观察，不能声称是 Quote 的唯一因果结果。

真实验证建议持续一周：每天只做 1–3 条高质量 Quote，并与原创帖分别观察 7d 互动命中率、决策到草稿时延、以及可复核的关系信号。再从多个样本中人工批准一条 Playbook 规则，而不是用单条爆款固化策略。
