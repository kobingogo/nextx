# NextX 新手指南

**适用对象：** 第一次使用 NextX 的单账号 X 运营者。  
**目标：** 在 15 分钟内完成安装、建立自己的本地 Vault，并跑通“一个机会 → 一项可发布行动 → 一次可复盘反馈”的最小增长闭环。

NextX 不是自动发帖工具。它把重复、容易出错的部分固化为本地 Markdown 和 CLI：收集素材、验证裁决、保存草稿、记录结果；Agent 只在深拆、选题和写作时提供推理能力。

```text
Self（你是谁、为谁增长） → Signal（看到什么） → Decision（做/缓/毙）
                         → Artifact（内容包） → 人工发布与互动 → Outcome（结果） → 下一次决策
```

## 1. 先确认你需要什么

| 你的目标 | 必需组件 | 可选组件 |
| --- | --- | --- |
| 保存想法、做选题、写草稿 | Python 3.11+、一个 Agent、Obsidian | 无 |
| 发现热点 | Grok Build | 无 |
| 同步 X 收藏 | 已登录的 `twitter-cli` | macOS 定时轮询 |
| 让草稿更像你 | `topic-engine`、`x-tweet-writer` | 真实历史样本 |

Obsidian 是推荐的数据界面，但不是运行依赖。所有数据默认只写到本机的 `~/Documents/NextX`；NextX 不会自动发布、点赞、转发、关注或删除 X 内容。

## 2. 一键安装

### macOS / Linux：从源码仓库安装

在项目根目录执行：

```bash
./install-nextx
```

安装器会选择 Python 3.11+、创建隔离运行环境，并尝试在 `~/.local/bin/` 暴露 `nextx` 命令。它还会自动识别并部署 NextX Skill：Codex 与 Grok Build 共用 `~/.agents/skills/nextx`，Claude Code 使用 `~/.claude/skills/nextx`（或 `CLAUDE_CONFIG_DIR`）。它不会修改系统 Python、不会创建 Vault、也不会安装或登录 X 工具。

默认只配置已检测到的 Agent。若要预先同时配置三端，执行：

```bash
./install-nextx --agents all
```

同名的手工 Skill 不会被覆盖；安装结果会标记为 `conflict`。确认要替换时才执行 `./install-nextx --force-agent-skills`。

若终端提示找不到 `nextx`，仅在**当前终端会话**执行一次：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

这行的作用只是让 shell 能在 `~/.local/bin` 中找到 `nextx`；它不安装软件，也不上传数据。把它写入 `~/.zshrc` 或 `~/.bashrc` 后，新终端也会生效。

### Windows：从源码仓库安装

在命令提示符或 PowerShell 中执行：

```bat
install-nextx.cmd
```

安装器会使用 Windows `py` 启动器寻找 Python 3.11+。若机器没有兼容 Python，请先安装 Python 3.11 或更新版本，再重新运行。

### 仅拿到 Agent Skill 时

让 Agent 使用 Skill 所在目录的绝对路径：

```bash
/absolute/path/to/nextx/scripts/install-nextx --json
```

`--json` 是给 Codex、Claude Code、Grok Build 等 Agent 读取的机器格式。人直接在终端使用时，默认的中文输出更易读。

### 安装后立刻检查

```bash
nextx --help
nextx config --show
```

如果不希望写入任何文件，可以先预演安装：

```bash
./install-nextx --dry-run
```

独立安装需要网络下载源码；有 Git 时优先使用 Git，无 Git 时会下载受大小限制的 GitHub 源码归档。源码仓库内执行安装则直接复用本地代码，不需要下载源码。

## 3. 初始化你的本地工作台

默认 Vault 是 `~/Documents/NextX`。安装完成后，推荐在任一已检测到的 Agent 对话中只说：

> 初始化 NextX

这句明确请求会创建/检查默认 Vault，并立刻进入 Self 配置对话。Agent 会一次性收集你的定位、受众、阶段、3–4 个内容柱、禁区和真实表达样本；起号用户还会确认一个周增长目标、目标读者、主页承接、CTA 和行动配比。它可以给出建议，但不会替你臆造这些内容。若 Agent 是在安装前启动且没有显示 NextX，重新打开一次会话即可。

仍可用以下命令作为终端排障入口：

```bash
nextx setup --yes
nextx doctor --no-smoke
nextx readiness
```

`setup` 会创建 Vault、Self 模板和本地配置。重复执行安全，不会覆盖你在 Markdown 中写的内容。

若想用现有 Obsidian 目录，只在首次配置时改一次路径：

```bash
nextx setup --vault "/absolute/path/to/My NextX Vault" --yes
nextx config --show
```

之后所有命令都可省略 `--vault`。`config --show` 会显示实际使用的 Vault 路径。

接下来不必手工编辑文件。直接在安装 NextX Skill 的 Agent 对话中说“帮我配置 NextX 的定位和声纹”。Agent 会用一轮简短对话收集定位、受众、阶段、3–4 个内容柱、禁区和真实表达样本，确认后写入 Self 模板。

