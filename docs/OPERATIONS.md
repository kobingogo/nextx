# NextX 安装与完整操作手册

**适用版本：** v0.2「Growth Loop」  
**验证日期：** 2026-08-08  
**运行形态：** 单一 X 账号、本地 CLI + Obsidian + Agent 对话

这份手册同时回答三个问题：当前代码到底实现了什么、怎样安装、怎样从初始化一路验收到完整运营闭环。

首次使用请先阅读 [新手指南](GETTING_STARTED.md)；本文保留完整验收、运维与排障细节。

## 1. 先理解产品边界

NextX 不是独立 Web 前端。它由三层组成：

| 层 | 实现 | 作用 |
| --- | --- | --- |
| 操作入口 | Codex CLI、Claude Code、Grok Build 或直接终端 | 理解自然语言、调用 Agent Skill、展示结果 |
| 确定性内核 | `nextx` Python CLI | 校验 JSON、幂等去重、状态转换、原子写入、生成 Brief 和 Views |
| 用户数据界面 | Obsidian Vault | 编辑 Self、查看 Signal/Decision/Artifact、审计历史 |

持久化只有四个原语：

```text
Self → Signal → Decision(do/defer/kill) → Artifact(draft/review_ready/publish_confirmed/published/measured)
```

Outcome 嵌在 Artifact 内，Learn 是 Weekly Review 过程，不会创建第五种核心对象。NextX 永远不自动发帖、点赞、转发、关注或删除 X 内容。

## 2. 代码实现盘点

### 已实现能力

| 能力 | 关键代码 | 当前实现程度 |
| --- | --- | --- |
| CLI 与安装 | `pyproject.toml`、`src/nextx/cli.py`、`skills/nextx/scripts/bootstrap.py` | 一键创建用户级 Python 3.11+ 环境；独立 Skill 按仓库/ref 隔离源码，优先 Git、无 Git 时可安全下载 GitHub 归档；所有成功/失败输出结构化 JSON |
| Vault 与 Self | `vault.py`、`records.py`、`self_model.py`、`accounts.py` | 初始化六个 Self 模板、对话式 `configure-self`、Growth Strategy 与 `next-step` 就绪引导；单 Vault 只允许 primary；Markdown frontmatter 是权威数据；原子写入和单 Vault 写锁 |
| Signal 采集 | `signals.py`、`schemas/collector-envelope.v1.json` | Grok 文件导入、任意契约采集器导入、手动文本；整批校验、URL/ID/hash 去重 |
| X Bookmarks | `bookmarks.py`、`twitter_cli.py` | 读取 `twitter bookmarks --json`，初次最多 200、增量默认 50、dry-run、健康状态、幂等入库；完整快照可显式对账 |
| Grok 热点 | `prompts/grok-collector.md` | Grok Build 输出 Envelope JSON，再由 `nextx collect --source grok` 导入 |
| Today | `views.py` | 10 条自动候选 + 2 条手动位置；按 Self 匹配、原创增量、证据、时效解释性排序，近重复去重，defer 到期复访；生成 Bookmark Inbox |
| 深度拆解 | `analysis.py` | 只读取一个选定 Signal，生成并持久化事实/原帖观点/推断、结构、钩子、传播机制等分析 |
| 选题裁决 | `decisions.py` | `do/defer/kill` 三态；`do` 必须有角度、原创增量、风险和可回溯的逐字证据；生成 topic-engine Brief |
| 草稿与发布 | `artifacts.py` | 仅 `do` 可生成 x-tweet-writer Brief；保存定稿；三项检查清单 + 显式确认后才可回填人工发布的 X URL |
| Outcome 与周复盘 | `learning.py` | 手动录入 1h/24h/7d 指标与人工增长观察；同窗口替换；7d 后 measured；按执行模式 × 增长目标生成记分卡，并以三条同类样本作为 Playbook 提案门槛 |
| Agent Skill | `skills/nextx/SKILL.md` | 一份 canonical Skill 路由所有意图；topic-engine 和 x-tweet-writer 仍由外部 Skill 负责 |
| 性能与可靠性 | `views.py`、`vault.py` | 可重建 `.nextx/index.json`；10,000 条 Signal 增量 Today 实测约 109ms |
| 调度模板 | `examples/com.nextx.bookmarks.plist` | macOS launchd 每 180 秒轮询；需要替换绝对路径和完成账号认证 |

