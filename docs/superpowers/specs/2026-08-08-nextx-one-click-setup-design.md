# NextX 一键安装与初始化设计

**状态：** 已实施，待真实环境验收  
**目标版本：** v0.2 setup experience  
**默认 Vault：** `~/Documents/NextX`

## 1. 问题与目标

当前用户需要先选择 Python、创建 venv、安装 editable package、记住 Vault 路径，再运行 `init`。这与 Skill 插件“安装后即可使用”的体验不一致。

目标是让用户安装 `$nextx` Skill 后，只需对 Agent 说“初始化 NextX”，Agent 就能完成运行时检测、配置写入、Vault 初始化和可用性报告。用户只在必要时确认 Vault 路径和外部 X 认证，不要求用户理解 Python 打包细节。

## 2. 用户体验

默认流程：

```text
安装 $nextx
  → “初始化 NextX”
  → 检测/准备本地运行时
  → 使用 ~/Documents/NextX（不存在则创建）
  → 创建 Self、Signal、Decision、Artifact、Views
  → 写入一次性用户配置
  → 输出下一步 Self 填写和可选 twitter-cli 认证提示
  → “同步收藏并生成今日裁决队列”
```

显式改路径时，只需执行一次 `nextx setup --vault PATH` 或通过 Agent 表达目标路径。后续命令不再要求重复传 `--vault`；显式参数继续拥有最高优先级。

## 3. CLI 设计

新增：

```text
nextx setup [--vault PATH] [--runtime PATH] [--yes]
nextx config [--show]
```

所有现有命令的 `--vault` 改为可选，统一按以下优先级解析：

1. 当前命令显式的 `--vault`。
2. 环境变量 `NEXTX_VAULT`。
3. 用户配置 `~/.config/nextx/config.json`。
4. 默认路径 `~/Documents/NextX`。

`setup` 必须幂等：已有 Self 内容、Signal、Decision、Artifact 和 Views 不被覆盖。配置只保存 Vault 路径、配置版本和最近一次 setup 时间，不保存 Cookie、Token 或 OAuth 密钥。

`config --show` 输出解析后的路径和能力状态，不输出任何秘密。

## 4. 运行时准备

Skill 触发初始化时执行一个最小 bootstrap 流程：

1. 优先使用当前可执行的 `nextx`。
2. 否则寻找 Python 3.11+，创建用户级运行时目录（默认 `~/.local/share/nextx/venv`）。
3. 开发仓库中创建指向当前 `src/` 的隔离 launcher；发布 Skill 中从正式包源安装并准备构建依赖。
4. 安装失败时返回明确的 Python 版本、pip、构建依赖或证书原因，不静默修改系统 Python。

Bootstrap 不安装或认证 `twitter-cli`。它只检测该命令是否存在，并把 Bookmark 作为可选能力报告。

运行时目录不进入 Vault，不进入 Git，也不影响用户已有 Python 环境。

统一入口：源码 checkout 使用根目录 `./install-nextx`；终端默认显示下一步提示，Codex、Claude Code、Grok Build 使用 `./install-nextx --json`，读取同一份 JSON 输出并优先调用其中的 `nextx`（冲突时回退到 `executable`）。Skill 目录独立分发时，使用等价的 `python3 skills/nextx/scripts/bootstrap.py`。安装器默认在用户级 `~/.local/bin` 暴露 `nextx`，不修改系统目录。

## 5. Skill 行为

`skills/nextx/SKILL.md` 增加 setup 路由：

- 用户说“初始化/安装/配置 NextX”时，先执行 bootstrap，再执行 `nextx setup --runtime RUNTIME --yes`。
- 没有指定路径时使用 `~/Documents/NextX`，不存在则创建。
- 只在配置不存在且用户希望改路径时提问；配置已有时不重复询问。
- setup 完成后自动运行 `nextx doctor --no-smoke`，并把缺失的 twitter-cli 作为可选阻塞，不阻止 Grok、手动 Signal、Decision 和 Artifact 工作流。
- 首次使用 Bookmarks 时才建议认证 twitter-cli，并提供 dry-run。

Skill 仍保持人工闸门：不自动发帖、不自动修改 Playbook、不上传整个 Vault。

## 6. 配置与兼容性

用户配置格式：

```json
{
  "schema_version": 1,
  "vault": "/Users/<user>/Documents/NextX",
  "runtime": "/Users/<user>/.local/share/nextx/venv",
  "setup_at": "2026-08-08T00:00:00+00:00"
}
```

旧命令和显式 `--vault` 必须继续可用。已有 Vault 只需运行 `setup` 绑定路径，不迁移 Markdown。配置损坏时 CLI 应返回可修复错误，并允许用 `setup --vault PATH` 重建配置。

## 7. 安全与可恢复性

- 默认目录创建前不删除或覆盖任何用户目录。
- `setup` 只创建缺失目录和文件；已有 Markdown 保留原文。
- 配置采用原子写入。
- bootstrap 只在用户级运行时目录写入依赖。
- 外部网络安装失败时，不伪装成 setup 成功。
- X Cookie、Token、OAuth 密钥继续由外部工具管理，不进入配置或 Vault。

## 8. 验收标准

1. 全新环境执行 setup 后，`~/Documents/NextX`、Self 模板和 `.nextx/config.json` 均存在。
2. 第二次执行 setup 不覆盖用户编辑。
3. 未传 `--vault` 的 `today`、`collect`、`weekly-review` 能解析默认配置路径。
4. `NEXTX_VAULT` 和显式 `--vault` 能覆盖默认路径。
5. 配置损坏、Python 不满足版本、pip 安装失败和 twitter-cli 缺失都有可操作错误。
6. 现有测试保持通过，并新增 setup、路径优先级、幂等、bootstrap、统一安装入口和人类/JSON 输出测试（当前 59 项）。
7. 真实 Bookmark 认证仍是可选外部步骤，不影响非 X 采集流程。

## 9. 不做的事情

- 不开发独立 Web 前端。
- 不在 setup 中自动登录 X 或抓取 Cookie。
- 不引入数据库、后台常驻 Worker 或远程配置服务。
- 不为每个 Agent 维护不同的安装逻辑；Codex、Claude Code、Grok Build 共用同一 canonical Skill。