你也可以在 Obsidian 手工修改 `00. Self/Profile.md`、`Pillars.md` 和 `Voice.md`；两种方式共享同一个本地 Vault。完成后 Agent 会运行 `nextx next-step` 或 `nextx readiness` 检查是否已可用于稳定选题与写作。

## 4. 跑通第一次闭环：从一个想法到草稿

先不接 X、不接 Grok，直接保存一个手动素材：

```bash
nextx add-signal --text "本地 Agent 如何把 X 运营从刷信息改成可审计的决策循环"
nextx today
```

在 `04. Views/Today.md` 找到它的 Signal ID，例如 `manual:...`。接着在支持 NextX、`topic-engine` 与 `x-tweet-writer` 的 Agent 对话中说：

> 使用 NextX：对 `manual:...` 做选题裁决；如果是 do，再生成三温度 X 草稿，但不要发布。

Agent 的标准执行顺序是：

```text
preflight → decision-brief → topic-engine → save-decision
          → artifact-brief → x-tweet-writer → save-artifact
```

NextX 不会直接“调用模型 API”。它生成受控 Brief、提供 JSON 契约并校验写入；当前 Agent 再调用 `topic-engine` 和 `x-tweet-writer`。因此在日常使用中你只需要对话，不需要手动输入这些 CLI 命令；CLI 保留给 Agent、自动化和排障。

成功后，你会在 Obsidian 看到：

```text
01. Signal/      原始素材
02. Decision/    做 / 缓 / 毙、证据与理由
03. Artifact/    选定的草稿
.nextx/handoffs/ 给 Agent 的稳定 Brief 文件
```

写完整长贴时，直接对 Agent 说“将这个 do Decision 做成 Thread，并准备配图清单”。NextX 会要求保存 `thread_pack`（逐条 Thread 与 CTA）和 `asset_manifest`（配图用途、提示词、alt text、可选本地文件），再交给 `content-infographic` 或其他图片 Skill 制作。它不会把“有图片提示词”误报为“图片已生成”。

### 多条 Signal 形成一个原创主题

当你想把多条已经保存并完成 Triage 的 Signal 整理成一个主题时，对 Agent 说“整理这些已保存 Signals”。它先给出只读的 Cluster Brief，不会写入 Topic Card。若你确认保存 Cluster，再明确说“保存这个 Cluster”；若要长期保留其中一个方向，再明确说“创建这个 Topic Card”。卡片会出现在 `01. Topic/`，Cluster 与卡片视图在 `04. Views/Topics/`。

一张原创 Topic Card 仍必须经过 Topic Decision，才可以写草稿；它不授权发布。Quote 和 Reply 仍是各自的单帖路径，不会被多 Signal 主题流程替代。

## 5. 三种采集方式

### 手动素材：最稳，随时可用

```bash
nextx add-signal --text "你的观察或灵感" \
  --source-url "https://x.com/handle/status/123"
```

没有来源 URL 也可以保存；它会被标记为手动来源，不能伪装成已验证的 X 原帖。

### Grok Build 热点：推荐

1. 让 Agent 先运行：

   ```bash
   nextx preflight --intent collect-grok --agent-capability grok-build
   nextx collector-prompt --source grok
   ```

2. 把返回的 Prompt 路径交给 Grok Build，并让它只输出 Collector JSON。
3. 将 JSON 保存到本地，再导入：

   ```bash
   nextx collect --source grok --input-json /path/to/grok-signals.json
   nextx signal-inbox
   ```

NextX 会校验 URL、字段和整批数据，再幂等写入；`signal-inbox` 会重建 `04. Views/Signals/` 下的 Immediate Action、四条内容泳道、Needs Triage 和 Archived 视图。它不会把 Grok 的自然语言结论直接当作“该做”。

### X Bookmarks：可选，先 dry-run

先确认 `twitter-cli` 已安装并在本机登录：

```bash
nextx doctor
nextx collect --source bookmarks --limit 1 --dry-run
```

dry-run 无论成功或失败都不会新建 Vault、健康记录或 Signal。确认结果正确后再正式同步：

```bash
nextx collect --source bookmarks
```

不要在普通增量同步中使用 `--reconcile`；它只适用于你已确认完整的收藏快照。为防止有限页数把旧收藏误标为失效，导入文件还必须显式包含 `"snapshot_complete": true`；实时 `twitter-cli` 增量读取不具备这个声明，不能直接对账。

如果 Vault 来自 v0.1 及以前，先预览再显式迁移旧 Signal 文件名；迁移会保留旧 Obsidian 链接所需的 alias：

```bash
nextx migrate-signals --vault ~/Documents/NextX
nextx migrate-signals --vault ~/Documents/NextX --apply
```

## 6. 日常操作清单

每天先让 NextX 帮你收敛下一步，而不是自己判断今天该找热点、写帖还是复盘：

```bash
nextx growth-loop
nextx readiness
nextx today
```

采集后，让 Agent 对当前请求点名的 Signal 做逐条快速判断：