### 目前不是“完全自动化”的部分

1. **Grok 不是 NextX 内置 SDK。** 先让 Grok Build 按 Prompt 输出 JSON，再导入；这样采集器可替换，避免绑定私有接口。
2. **深拆先交接、后显式保存。** `analysis-brief` 把单条 Signal 交给当前 Agent 分析；用 `save-analysis` 校验 JSON 后写回机器托管的深拆区，原始帖和用户笔记不被改写。
3. **Bookmarks 是在线准实时轮询。** X 没有公开 Bookmark webhook，launchd 在线时每 180 秒调用一次；休眠期间暂停。
4. **Outcome 是手动回填。** 代码验证 1h/24h/7d 格式、非负指标和 Growth Loop 的人工反馈字段，但不会凭空读取 X 指标，也不将观察表述为因果。
5. **真实 Bookmark 当前有环境阻塞。** 如果 twitter-cli Cookie 提取失败，fixture 测试仍可通过，但真实 smoke/dry-run 不能算完成。
6. **`twitter-cli` 是可选能力。** `doctor --no-smoke` 在没有 `twitter` 二进制时仍可通过；只有真实 smoke 检查才要求 Bookmark 能力完整。

当前任务状态以 [docs/TASKS.md](TASKS.md) 为准。

## 3. 安装前准备

### 必需

- macOS 或其他能运行 Python 3.11+ 的本机环境。
- Python 3.11+。
- 一个可写的 Obsidian Vault 路径；Obsidian 本身不是 Python 运行依赖，但推荐用它浏览和编辑。

### 可选

- `twitter-cli` 0.8.5+：读取 X Bookmarks；需要已认证的 X Cookie。
- Grok Build：首选开放式热点发现器。
- `topic-engine`：选题判断。
- `x-tweet-writer`：三温度推文写作。
- Codex、Claude Code 或 Grok Build：运行同一份 canonical Agent Skill。

## 4. 推荐安装方式：一键安装

在仓库根目录执行统一入口：

```bash
./install-nextx
```

Codex、Claude Code、Grok Build 都调用这一个入口，不维护各自的工作流文案。安装器会自动识别 Agent：Codex 与 Grok Build 共享 `~/.agents/skills/nextx`，Claude Code 使用 `~/.claude/skills/nextx`（或 `CLAUDE_CONFIG_DIR`）。若只拿到了 Skill 目录，先解析 `SKILL.md` 所在的绝对目录，再使用其自带入口：

```bash
/absolute/path/to/nextx/scripts/install-nextx --json
```

终端用户默认得到中文下一步提示；Agent 必须使用 JSON 模式：

```bash
./install-nextx --json
```

安装器会：

1. 选择当前可用的 Python 3.11+；
2. 在 `~/.local/share/nextx/venv` 创建用户级隔离环境；
3. 源码仓库创建指向 `src/` 的隔离 launcher（无需网络）；独立 Skill 会把按 `repository + ref` 隔离的源码缓存写入 runtime 同级 `sources/`，优先 Git clone；若未安装 Git 且目标是 GitHub HTTPS 仓库，则安全下载受 50 MiB 限制的源码归档后创建 launcher，不复用 PATH 中的同名程序；
4. 在用户级 `~/.local/bin` 暴露 `nextx` 入口，并同时输出 runtime 的 `executable` 路径。
5. 将完整 canonical Skill 安装到已检测到的 Agent 根目录；JSON 中的 `agent_skills` 给出每端的检测、路径与冲突状态。

安装器不写系统 Python、不写 Vault、不安装或认证 `twitter-cli`。默认 `--agents auto` 只写入检测到的 Agent；在尚未启动/安装目标 Agent 的机器上，可以显式使用 `--agents all`。若发现手工维护的同名 Skill，安装器返回 `conflict` 而不覆盖；只有明确指定 `--force-agent-skills` 才会替换。独立安装在 JSON 中记录 `repository`、`ref`、`source_transport`；通过 Git 下载时还记录 `source_revision`。默认 ref 是当前发行 tag `v0.3.0-alpha.2`，追求其他版本时应显式传入已审阅的 tag 或 branch。

若当前 shell 尚未把用户级 bin 目录加入 PATH，执行一次：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Agent 不依赖 PATH：读取 JSON 的 `nextx` 字段；当 `command_exposed` 为 false 时回退到 `executable`。

