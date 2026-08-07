# NextX 安装与完整操作手册

**适用版本：** v0.1  
**验证日期：** 2026-08-08  
**运行形态：** 单一 X 账号、本地 CLI + Obsidian + Agent 对话

这份手册同时回答三个问题：当前代码到底实现了什么、怎样安装、怎样从初始化一路验收到完整运营闭环。

## 1. 先理解产品边界

NextX 不是独立 Web 前端。它由三层组成：

| 层 | 实现 | 作用 |
| --- | --- | --- |
| 操作入口 | Codex CLI、Claude Code、Grok Build 或直接终端 | 理解自然语言、调用 Agent Skill、展示结果 |
| 确定性内核 | `nextx` Python CLI | 校验 JSON、幂等去重、状态转换、原子写入、生成 Brief 和 Views |
| 用户数据界面 | Obsidian Vault | 编辑 Self、查看 Signal/Decision/Artifact、审计历史 |

持久化只有四个原语：

```text
Self → Signal → Decision(do/defer/kill) → Artifact(draft/published/measured)
```

Outcome 嵌在 Artifact 内，Learn 是 Weekly Review 过程，不会创建第五种核心对象。NextX 永远不自动发帖、点赞、转发、关注或删除 X 内容。

## 2. 代码实现盘点

### 已实现能力

| 能力 | 关键代码 | 当前实现程度 |
| --- | --- | --- |
| CLI 与安装 | `pyproject.toml`、`src/nextx/cli.py`、`skills/nextx/scripts/bootstrap.py` | 一键创建用户级 Python 3.11+ 环境、安装构建依赖和 NextX；所有成功/失败输出结构化 JSON |
| Vault 与 Self | `vault.py`、`records.py`、`self_model.py` | 初始化五个 Self 模板；Markdown frontmatter 是权威数据；原子写入和单 Vault 写锁 |
| Signal 采集 | `signals.py`、`schemas/collector-envelope.v1.json` | Grok 文件导入、任意契约采集器导入、手动文本；整批校验、URL/ID/hash 去重 |
| X Bookmarks | `bookmarks.py`、`twitter_cli.py` | 读取 `twitter bookmarks --json`，初次最多 200、增量默认 50、dry-run、运行清单、幂等入库 |
| Grok 热点 | `prompts/grok-collector.md` | Grok Build 输出 Envelope JSON，再由 `nextx collect --source grok` 导入 |
| Today | `views.py` | 10 条自动候选 + 2 条手动位置；排除已裁决；单作者最多 2 条；生成 Bookmark Inbox |
| 深度拆解 | `analysis.py` | 只读取一个选定 Signal，生成事实/原帖观点/推断、结构、钩子、传播机制等分析 Brief |
| 选题裁决 | `decisions.py` | `do/defer/kill` 三态；`do` 必须有角度、原创增量、风险、证据确认；生成 topic-engine Brief |
| 草稿与发布 | `artifacts.py` | 仅 `do` 可生成 x-tweet-writer Brief；保存定稿；人工发布后校验并记录 X URL |
| Outcome 与周复盘 | `learning.py` | 手动录入 24h/7d 指标；同窗口替换；7d 后 measured；生成 Weekly Review 和最多 5 个提案槽 |
| Agent Skill | `skills/nextx/SKILL.md` | 一份 canonical Skill 路由所有意图；topic-engine 和 x-tweet-writer 仍由外部 Skill 负责 |
| 性能与可靠性 | `views.py`、`vault.py` | 可重建 `.nextx/index.json`；10,000 条 Signal 增量 Today 实测约 109ms |
| 调度模板 | `examples/com.nextx.bookmarks.plist` | macOS launchd 每 180 秒轮询；需要替换绝对路径和完成账号认证 |

### 目前不是“完全自动化”的部分

1. **Grok 不是 NextX 内置 SDK。** 先让 Grok Build 按 Prompt 输出 JSON，再导入；这样采集器可替换，避免绑定私有接口。
2. **深拆是 Brief 交接。** `analysis-brief` 把单条 Signal 交给当前 Agent 分析，但不会自动把分析结果写回 Signal。需要人工确认后再走 Decision。
3. **Bookmarks 是在线准实时轮询。** X 没有公开 Bookmark webhook，launchd 在线时每 180 秒调用一次；休眠期间暂停。
4. **Outcome 是手动回填。** 代码验证 24h/7d 格式和非负指标，但不会凭空读取 X 指标。
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
- Codex CLI 或 Claude Code：运行 canonical Agent Skill。

## 4. 推荐安装方式：一键安装

在仓库根目录执行：

```bash
python3 skills/nextx/scripts/bootstrap.py
```

安装器会：

1. 选择当前可用的 Python 3.11+；
2. 在 `~/.local/share/nextx/venv` 创建用户级隔离环境；
3. 源码仓库创建指向 `src/` 的隔离 launcher（无需网络）；发布版 Skill 安装/升级 `pip`、`setuptools`、`wheel` 后安装 `nextx-workbench`；
4. 输出可直接调用的 `nextx` 绝对路径。

安装器不写系统 Python、不写 Vault、不安装或认证 `twitter-cli`。源码 launcher 会随仓库代码更新而生效；发布版 Skill 没有源码时才走 pip 包安装。

可先检查而不写入：

```bash
python3 skills/nextx/scripts/bootstrap.py --dry-run
```

### 4.1 手动开发安装（备用）

#### 使用 Homebrew Python（macOS 推荐）