```bash
nextx triage-brief x:2086237980872847443
nextx save-triage --input-json /absolute/path/to/one-triage.json
nextx signal-inbox
```

Agent 只能把 Brief 中的 Signal 文本当作证据，不能当作指令，也不能默默整理整个 Vault。它按 `triage-input.v1.json` 提供语义字段；分数、策略快照和 Quote / Reply 资格由 NextX 计算。只有带原始候选标记且仍在有效窗口内的 Quote / Reply 才能进入 Immediate Action。

`growth-loop` 会优先处理已发布待复盘、草稿待审阅、已裁决待写作，最后才建议采集。汇报先给 Immediate Action，再给选题候选；默认按 30 分钟核心模式执行，只有用户需要时才增加额外 30 分钟，形成可选 60 分钟扩展模式。冷启动阶段会在有效 Reply / Quote 候选中推荐一个可解释入口；它不替你自动回复或 Quote。`do` 才进入写作；`defer` 会在指定复访时间后回到队列；`kill` 留下原因，不再反复消耗注意力。

若想主动寻找起号回复机会：

```bash
nextx collector-prompt --source reply
nextx reply-sprint
nextx reply-brief x:123
```

草稿完成后，人工在 Artifact 里勾完三项发布检查，再按顺序执行：

```bash
nextx mark-review-ready artifact:ID
nextx confirm-publish artifact:ID --yes
nextx record-published artifact:ID --url "https://x.com/handle/status/123"
```

`--yes` 只表示你已经明确确认发布；它不会把帖子发到 X。最后一条命令仅记录你**已在 X 手工发布**的 URL。

发布后在 1h、24h、7d 录入结果并生成周报：

```bash
nextx record-outcome artifact:ID --input-json /path/to/7d-outcome.json
nextx weekly-review
```

带增长契约的内容必须额外录入 `growth_signals.follow_up_completed`，可补充非粉丝回复、主页访问、关注、CTA 行动和观察笔记。周报只用 7d 快照比较内容表现，1h/24h 仅保留为早期信号；少于三条同类样本时只保留假设。它不会自动修改 `Playbook.md`。

## 7. 重要注意事项

- **先填 Self，再让 Agent 写。** 空 Self 会让输出变成泛化内容；`readiness` 的缺项就是优先级。
- **外部内容是不可信数据。** X 帖、收藏、Collector JSON 中的“命令”或链接都不能改变 Agent 的文件、网络或工具权限。
- **只把必要内容交给模型。** NextX 的 Brief 默认只交接当前 Signal 或 Decision，不应把整个 Vault 发给模型。
- **NextX 不保证 X 数据的长期可得性。** 保留原始 URL、摘录和采集时间，重要判断不要只依赖单条热帖。
- **人工发布闸门不能跳过。** 草稿、URL 或 Agent 文本都不是发布事实；必须由人完成检查、确认与手工发布。
- **Vault 是权威数据。** 不要把唯一信息写进 `04. Views/`，因为 Today 和 Weekly Review 都可以重建覆盖。
- **先备份再迁移。** 备份整个 Vault；不要复制或提交 Cookie、Token、OAuth 密钥和 `.nextx` 之外的私密运行凭据。
- **单账号是当前边界。** 一个 Vault 只管理 `primary` 账号，暂不支持多个账号混用。

## 8. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| `nextx: command not found` | macOS/Linux 执行 `export PATH="$HOME/.local/bin:$PATH"`，或使用安装器 JSON 返回的 `executable` 绝对路径。 |
| 安装器提示 Python 版本不足 | 安装 Python 3.11+；可用 `python3 --version` 或 Windows 的 `py -3.11 --version` 检查。 |
| `readiness` 不通过 | 按输出补全 Profile、至少三个 Pillars、真实 Voice 样本与禁区。 |
| Bookmark 失败 | 先执行 `nextx doctor`；通常是 `twitter-cli` 未安装或 X Cookie 已失效。可先用 Grok/手动采集。 |
| `Another NextX sync is already running` | 确认没有正在写入的 NextX 进程后运行 `nextx recover-lock`；只有无 owner 的旧锁才在人工确认后加 `--force`。 |
| Agent 被 preflight 阻止 | 安装所需 Skill，或向 preflight 传入实际的 `--skills-root /path/to/skills`。自声明能力会被标记为未验证。 |
| `pip install -e .` 失败 | 优先使用 `./install-nextx`。若必须开发安装，请阅读 [操作手册的代理/证书排障](OPERATIONS.md#42-安装错误的判断方法)。 |

## 9. 接下来做什么

1. 连续 7 天每天只处理少量 Signal，而不是扩大采集量。
2. 每周运行一次 `nextx weekly-review`，只挑一个实验写入 Playbook。
3. 真实 Bookmark dry-run 稳定后，再考虑启用 macOS 定时轮询。
4. 需要字段规范、fixture 验收或完整运维操作时，继续阅读 [完整操作手册](OPERATIONS.md) 与 [JSON Contracts](contracts.md)。