对 Agent 工作流先运行只读预检；它不会初始化 Vault 或改变收藏状态。按需声明当前 Agent 能力，或用 `--skills-root` 验证实际的 Skill 目录：

```bash
nextx preflight --intent collect-grok --agent-capability grok-build
nextx preflight --intent decision --agent-capability topic-engine
nextx preflight --intent draft --agent-capability x-tweet-writer
nextx contracts
```

`nextx contracts --name NAME` 和 `nextx collector-prompt --source grok` 返回当前运行时内的绝对路径，因此已安装的 Skill 不需要猜测仓库或当前工作目录。

可先检查而不写入：

```bash
./install-nextx --dry-run
```

### 4.0.1 对话初始化验收

安装器报告对应 Agent 的 Skill 为 `installed`、`updated` 或 `unchanged` 后，在该 Agent 的新会话中只发送：

> 初始化 NextX

Skill 会将此视为对默认 Vault 初始化的明确授权，执行 `next-step → setup（如有需要）→ next-step`，然后收集不可替代的 Self 信息。定位、禁区和声纹必须由用户提供，不能由 Agent 自动补全。已打开但未显示新 Skill 的会话应重启；Grok Build 可用 `grok inspect --json` 查看发现结果。

### 4.1 手动开发安装（备用）

#### 使用 Homebrew Python（macOS 推荐）

```bash
cd /Users/bingo/workspace/NextX

/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install -e . --quiet
.venv/bin/nextx --help
```

安装成功后，后续命令统一使用：

```bash
export NEXTX_ROOT="/Users/bingo/workspace/NextX"
export NEXTX_PYTHON="$NEXTX_ROOT/.venv/bin/python"
export NEXTX="$NEXTX_ROOT/.venv/bin/nextx"
```

