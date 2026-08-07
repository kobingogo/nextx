# NextX Task Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一份可持续维护、带验证证据的 NextX 当前任务台账，并从 README 提供唯一入口。

**Architecture:** `docs/TASKS.md` 是实时任务状态的唯一权威文档；产品规格和历史实施计划继续保留，但不再承担进度跟踪。台账按已完成、受阻和待办分区，使用稳定任务 ID 和可检查证据。

**Tech Stack:** Markdown、Git、本地文件链接。

## Global Constraints

- 任务字段固定为 `ID`、`模块`、`任务`、`优先级`、`状态`、`验收或证据`、`下一步`。
- `已完成` 必须链接代码、测试、文档或提交证据。
- `受阻` 必须说明解除条件；`待办` 必须说明进入条件。
- 不引入负责人、工期、发布日期、外部任务系统或新依赖。
- README 只链接台账，不复制任务状态。

---

### Task 1: 建立并接入任务台账

**Files:**
- Create: `docs/TASKS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-07-task-ledger-design.md` 的状态口径；当前 Git 提交、测试与产品文档证据。
- Produces: 面向维护者的唯一实时任务状态页 `docs/TASKS.md`。

- [ ] **Step 1: 创建当前状态表**

  在 `docs/TASKS.md` 写入版本 `v0.1`、更新时间 `2026-08-07`、三种状态定义和维护规则。已完成区覆盖：本地 Vault/Self、通用 Signal、Grok 契约、Bookmarks、Today Views、Analysis Brief、Decision、Artifact、Outcome、Weekly Review、Agent Skill、launchd、可靠性、47 项测试和 10,000 Signal 派生索引。

- [ ] **Step 2: 记录真实阻塞和待办**

  受阻区记录 `twitter-cli Cookie 认证`，解除条件为真实 Bookmark smoke 与 dry-run 成功；待办区记录真实试运营、开源许可证、官方 X API、多账号、可选前端、自动 Outcome 和公开发布准备，并为每项写清进入条件。

- [ ] **Step 3: 增加 README 入口**

  在 README 开头产品介绍之后增加“项目状态”段落，只链接 `docs/TASKS.md`，并说明历史实施计划不代表当前进度。

- [ ] **Step 4: 验证台账证据和文档格式**

  Run: `rg -n '已完成|受阻|待办|47|10,000|Cookie' docs/TASKS.md`

  Expected: 每个当前状态和关键验证证据至少命中一次。

  Run: `git diff --check`

  Expected: 无输出，退出码为 0。

- [ ] **Step 5: 提交**

  ```bash
  git add docs/TASKS.md README.md docs/superpowers/plans/2026-08-07-task-ledger.md
  git commit -m "docs: add maintained NextX task ledger"
  ```