```bash
cd /Users/bingo/workspace/NextX

/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install -e . --quiet --no-build-isolation
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

不要长期使用关闭 TLS 校验的参数。`--no-build-isolation` 只应在当前虚拟环境已经有满足要求的构建工具时使用。

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

其中 `NEXTX_RUNTIME` 使用 bootstrap JSON 中的 `runtime`。需要改路径时只配置一次：

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

## 6. 完整自动化测试与 fixture 验收

### 6.1 静态与单元测试

在仓库根目录执行：

```bash
"$NEXTX_PYTHON" -m compileall -q "$NEXTX_ROOT/src"
PYTHONPATH="$NEXTX_ROOT/src" "$NEXTX_PYTHON" -m unittest discover -s "$NEXTX_ROOT/tests" -v
```

当前基线应为 **57 项测试全部通过**。测试覆盖：Vault 锁、frontmatter、Self、Signal、Bookmarks 解析与幂等、CLI JSON、默认 Vault 配置、bootstrap dry-run/launcher、自愈、Today、Analysis、Decision、Artifact、Outcome、Weekly Review、索引重建和 twitter-cli 失败路径。

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

模拟人工发布和 7d 回写：

```bash
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
  "bookmarks": 21
}
JSON

"$NEXTX" record-outcome --vault "$TEST_VAULT" "$ARTIFACT_ID" \
  --input-json "$TEST_VAULT/outcome.json"
"$NEXTX" weekly-review --vault "$TEST_VAULT"
sed -n '1,160p' "$TEST_VAULT/04. Views/Weekly Review.md"
```

预期：Artifact 状态为 `measured`，Weekly Review 显示 `做：1`、一个 measured Artifact、草稿时延和五个提案槽。整个流程不会发布到 X。

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

预期：返回 `ok: true`、`dry_run: true`，Vault 中不应新增 Signal。确认无误后再正式同步：

```bash
"$NEXTX" collect --vault "$NEXTX_VAULT" --source bookmarks
```

首轮默认最多读取 200 条，后续根据 `.nextx/bookmarks-state.json` 默认读取 50 条。相同 Tweet ID 会返回 duplicate，不覆盖用户编辑。

### 7.3 Grok 热点采集

把 [Grok Collector Prompt](../prompts/grok-collector.md) 提供给 Grok Build，并要求只输出 JSON。先检查 JSON 满足 [Collector Schema](../schemas/collector-envelope.v1.json)，再导入：

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

Today 只保留最多 10 条自动候选和 2 条手动候选；已存在 Decision 关联的 Signal 不再进入待裁决队列。

### 第二步：单帖深拆

对选中的 ID 执行：

```bash
"$NEXTX" analysis-brief --vault "$NEXTX_VAULT" x:123456789
```

把输出交给 Agent，要求只分析该 Signal，并分离：事实、原帖观点、推断、内容结构、钩子、传播机制、可迁移方法、风险与反证。分析结果先作为判断材料，不要直接当作 Decision。

### 第三步：做 / 缓 / 毙

```bash
"$NEXTX" decision-brief --vault "$NEXTX_VAULT" x:123456789
```

把 Brief 交给 `topic-engine`。Agent 返回 Decision JSON 后保存：

```bash
"$NEXTX" save-decision --vault "$NEXTX_VAULT" \
  --input-json /absolute/path/to/decision.json
```

`do` 必须提供证据、角度、原创增量、风险和理由；`defer`/`kill` 只需要理由码和理由。保存后检查：

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

NextX 不打开发布权限。用户在 X 人工确认事实、链接、声纹和禁区后发布，再记录 URL：

```bash
"$NEXTX" record-published --vault "$NEXTX_VAULT" artifact:... \
  --url "https://x.com/handle/status/123456789"
```

### 第六步：结果回写

24h 或 7d 后准备指标 JSON：

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

7d 回写会把 Artifact 状态变成 `measured`。同一窗口再次回写会替换旧快照，不会产生重复记录。

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
04. Views/      Today、Bookmark Inbox、Decision Board、Weekly Review
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
| `Another NextX sync is already running` | Vault 写锁存在 | 先确认没有同步进程，再处理 `.nextx/sync.lock` |
| Collector 被拒绝 | schema、account_key、source_id/URL 或字段缺失 | 对照 Collector Schema 修正后整批重试 |
| `Signal not found` | ID 不存在或格式不对 | 使用 `x:数字` 或从 Today 卡片复制 ID |
| `Only a do Decision can create an Artifact` | Decision 是 defer/kill | 先建立新的 do Decision，不能绕过闸门 |
| View 内容过期 | Projection 尚未重建 | 重新执行 `today` 或 `weekly-review` |
| launchd 不启动 | plist 占位符、路径或权限错误 | 先 `plutil -lint`，再检查 `launchctl print` 和日志 |

所有 CLI 失败都应返回非零退出码，并把 JSON 错误写到 stderr；不要把 stderr 当作成功结果继续交给 Agent。

## 13. 完成判定

可以把本机 v0.1 视为“代码完成、真实运营待验证”，必须同时满足：

1. `nextx --help` 正常。
2. `nextx init` 能创建 Vault 和 Self 模板。
3. 57 项测试全部通过。
4. fixture 纵向流程能生成 Decision、Artifact、measured Outcome 和 Weekly Review。
5. `doctor --no-smoke` 通过。
6. 如果要启用 Bookmark 轮询，真实 `doctor` smoke 和 Bookmark dry-run 也必须通过。
7. Self 已由用户填写，不能只保留空模板。
8. 至少连续使用一周后，再决定是否进入官方 X API、多账号或独立前端等待办。

当前“已完成/受阻/待办”明细见 [docs/TASKS.md](TASKS.md)。