如果没有 Homebrew Python：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e .
```

`pyproject.toml` 要求 `setuptools>=68`。如果使用公司代理，遇到证书问题应配置：

```bash
export PIP_CERT="/absolute/path/to/company-ca.pem"
```

不要长期使用关闭 TLS 校验的参数。默认安装会使用项目声明的隔离构建依赖。

### 4.2 安装错误的判断方法

如果错误出现在 `Installing build dependencies`，并同时出现：

```text
AttributeError: 'NoneType' object has no attribute 'get'
```

通常是旧 pip 通过代理解析 PyPI 证书失败，不是 NextX 代码错误。检查：

```bash
python -V
python -m pip --version
python -c "import setuptools; print(setuptools.__version__)"
```

至少应满足 Python 3.11 和 setuptools 68。旧 pyenv Python 3.11.0 + pip 22.3 + setuptools 65.5 不满足本项目的构建隔离条件。

## 5. 初始化 Vault 与 Self

默认 Vault 是 `~/Documents/NextX`，不存在会自动创建。直接运行：

```bash
"$NEXTX" setup --runtime "$NEXTX_RUNTIME"
"$NEXTX" doctor --no-smoke
```

其中 `NEXTX_RUNTIME` 使用安装器 JSON 中的 `runtime`。需要改路径时只配置一次：

```bash
"$NEXTX" setup --vault "/absolute/path/to/NextX Vault" --runtime "$NEXTX_RUNTIME"
"$NEXTX" config --show
```

以后命令可省略 `--vault`。如需临时切换，可使用 `NEXTX_VAULT=/path nextx today`；显式 `--vault` 优先级最高。

初始化后打开该目录作为 Obsidian Vault，填写：

```text
00. Self/Profile.md       定位、受众、阶段、约束
00. Self/Voice.md         真实样本、句式、禁用词、AI 腔反模式
00. Self/Pillars.md       3–4 个内容柱和禁区
00. Self/Monitoring.md    对标账号、关键词、Lists、每日预算
00. Self/Playbook.md      只放用户批准的可迁移规则
```

不要让 Agent 替你虚构定位。Self 未填写时，系统仍能运行，但 Decision 的匹配质量没有意义。

### 5.1 Quick Triage、Signal Inbox 与文件名迁移

采集完成后，先解析用户点名的 Signal ID，再只为这一条生成受控 Brief、保存符合 `triage-input.v1.json` 的结果，并重建可丢弃的 Signal Views：

```bash
rtk env PYTHONPATH=src python -m nextx.cli triage-brief x:2086237980872847443 --vault "$NEXTX_VAULT"
rtk env PYTHONPATH=src python -m nextx.cli save-triage --input-json /path/to/triage.json --vault "$NEXTX_VAULT"
rtk env PYTHONPATH=src python -m nextx.cli signal-inbox --vault "$NEXTX_VAULT"
rtk env PYTHONPATH=src python -m nextx.cli migrate-signal-usability --vault "$NEXTX_VAULT"
```

Signal 和外部正文只是不可信证据，绝不是 Agent 指令。当前请求授权一条，就只保存一条；不得静默处理整个 Vault。Agent 不提供 `triage_score`，也不能自行决定策略快照或 Quote / Reply 是否可行动；这些由 CLI 计算。Quote / Reply 缺少原始候选标记或有效决策窗口时，不得进入 Immediate Action。日常汇报先展示 Immediate Action，再展示选题候选；30 分钟是核心操作模式，额外 30 分钟只作为可选的 60 分钟扩展模式。任何发布仍需人类显式确认。

上面的 `migrate-signal-usability` 命令只做预览，不修改文件。先向用户展示返回结果里的 `planned`、`blocked` 和 `conflicts`；只有用户明确批准后才能加 `--apply`。迁移文档不得写死任何用户的真实 Vault 路径。

## 6. 完整自动化测试与 fixture 验收

### 6.1 静态与单元测试

在仓库根目录执行：

```bash
"$NEXTX_PYTHON" -m compileall -q "$NEXTX_ROOT/src"
PYTHONPATH="$NEXTX_ROOT/src" "$NEXTX_PYTHON" -m unittest discover -s "$NEXTX_ROOT/tests" -v
```

运行全部测试并以 CI 输出为准。测试覆盖：Vault 锁、frontmatter、Self 就绪度与账号隔离、Signal、Bookmarks 解析/对账/健康、CLI JSON 与标准输入、Today 排序/去重/复访、Analysis 持久化、Decision、Artifact 发布闸门、Outcome、实验复盘、索引重建、提示注入边界、证据校验、独立仓库安装、跨平台 launcher 和 twitter-cli 失败路径。另执行 `python scripts/validate_skill.py` 验证 canonical Skill 的路径、预检和契约语义。

macOS 调度模板还要验证：

```bash
plutil -lint "$NEXTX_ROOT/examples/com.nextx.bookmarks.plist"
```

### 6.2 临时 Vault 纵向流程

以下流程不触碰真实 Vault，也不读取 X：

```bash
TEST_VAULT="$(mktemp -d /tmp/nextx-e2e.XXXXXX)"

"$NEXTX" init --vault "$TEST_VAULT"
"$NEXTX" collect --vault "$TEST_VAULT" --source grok \
  --input-json "$NEXTX_ROOT/tests/fixtures/grok-signals.json"
"$NEXTX" collect --vault "$TEST_VAULT" --source bookmarks \
  --input-json "$NEXTX_ROOT/tests/fixtures/bookmarks.json"
"$NEXTX" add-signal --vault "$TEST_VAULT" \
  --text "A manual integration idea"
"$NEXTX" today --vault "$TEST_VAULT"
"$NEXTX" analysis-brief --vault "$TEST_VAULT" x:3001 \
  > "$TEST_VAULT/analysis-brief.json"
```

检查结果：

```bash
sed -n '1,80p' "$TEST_VAULT/04. Views/Today.md"
sed -n '1,80p' "$TEST_VAULT/04. Views/Bookmark Inbox.md"
```

随后保存 fixture Decision：

```bash
DECISION_JSON="$TEST_VAULT/decision-result.json"
"$NEXTX" save-decision --vault "$TEST_VAULT" \
  --input-json "$NEXTX_ROOT/tests/fixtures/decision-do.json" \
  > "$DECISION_JSON"
DECISION_ID="$("$NEXTX_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$DECISION_JSON")"
```

创建 Artifact 输入文件：

```bash
cat > "$TEST_VAULT/artifact.json" <<JSON
{
  "schema_version": 1,
  "account_key": "primary",
  "decision_id": "$DECISION_ID",
  "format": "single-post",
  "draft": "NextX turns noisy signals into an auditable decision loop."
}
JSON

