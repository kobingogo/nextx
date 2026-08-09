# NextX Growth Loop 使用与产品规则

NextX v0.3.0 Alpha 2 面向的是“知道自己想把 X 做起来、但不知道每天先做什么”的运营小白。它不是自动发帖或自动互动工具，而是把每天的运营压成一项可解释、可审计、可复盘的人工行动。

## 一句话规则

> 先完成离结果最近的动作，再开始新的采集；每个 `do` 都必须说明为谁做、希望对方做什么、何时验证。

先在任一已安装 NextX Skill 的 Agent 中说：

> 帮我设置 NextX 的本周增长目标，并告诉我今天的下一步。

Agent 会收集并由你确认以下 Self 信息：账号阶段、单周目标、目标读者、主页承接、CTA、本周聚焦和三条行动线配比。它可以解释推荐，但不能虚构你的定位、读者或 CTA。

## 起号阶段的行动线

| 行动线 | 用户真正要获得的东西 | NextX 的执行模式 |
| --- | --- | --- |
| Discovery | 让相邻读者第一次看见你的新增判断 | Quote / Reply |
| Authority | 让读者知道你能持续解决什么问题 | 原创 post / Thread |
| Conversion | 让已经信任的人采取明确下一步 | 案例 / CTA |

冷启动通常以 Discovery 为主；爬坡提高原创 Thread 比例；稳态才增加 Conversion。这里的比例只是工作量导航，不是发帖配额，也不保证结果。

## 每天只看一个入口

运行或让 Agent 内部运行：

```bash
nextx growth-loop
```

`04. Views/Growth Loop.md` 只给出一个优先动作。排序固定为：

1. 已发布且当前 `1h` / `24h` / `7d` 窗口真正到期、尚未记录 Outcome 的内容；
2. 已写好但未审阅、未确认、未人工发布的内容；
3. 已裁决 `do` 但尚未变成 Artifact 的内容；
4. 按本周 Discovery / Authority / Conversion 行动配比，选择仍在窗口中的 Reply / Quote、待写 `do`、或常规 Signal；
5. 以上都没有时，才建议采集少量新 Signal。

因此，小白不需要在“继续刷 X”和“写一条新帖”之间猜优先级。系统先展示理由，最终裁决与操作仍由人完成。

## 三种分发动作

### Reply Sprint

Reply 用于推进一段具体讨论，不用于刷存在感。

```bash
nextx collector-prompt --source reply
nextx collect --source grok --input-json /path/to/reply-candidates.json
nextx reply-sprint
nextx reply-brief x:123
```

Reply `do` 必须绑定一条已入库原帖、作者和有效窗口，只能保存 `reply-post`。用户在 X 手动回复；NextX 不会自动回复、点赞、关注或继续对话。

### Quote Sprint

Quote 用于让相邻读者看到一个不等于复述的新判断。规则与 Reply 相同，但 Artifact 固定为 `quote-post`，并锁定原帖 URL 与作者。

### 原创 Thread

Thread 用于把一次判断变成可保存、可回看的权威内容。`format=thread` 或 `thread-post` 时，Artifact 必须有：

- 2–25 条按顺序可发布的 `thread_pack.posts`；
- 明确 CTA；
- 可选但结构化的 Asset Manifest：封面/插图角色、用途、生成提示词、alt text、可选本地文件。

Asset Manifest 只是制作交接，不代表图片已经生成或上传。可将它交给 `content-infographic` 等图片 Skill，完成后再填写真实本地路径。

## Growth Contract 与 Outcome

所有 `do` Decision 都必须具有：

```text
增长目标（awareness / authority / conversion）
目标读者
期待动作
分发目标
复盘时间
```

发布后记录三个窗口：

- `1h`：首轮讨论与人工互动是否完成；
- `24h`：早期数据和读者语言；
- `7d`：进入可比周复盘的稳定快照。

每个窗口只能在发布后到期时记录，不能把 7 天后的当前数据伪装成 1 小时快照。更正同一窗口时 NextX 会保留旧机器记录作为修订历史。

带 Growth Contract 的 Artifact 还要记录 `growth_signals.follow_up_completed`。如有条件，可记录非粉丝回复、目标作者回应、主页访问、关注、CTA 行动和观察笔记。它们都是人为观察，**不能表述为帖子造成了这些结果**。

## 学习，而非单帖迷信

Weekly Review 只用 7d 数据生成同类记分卡：

```text
执行模式 × 增长目标
```

例如 `reply × awareness` 只与其他同类 7d Artifact 比较。少于三条样本时，NextX 只允许记录“待验证假设”；达到三条同类样本后，才显示为可人工审查的 Playbook 提案。用户仍必须亲自确认后才能写入 `00. Self/Playbook.md`。

这就是 NextX 的闭环：不是“发更多”，而是每周留下一个有证据支持的 `repeat / alter / stop` 决定。
