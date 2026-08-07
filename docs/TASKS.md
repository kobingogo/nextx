# NextX 任务台账

**当前版本：** v0.1（单一 X 账号）  
**更新时间：** 2026-08-07  
**状态来源：** 本文档是当前任务状态的唯一权威台账；`docs/superpowers/plans/` 中的复选框仅保留历史执行上下文。

## 状态与维护规则

- `已完成`：功能与必要验证均已存在，证据可以检查。
- `受阻`：实现路径明确，但依赖外部认证、用户决策或外部状态。
- `待办`：尚未开始且进入条件明确；纯设想不进入台账。
- 功能合并时同步更新任务状态和文末变更记录。
- 状态改变时沿用原任务 ID；已完成项补充证据，受阻项写解除条件，待办项写进入条件。

## 已完成

| ID | 模块 | 任务 | 优先级 | 状态 | 验收或证据 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-001 | 产品与架构 | 定义本地优先、单账号、Agent 对话 + Obsidian + CLI 的产品形态及四原语 | P0 | 已完成 | [产品架构](product-architecture.md)、[完整产品定义](superpowers/specs/2026-08-07-nextx-complete-product-design.md) | 用真实运营反馈校正边界 |
| NX-002 | CLI | 建立 Python 3.11+ 可安装 CLI、版本化 JSON 输出和结构化错误 | P0 | 已完成 | [CLI](../src/nextx/cli.py)、[CLI 测试](../tests/test_cli.py)，提交 `6eb7221` | 保持 v1 输出向后兼容 |
| NX-003 | Self / Vault | 初始化 Vault、五个 Self 模板、账号配置、原子写入和全局锁 | P0 | 已完成 | [Vault](../src/nextx/vault.py)、[Self](../src/nextx/self_model.py)、[测试](../tests/test_self_model.py) | 真实使用后完善 Self 内容 |
| NX-004 | Signal | 实现版本化 Collector Envelope、Grok/文件导入、手动 Signal、整批校验和幂等去重 | P0 | 已完成 | [Signal 实现](../src/nextx/signals.py)、[公共 Schema](../schemas/collector-envelope.v1.json)、[测试](../tests/test_signals.py) | 用新增 Collector 验证契约稳定性 |
| NX-005 | Grok | 将 Grok Build 定义为首选开放式热点采集器，并提供可验证 URL 的采集提示词 | P0 | 已完成 | [Grok Prompt](../prompts/grok-collector.md)、本机 Grok Build 1.0.0 支持 headless 与 JSON Schema | 执行一周真实热点采集 |
| NX-006 | Bookmarks | 实现 twitter-cli 收藏读取、首次/增量数量、幂等入库、dry-run 和运行状态 | P0 | 已完成 | [Bookmarks](../src/nextx/bookmarks.py)、[适配器](../src/nextx/twitter_cli.py)、[测试](../tests/test_bookmarks.py) | 解除 NX-B01 后做真实同步验收 |
| NX-007 | Obsidian Views | 生成 Today、Bookmark Inbox、Decision Board；限制 10 条自动 + 2 条手动及作者多样性 | P0 | 已完成 | [Views](../src/nextx/views.py)、[测试](../tests/test_views.py) | 用日常队列观察排序质量 |
| NX-008 | Analysis | 对选中 Signal 生成单帖深拆 Brief，强制分离事实、原帖观点与推断 | P1 | 已完成 | [Analysis](../src/nextx/analysis.py)、[测试](../tests/test_analysis.py) | 用真实收藏验证拆解质量 |
| NX-009 | Decision | 实现 `do / defer / kill` 校验、证据门槛、topic-engine Brief 和可审计持久化 | P0 | 已完成 | [Decision](../src/nextx/decisions.py)、[测试](../tests/test_decisions.py) | 统计真实裁决分布和转化率 |
| NX-010 | Artifact | 仅允许 `do` 生成写作 Brief 和草稿，记录人工发布 URL，禁止自动发布 | P0 | 已完成 | [Artifact](../src/nextx/artifacts.py)、[测试](../tests/test_artifacts.py) | 跑通真实帖子发布回填 |
| NX-011 | Outcome / Learn | 记录 24h/7d 指标、替换重复窗口、生成 Weekly Review 与人工 Playbook 提案槽 | P0 | 已完成 | [Learning](../src/nextx/learning.py)、[测试](../tests/test_learning.py) | 积累至少三条真实 measured Artifact |
| NX-012 | Agent Skill | 建立一份 canonical NextX Skill，路由采集、分析、裁决、写作与复盘并保留人工闸门 | P0 | 已完成 | [NextX Skill](../skills/nextx/SKILL.md)，Skill validator 通过 | 在 Codex/Grok 实际调用中迭代触发语 |
| NX-013 | 调度 | 提供 macOS launchd 每 180 秒同步收藏的配置模板 | P1 | 已完成 | [launchd 模板](../examples/com.nextx.bookmarks.plist)，`plutil -lint` 通过 | NX-B01 解除后安装到真实 Vault |
| NX-014 | 可靠性与隐私 | 实现原子写入、写锁、整批校验、状态机、最小上下文和只读 X 边界 | P0 | 已完成 | [架构说明](product-architecture.md#数据与一致性)、47 项测试 | 公开发布前增加安全披露流程 |
| NX-015 | 性能 | 在 10,000 条 Signal 门槛下加入可删除重建的 frontmatter 派生索引 | P1 | 已完成 | [索引实现](../src/nextx/views.py)、[索引测试](../tests/test_views.py)；增量 Today 实测约 109ms | 超过 100,000 条且 JSON 索引不足时才评估 SQLite |
| NX-016 | 交付验证 | 完成 fixture 纵向流程、47 项测试、源码编译、可编辑安装、Skill 与 plist 验证 | P0 | 已完成 | [测试目录](../tests/)、提交 `22154b8` | 在真实运营数据上补充验收 |

## 受阻

| ID | 模块 | 任务 | 优先级 | 状态 | 验收或证据 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-B01 | Bookmarks 运行环境 | 真实 X Bookmark smoke 与 dry-run | P0 | 受阻 | twitter-cli 已安装，但当前报错 `Twitter cookie extraction failed`；测试夹具链路正常 | 重新认证 twitter-cli；以 `nextx doctor` 和 `collect --source bookmarks --limit 1 --dry-run` 均成功作为解除条件 |

## 待办

| ID | 模块 | 任务 | 优先级 | 状态 | 验收或证据 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-P01 | 产品验证 | 使用一个真实账号连续运行至少一周，建立草稿时延、裁决转化和 Outcome 基线 | P0 | 待办 | v0.1 纵向功能已完成 | NX-B01 解除且 Self 初始化后进入 |
| NX-P02 | 开源准备 | 确定许可证并补充贡献、安全披露和支持范围 | P0 | 待办 | [开源边界](product-architecture.md#安全与开源边界) 已定义 | 仓库所有者在公开发布前选择 Apache-2.0、MIT 或其他许可证 |
| NX-P03 | 官方 X API | 增加官方 OAuth Bookmarks Collector | P1 | 待办 | Collector Envelope 已提供替换边界 | 当分发需求不能依赖私有 twitter-cli，或其稳定性持续不足时进入 |
| NX-P04 | 多账号 | 开放账号选择、配置隔离和分账号 Views | P1 | 待办 | 记录已带 `account_key: primary` | 出现第二个真实运营账号后进入 |
| NX-P05 | 交互界面 | 评估 Obsidian 插件、TUI 或独立前端 | P2 | 待办 | CLI JSON 和 Markdown 已提供 UI 边界 | Agent + Obsidian 的真实操作摩擦持续影响北极星指标时进入 |
| NX-P06 | Outcome 自动化 | 只读采集已发布 Artifact 的 24h/7d 指标 | P1 | 待办 | Outcome 状态机和输入格式已完成 | 人工回填成为稳定高频负担且指标读取可靠时进入 |
| NX-P07 | 发布工程 | 建立版本发布、兼容性矩阵和最小 CI | P1 | 待办 | 本地安装和测试已验证 | NX-P01 完成且准备首次公开版本时进入 |

## 状态变更记录

| 日期 | 任务 | 变更 | 依据 |
| --- | --- | --- | --- |
| 2026-08-07 | NX-001–NX-016 | 初始化为已完成 | `main` 已包含完整 v0.1 实现，47 项测试通过 |
| 2026-08-07 | NX-B01 | 初始化为受阻 | 真实 twitter-cli Cookie 提取失败，未写入私人收藏 |
| 2026-08-07 | NX-P01–NX-P07 | 初始化为待办 | 产品架构中已有明确进入条件，尚未实施 |