ARTIFACT_JSON="$TEST_VAULT/artifact-result.json"
"$NEXTX" save-artifact --vault "$TEST_VAULT" \
  --input-json "$TEST_VAULT/artifact.json" > "$ARTIFACT_JSON"
ARTIFACT_ID="$("$NEXTX_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$ARTIFACT_JSON")"
```

模拟人工发布、确认和 7d 回写：

```bash
sed -i '' 's/- \[ \]/- [x]/g' "$TEST_VAULT/03. Artifact/"*.md
"$NEXTX" mark-review-ready --vault "$TEST_VAULT" "$ARTIFACT_ID"
"$NEXTX" confirm-publish --vault "$TEST_VAULT" "$ARTIFACT_ID" --yes
"$NEXTX" record-published --vault "$TEST_VAULT" "$ARTIFACT_ID" \
  --url "https://x.com/example/status/9001"

cat > "$TEST_VAULT/outcome.json" <<'JSON'
{
  "schema_version": 1,
  "account_key": "primary",
  "window": "7d",
  "views": 1200,
  "likes": 48,
  "replies": 9,
  "reposts": 12,
  "bookmarks": 21,
  "growth_signals": {
    "follow_up_completed": true,
    "non_follower_replies": 2,
    "observations": ["A reader asked for the decision template."]
  }
}
JSON

"$NEXTX" record-outcome --vault "$TEST_VAULT" "$ARTIFACT_ID" \
  --input-json "$TEST_VAULT/outcome.json"
"$NEXTX" weekly-review --vault "$TEST_VAULT"
sed -n '1,160p' "$TEST_VAULT/04. Views/Weekly Review.md"
```

预期：Artifact 状态为 `measured`，Weekly Review 显示 `做：1`、一个 measured Artifact、草稿时延和同类记分卡；单一样本只保留待验证假设。整个流程不会发布到 X。

## 7. 真实账号首次验收

### 7.1 检查本地能力

```bash
"$NEXTX" doctor --vault "$NEXTX_VAULT" --no-smoke
```

`--no-smoke` 只检查 Python、Vault 可写性和 `twitter` 二进制，不读取 X。要把真实 Bookmark 能力标记为可用，执行：

```bash
"$NEXTX" doctor --vault "$NEXTX_VAULT"
```

预期 `bookmark_smoke: ready`。如果出现 `Twitter cookie extraction failed`，先重新认证 twitter-cli；在认证恢复前，不要把 Bookmark 轮询配置加载到 launchd。

### 7.2 真实 Bookmark dry-run

```bash
"$NEXTX" collect --vault "$NEXTX_VAULT" --source bookmarks \
  --limit 1 --dry-run
```

预期：返回 `ok: true`、`dry_run: true`，Vault 中不应新增 Signal。即使 Collector 读取失败，dry-run 也不会创建 Vault 或写入 Bookmark 健康记录。确认无误后再正式同步：

```bash
"$NEXTX" collect --vault "$NEXTX_VAULT" --source bookmarks
```

首轮默认最多读取 200 条，后续根据 `.nextx/bookmarks-state.json` 默认读取 50 条。相同 Tweet ID 会返回 duplicate，不覆盖用户编辑。

若导入的是确认完整的收藏快照，可再加 `--reconcile`；输入 JSON 必须同时含有 `"snapshot_complete": true`，否则 NextX 会拒绝执行。NextX 仅把缺失项目标为 `bookmark_active: false`，不删除原始 Markdown 或人工笔记。普通增量同步绝不能使用该参数。`nextx doctor` 会显示最近 Bookmark 同步的本地健康状态。

### 7.3 Grok 热点采集

从源码运行时可把 [Grok Collector Prompt](../prompts/grok-collector.md) 提供给 Grok Build；已安装的 Skill 则运行 `nextx collector-prompt --source grok` 并读取返回路径。先用 `nextx contracts --name collector` 检查 JSON 契约，再导入：

```bash
"$NEXTX" collect --vault "$NEXTX_VAULT" --source grok \
  --input-json /absolute/path/to/grok-signals.json
```

没有可验证原帖 URL/ID 的结论不能单独支撑 `do` Decision。

## 8. 每日运营流程

### 第一步：生成裁决队列

```bash
"$NEXTX" today --vault "$NEXTX_VAULT"
```

在 Obsidian 查看：

```text
04. Views/Today.md
04. Views/Bookmark Inbox.md
```

Today 只保留最多 10 条自动候选和 2 条手动候选；自动候选按 Self 匹配、原创增量、证据质量、时效和有限动量排序，并显示“为什么是今天”。同内容近重复和同作者过量内容会被压掉。`defer` 在 `revisit_at` 到期之前不会出现，届时带“复访已到期”重新出现。

### 第二步：单帖深拆

对选中的 ID 执行：

```bash
"$NEXTX" analysis-brief --vault "$NEXTX_VAULT" x:123456789
```

把输出交给 Agent，要求只分析该 Signal，并分离：事实、原帖观点、推断、内容结构、钩子、传播机制、可迁移方法、风险与反证。Brief 会保存到 `.nextx/handoffs/analysis-<id>.md`；将 Agent JSON 用下列方式显式写回，再作为 Decision 判断材料：

```bash
"$NEXTX" save-analysis --vault "$NEXTX_VAULT" --input-json /absolute/path/to/analysis.json
# 或让 Agent 直接通过标准输入交接：... | "$NEXTX" save-analysis --vault "$NEXTX_VAULT" --input-json -
```

### 第三步：做 / 缓 / 毙

```bash
"$NEXTX" decision-brief --vault "$NEXTX_VAULT" x:123456789
```

把 Brief 交给 `topic-engine`。Agent 返回 Decision JSON 后保存：

```bash
"$NEXTX" save-decision --vault "$NEXTX_VAULT" \
  --input-json /absolute/path/to/decision.json
```

`do` 必须提供证据、角度、原创增量、风险和理由；可选 `experiment: {id, hypothesis, metric: "engagement_rate"}` 用于后续归因。`defer` 必须提供理由码、理由、带时区的未来 `revisit_at` 与 `revisit_reason`；`kill` 只需要理由码和理由。保存后检查：

```text
02. Decision/<decision-id>.md
04. Views/Decision Board.md
```

### 第四步：生成草稿

只对 `do` Decision 执行：

```bash
"$NEXTX" artifact-brief --vault "$NEXTX_VAULT" decision:YYYYMMDDTHHMMSS-XXXXXXXX
```

把 Brief 交给 `x-tweet-writer`，让 Agent 生成三温度版本并完成 validation。用户选择最终版本后，保存一个 Artifact JSON：

```json
{
  "schema_version": 1,
  "account_key": "primary",
  "decision_id": "decision:...",
  "format": "single-post",
  "draft": "只保存用户选择的最终版本"
}
```

```bash
"$NEXTX" save-artifact --vault "$NEXTX_VAULT" \
  --input-json /absolute/path/to/artifact.json
```

### 第五步：人工发布并回填

NextX 不打开发布权限。先在 Obsidian 勾选 Artifact 的三个发布检查项；再让 CLI 记录 review 与用户的显式确认。用户在 X 完成人工发布后，才回填 URL：

```bash
"$NEXTX" mark-review-ready --vault "$NEXTX_VAULT" artifact:...
"$NEXTX" confirm-publish --vault "$NEXTX_VAULT" artifact:... --yes
"$NEXTX" record-published --vault "$NEXTX_VAULT" artifact:... \
  --url "https://x.com/handle/status/123456789"
```

### 第六步：结果回写

在 1h、24h 或 7d 后准备指标 JSON：

```json
{
  "schema_version": 1,
  "account_key": "primary",
  "window": "24h",
  "views": 12000,
  "likes": 180,
  "replies": 32,
  "reposts": 20,
  "bookmarks": 90
}
```

```bash
"$NEXTX" record-outcome --vault "$NEXTX_VAULT" artifact:... \
  --input-json /absolute/path/to/outcome.json
```

7d 回写会把 Artifact 状态变成 `measured`。同一窗口再次回写会替换旧快照，不会产生重复记录；周报只比较 7d 快照，1h/24h 仅作为早期信号保留。

## 9. 每周复盘

```bash
"$NEXTX" weekly-review --vault "$NEXTX_VAULT"
```

在 Obsidian 查看 `04. Views/Weekly Review.md`，重点检查：

- 做/缓/毙数量。
- Decision 到 Artifact 的转化。
- 草稿时延中位数。
- Top/Bottom measured Artifact。
- 最多五个学习提案。
- 下周唯一实验。

Weekly Review 不自动写入 `00. Self/Playbook.md`。只有用户明确批准一个规则后，才手工写入 Playbook。

## 10. macOS 收藏轮询

先确保真实 dry-run 成功，再复制模板：

```bash
cp "$NEXTX_ROOT/examples/com.nextx.bookmarks.plist" \
  "$HOME/Library/LaunchAgents/com.nextx.bookmarks.plist"
```

替换：

```text
__NEXTX_EXECUTABLE__ → .venv/bin/nextx 的绝对路径
__VAULT_PATH__       → NEXTX_VAULT 的绝对路径
__LOG_DIR__          → 已存在的日志目录
```

验证并加载：

```bash
plutil -lint "$HOME/Library/LaunchAgents/com.nextx.bookmarks.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.nextx.bookmarks.plist"
```

检查任务：

```bash
launchctl print "gui/$(id -u)/com.nextx.bookmarks"
```

停止任务：

```bash
launchctl bootout "gui/$(id -u)/com.nextx.bookmarks"
```

## 11. Vault 结构与数据维护

```text
00. Self/       用户定位、声纹、内容柱、监控、Playbook
01. Signal/     Grok、Bookmarks、手动素材的归一化记录
02. Decision/   做 / 缓 / 毙及证据和理由
03. Artifact/  草稿、发布 URL、Outcome
04. Views/      Growth Loop、Today、Quote Sprint、Reply Sprint、Bookmark Inbox、Decision Board、Weekly Review
.nextx/         config、state、运行清单、写锁、可重建 index
```

- Markdown 记录是权威源；`.nextx/index.json` 损坏或删除后可以从 Markdown 重建。
- `04. Views/` 会被覆盖重建，不要在 View 中保存唯一信息。
- 记录按类型存放，不要通过手工移动文件改变状态。
- 不要把 Cookie、Token、OAuth 密钥写入 Vault。
- 备份 Vault 时优先备份整个 Vault；运行中的 `sync.lock` 不代表数据本身。

## 12. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| pip 在 build dependencies 阶段报 `cert.get` | 旧 pip/代理证书环境 | 使用上面的 Homebrew Python venv；或配置 `PIP_CERT` |
| `python` 版本低于 3.11 | 不满足项目元数据 | 使用 Python 3.11+ 的 venv |
| `twitter_binary: missing` | 找不到 `twitter` 命令 | 安装 twitter-cli，并确认 `which twitter` 能找到 |
| `Twitter cookie extraction failed` | X 登录 Cookie 不可用 | 重新认证 twitter-cli；暂用 Grok/手动导入 |
| `Another NextX sync is already running` | Vault 写锁存在 | 先确认没有同步进程，再运行 `nextx recover-lock`；仅对无 owner 旧锁人工确认后使用 `--force` |
| Collector 被拒绝 | schema、account_key、source_id/URL 或字段缺失 | 对照 Collector Schema 修正后整批重试 |
| `Signal not found` | ID 不存在或格式不对 | 使用 `x:数字` 或从 Today 卡片复制 ID |
| `Only a do Decision can create an Artifact` | Decision 是 defer/kill | 先建立新的 do Decision，不能绕过闸门 |
| View 内容过期 | Projection 尚未重建 | 重新执行 `today` 或 `weekly-review` |
| launchd 不启动 | plist 占位符、路径或权限错误 | 先 `plutil -lint`，再检查 `launchctl print` 和日志 |

所有 CLI 失败都应返回非零退出码，并把 JSON 错误写到 stderr；不要把 stderr 当作成功结果继续交给 Agent。

## 13. 完成判定

可以把本机 v0.2 视为“代码完成、真实运营待验证”，必须同时满足：

1. `nextx --help` 正常。
2. `nextx init` 能创建 Vault 和 Self 模板。
3. 所有测试和 `python scripts/validate_skill.py` 全部通过。
4. fixture 纵向流程能生成 Decision、Artifact、measured Outcome 和 Weekly Review。
5. `doctor --no-smoke` 通过。
6. 如果要启用 Bookmark 轮询，真实 `doctor` smoke 和 Bookmark dry-run 也必须通过。
7. Self 已由用户填写，不能只保留空模板。
8. 至少连续使用一周后，再决定是否进入官方 X API、多账号或独立前端等待办。

当前“已完成/受阻/待办”明细见 [docs/TASKS.md](TASKS.md)。
