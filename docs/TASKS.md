# NextX 任务台账

**当前版本：** v0.3.0-alpha.2（单一 X 账号）
**更新时间：** 2026-08-09  
**状态来源：** 本文档是当前任务状态的唯一权威台账；`docs/superpowers/plans/` 中的复选框仅保留历史执行上下文。

## 状态与维护规则

- `已完成`：功能与必要验证均已存在，证据可以检查。
- `受阻`：实现路径明确，但依赖外部认证、用户决策或外部状态。
- `待办`：尚未开始且进入条件明确；纯设想不进入台账。
- `进行中`：已经开始，尚未达到该版本的完整验收门槛。
- 功能合并时同步更新任务状态和文末变更记录。
- 状态改变时沿用原任务 ID；已完成项补充证据，受阻项写解除条件，待办项写进入条件。

## 已完成

| ID | 模块 | 任务 | 优先级 | 状态 | 验收或证据 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-001 | 产品与架构 | 定义本地优先、单账号、Agent 对话 + Obsidian + CLI 的产品形态及四原语 | P0 | 已完成 | [产品架构](product-architecture.md)、[完整产品定义](superpowers/specs/2026-08-07-nextx-complete-product-design.md) | 用真实运营反馈校正边界 |
| NX-002 | CLI | 建立 Python 3.11+ 可安装 CLI、版本化 JSON 输出和结构化错误 | P0 | 已完成 | [CLI](../src/nextx/cli.py)、[CLI 测试](../tests/test_cli.py)，提交 `6eb7221` | 保持 v1 输出向后兼容 |
| NX-003 | Self / Vault | 初始化 Vault、六个 Self 模板、账号配置、原子写入和全局锁 | P0 | 已完成 | [Vault](../src/nextx/vault.py)、[Self](../src/nextx/self_model.py)、[测试](../tests/test_self_model.py) | 真实使用后完善 Self 内容 |
| NX-004 | Signal | 实现版本化 Collector Envelope、Grok/文件导入、手动 Signal、整批校验和幂等去重 | P0 | 已完成 | [Signal 实现](../src/nextx/signals.py)、[公共 Schema](../schemas/collector-envelope.v1.json)、[测试](../tests/test_signals.py) | 用新增 Collector 验证契约稳定性 |
| NX-005 | Grok | 将 Grok Build 定义为首选开放式热点采集器，并提供可验证 URL 的采集提示词 | P0 | 已完成 | [Grok Prompt](../prompts/grok-collector.md)、本机 Grok Build 1.0.0 支持 headless 与 JSON Schema | 执行一周真实热点采集 |
| NX-006 | Bookmarks | 实现 twitter-cli 收藏读取、首次/增量数量、幂等入库、dry-run 和运行状态 | P0 | 已完成 | [Bookmarks](../src/nextx/bookmarks.py)、[适配器](../src/nextx/twitter_cli.py)、[测试](../tests/test_bookmarks.py) | 解除 NX-B01 后做真实同步验收 |
| NX-007 | Obsidian Views | 生成 Today、Bookmark Inbox、Decision Board；限制 10 条自动 + 2 条手动及作者多样性 | P0 | 已完成 | [Views](../src/nextx/views.py)、[测试](../tests/test_views.py) | 用日常队列观察排序质量 |
| NX-008 | Analysis | 对选中 Signal 生成单帖深拆 Brief，强制分离事实、原帖观点与推断 | P1 | 已完成 | [Analysis](../src/nextx/analysis.py)、[测试](../tests/test_analysis.py) | 用真实收藏验证拆解质量 |
| NX-009 | Decision | 实现 `do / defer / kill` 校验、证据门槛、topic-engine Brief 和可审计持久化 | P0 | 已完成 | [Decision](../src/nextx/decisions.py)、[测试](../tests/test_decisions.py) | 统计真实裁决分布和转化率 |
| NX-010 | Artifact | 仅允许 `do` 生成写作 Brief 和草稿，记录人工发布 URL，禁止自动发布 | P0 | 已完成 | [Artifact](../src/nextx/artifacts.py)、[测试](../tests/test_artifacts.py) | 跑通真实帖子发布回填 |
| NX-011 | Outcome / Learn | 记录 1h/24h/7d 指标、替换重复窗口、生成 Weekly Review 与人工 Playbook 提案槽 | P0 | 已完成 | [Learning](../src/nextx/learning.py)、[测试](../tests/test_learning.py) | 积累至少三条真实 measured Artifact |
| NX-012 | Agent Skill | 建立一份 canonical NextX Skill，路由采集、分析、裁决、写作与复盘并保留人工闸门 | P0 | 已完成 | [NextX Skill](../skills/nextx/SKILL.md)，Skill validator 通过 | 在 Codex/Grok 实际调用中迭代触发语 |
| NX-013 | 调度 | 提供 macOS launchd 每 180 秒同步收藏的配置模板 | P1 | 已完成 | [launchd 模板](../examples/com.nextx.bookmarks.plist)，`plutil -lint` 通过 | NX-B01 解除后安装到真实 Vault |
| NX-014 | 可靠性与隐私 | 实现原子写入、写锁、整批校验、状态机、最小上下文和只读 X 边界 | P0 | 已完成 | [架构说明](product-architecture.md#数据与一致性)、P0–P2 回归测试 | 持续跟踪真实运行的恢复体验 |
| NX-015 | 性能 | 在 10,000 条 Signal 门槛下加入可删除重建的 frontmatter 派生索引 | P1 | 已完成 | [索引实现](../src/nextx/views.py)、[索引测试](../tests/test_views.py)；增量 Today 实测约 109ms | 超过 100,000 条且 JSON 索引不足时才评估 SQLite |
| NX-016 | 交付验证 | 完成 fixture 纵向流程、单元测试、源码编译、可编辑安装、统一一键安装入口和用户级 nextx 命令、Skill 与 plist 验证 | P0 | 已完成 | [测试目录](../tests/)、[install-nextx](../install-nextx)、[bootstrap](../skills/nextx/scripts/bootstrap.py)、[CI](../.github/workflows/ci.yml) | 在真实运营数据上补充验收 |
| NX-017 | 安全加固 | 修复公开内容提示注入、安装器 PATH/冲突入口、Windows launcher、证据伪造、Outcome 并发覆盖和机器区块碰撞 | P0 | 已完成 | [Brief 边界](../src/nextx/briefs.py)、[安装器](../skills/nextx/scripts/bootstrap.py)、[证据校验](../src/nextx/decisions.py)、[Outcome](../src/nextx/learning.py) | 真实 Agent 使用中观察拒绝与误伤率 |
| NX-018 | 闭环 P0 | 发布检查清单、review/confirm 状态机、defer 到期复访、Analysis 写回、4 周互动命中率 | P0 | 已完成 | [Artifact](../src/nextx/artifacts.py)、[Decision](../src/nextx/decisions.py)、[Analysis](../src/nextx/analysis.py)、[Learning](../src/nextx/learning.py) 及回归测试 | 用真实 4 周样本校准命中率口径 |
| NX-019 | 闭环 P1 | Self 就绪度、候选解释性排序/去重、持久 Brief 交接、收藏健康与显式全量对账 | P1 | 已完成 | [Views](../src/nextx/views.py)、[Bookmarks](../src/nextx/bookmarks.py)、[CLI](../src/nextx/cli.py) 及回归测试 | 观察真实队列误排与遗漏 |
| NX-020 | 闭环 P2 | Decision 实验标签和周报归因；单 Vault primary account registry 与混合配置拒绝 | P2 | 已完成 | [Accounts](../src/nextx/accounts.py)、[Decision](../src/nextx/decisions.py)、[Learning](../src/nextx/learning.py) 及回归测试 | 第二个真实账号出现后再设计显式路由 |
| NX-021 | Skill 工程化 | 闭合独立安装、可移植 Skill 路径、只读预检、输入契约、Skill 语义 CI 和开源治理 | P0 | 已完成 | [独立安装器](../skills/nextx/scripts/install-nextx)、[预检](../src/nextx/preflight.py)、[Contracts](contracts.md)、[Skill CI](../scripts/validate_skill.py)、[治理](../CONTRIBUTING.md) | 首次 tag 后将默认 ref 从 `main` 固定到发行 tag |
| NX-022 | 对抗性修复 | 封死发布清单绕过、Agent 重试幂等、dry-run 零写入、缓存身份隔离、7d 指标口径、可恢复锁与 Brief 边界 | P0 | 已完成 | [Artifact](../src/nextx/artifacts.py)、[安装器](../skills/nextx/scripts/bootstrap.py)、[Vault](../src/nextx/vault.py)、[回归测试](../tests/) | 真实一周运营中观察误拒绝、锁恢复与安装回退 |
| NX-023 | 新手体验 | 提供从安装、初始化、首个 Signal 到发布复盘的中文入门指南，并链接完整运维文档 | P1 | 已完成 | [新手指南](GETTING_STARTED.md)、[README 入口](../README.md)、[操作手册入口](OPERATIONS.md) | 根据首次真实用户反馈压缩步骤 |
| NX-024 | 对话优先 Skill | 将安装、Vault 设置、Self 初始化和日常运营收敛为 Agent 对话协议；提供 `next-step` 与 `configure-self` 确定性内核 | P0 | 已完成 | [NextX Skill](../skills/nextx/SKILL.md)、[CLI](../src/nextx/cli.py)、[Self](../src/nextx/self_model.py)、[Self Contract](../schemas/self-input.v1.json) | 在 Codex、Claude Code、Grok Build 各完成一次真实安装引导 |
| NX-025 | 三端 Agent 安装闭环 | 一键识别 Codex、Claude Code、Grok Build，部署受控 canonical Skill，并通过“初始化 NextX”进入对话式初始化 | P0 | 已完成 | [安装器](../skills/nextx/scripts/bootstrap.py)、[跨 Agent 回归测试](../tests/test_bootstrap.py)、[操作手册](OPERATIONS.md) | 在真实三端各做一次新会话验收 |
| NX-026 | 起号 Quote Sprint | 将高质量 Quote 实现为候选采集、时效队列、受限 Decision/Artifact、人工可见性观察与三端对话路由 | P0 | 已完成 | [Quote 指南](QUOTE_SPRINT.md)、[Collector Prompt](../prompts/quote-collector.md)、[实现](../src/nextx/)、[回归测试](../tests/) | 用一个真实冷启动账号连续一周校准窗口、排序与质量闸门 |
| NX-027 | Growth Loop v0.2 | 实现 Growth Strategy、强制 Growth Contract、Reply Sprint、Thread Pack/Asset Manifest、1h/24h/7d Outcome、同类基线与小白“下一步行动” | P0 | 已完成 | [Growth Loop 指南](GROWTH_LOOP.md)、[Self](../src/nextx/self_model.py)、[Decision](../src/nextx/decisions.py)、[Artifact](../src/nextx/artifacts.py)、[Learning](../src/nextx/learning.py)、[端到端测试](../tests/test_growth_loop.py) | 用真实账号验证行动推荐与样本阈值 |
| NX-P02 | 开源准备 | 固定许可证并补充贡献、安全披露和支持范围 | P0 | 已完成 | [Apache-2.0](../LICENSE)、[贡献指南](../CONTRIBUTING.md)、[安全策略](../SECURITY.md) | 真实开源协作后按 issue 数据调整模板 |

## 进行中

| ID | 模块 | 任务 | 优先级 | 状态 | 当前证据 | 完成门槛 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-028 | v0.2-rc 稳定化 | 修复 Signal 路径碰撞、Windows 锁探测、Outcome 时间与审计语义、跨账号投影、Reply 队列、收藏完整快照、独立安装依赖与升级路径 | P0 | 已完成 | `v0.3.0-alpha.2`；143 项回归、隔离 wheel 安装、构建隔离和 Skill 校验均已验证 | 进入 NX-B02 的真实三端 Agent 验收 |
| NX-029 | v0.3 决策系统 | 让 Growth Strategy 驱动 Discovery/Authority/Conversion 的下一步排序；建立可计算北极星时延、到期 Outcome、证据/反例约束的 repeat/alter/stop Playbook；完善小白对话引导 | P0 | 已完成 | `v0.3.0-alpha.2`；Growth Planner、Conversion 冷启动、review-ready 北极星、独立样本与格式/写入契约回归均通过 | 用真实运营样本校正指标阈值与推荐质量 |

## 受阻

| ID | 模块 | 任务 | 优先级 | 状态 | 验收或证据 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-B01 | Bookmarks 运行环境 | 真实 X Bookmark smoke 与 dry-run | P0 | 受阻 | twitter-cli 已安装，但当前报错 `Twitter cookie extraction failed`；测试夹具链路正常 | 重新认证 twitter-cli；以 `nextx doctor` 和 `collect --source bookmarks --limit 1 --dry-run` 均成功作为解除条件 |
| NX-B02 | 真实 Agent 验收 | 在 Codex、Claude Code、Grok Build 三端各跑一次“初始化 NextX → Self/Strategy → Signal → Decision → Artifact”的真实新会话黄金路径 | P0 | 受阻 | 安装器已检测到三端并部署 canonical Skill；自动化覆盖安装、路径和预检，不替代真实会话 | 需要三端实际可用会话与用户确认；不阻塞公开 Alpha，但阻塞“已验证三端运营体验”的声明 |

## 待办

| ID | 模块 | 任务 | 优先级 | 状态 | 验收或证据 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| NX-P01 | 产品验证 | 使用一个真实账号连续运行至少一周，验证 Growth Loop 行动推荐、草稿时延、裁决转化和 1h/24h/7d 反馈采集 | P0 | 待办 | v0.2 fixture 纵向功能已完成 | Self 初始化后进入；Bookmarks 并非前置条件 |
| NX-P03 | 官方 X API | 增加官方 OAuth Bookmarks Collector | P1 | 待办 | Collector Envelope 已提供替换边界 | 当分发需求不能依赖私有 twitter-cli，或其稳定性持续不足时进入 |
| NX-P04 | 多账号 | 开放账号选择、显式 Vault 配置隔离和分账号 Views | P1 | 待办 | 已有 primary registry 与混合配置拒绝，不会混淆样本 | 出现第二个真实运营账号后进入 |
| NX-P05 | 交互界面 | 评估 Obsidian 插件、TUI 或独立前端 | P2 | 待办 | CLI JSON 和 Markdown 已提供 UI 边界 | Agent + Obsidian 的真实操作摩擦持续影响北极星指标时进入 |
| NX-P06 | Outcome 自动化 | 只读采集已发布 Artifact 的 1h/24h/7d 指标 | P1 | 待办 | Outcome 状态机和输入格式已完成 | 人工回填成为稳定高频负担且指标读取可靠时进入 |
| NX-P07 | 发布工程 | 建立签名发布、兼容性矩阵和发行物校验 | P1 | 待办 | 已有 macOS/Linux/Windows CI、独立 Git 安装回归和 `source_revision` 审计 | 首次公开 tag 时生成校验和并建立 Release 流程 |

## 状态变更记录

| 日期 | 任务 | 变更 | 依据 |
| --- | --- | --- | --- |
| 2026-08-07 | NX-001–NX-016 | 初始化为已完成 | `main` 已包含完整 v0.1 实现，47 项测试通过 |
| 2026-08-07 | NX-B01 | 初始化为受阻 | 真实 twitter-cli Cookie 提取失败，未写入私人收藏 |
| 2026-08-07 | NX-P01–NX-P07 | 初始化为待办 | 产品架构中已有明确进入条件，尚未实施 |
| 2026-08-08 | NX-B01 | 仍受阻 | 代码与 fixture 流程可用，真实 Cookie 认证仍需外部恢复 |
| 2026-08-08 | NX-016 | 增补一键安装与默认 Vault 配置 | `nextx setup/config`、Skill bootstrap、59 项测试、源码运行演练通过 |
| 2026-08-08 | NX-016 | 增加跨 Agent 统一安装命令 | 根目录 `./install-nextx`、Agent JSON 安装契约和入口测试通过 |
| 2026-08-08 | NX-017 | 完成对抗性审查修复 | 新增不可信内容边界、结构化证据、锁内 Outcome 合并、安装器加固与跨平台 CI；68 项测试通过 |
| 2026-08-08 | NX-018–NX-020 | 完成 P0–P2 运营闭环断点修复 | 发布三段闸门、缓办复访、深拆写回与北极星指标；候选排序/去重、收藏对账健康与持久 Agent 交接；实验归因和单 Vault 账号隔离基础 |
| 2026-08-08 | NX-021、NX-P02 | 完成 Skill 工程化与开源治理清理 | 独立 Git 安装、跨平台入口、可验证 Skill 路径、只读预检、五份输入契约、语义 CI、贡献和安全披露文档 |
| 2026-08-08 | NX-022 | 完成审查问题的顺序修复 | 发布清单机读边界、相同输入重试复用、dry-run 失败零写入、缓存按仓库/ref 隔离、GitHub 归档回退、7d 周报口径、锁恢复和不可信标签转义均有回归测试 |
| 2026-08-08 | NX-023 | 新增中文新手指南 | 覆盖一键安装、默认/自定义 Vault、最小闭环、三种采集、发布闸门、隐私边界与常见故障 |
| 2026-08-08 | NX-024 | 完成对话优先 Skill 基础设施 | Skill 将 CLI 降为内部执行层；新增只读下一步状态和确认后写入的对话式 Self 配置 |
| 2026-08-08 | NX-025 | 完成三端 Agent 安装闭环 | 安装器以 `--agents auto` 自动识别并部署；Codex/Grok 共享 Agent-Skills 根，Claude 使用官方用户根；同名非托管 Skill 冲突安全拒绝，并用“初始化 NextX”完成对话启动 |
| 2026-08-08 | NX-026 | 完成起号 Quote Sprint | 新增 Quote Collector Prompt、带原帖/作者/窗口校验的候选 Signal、最多三条的 View、受限 Quote Decision/Artifact、QT 写作交接、人工可见性观察与完整回归覆盖 |
| 2026-08-08 | NX-027 | 完成 v0.2 Growth Loop | 增加用户确认的增长策略、Growth Contract、Reply 候选/时效队列、Reply 锁定草稿、Thread Pack 与资产清单、发布后行动、1h/24h/7d 反馈、三样本 Playbook 门槛、Growth Loop View 与端到端测试 |
| 2026-08-09 | NX-028、NX-029 | 启动 v0.2-rc → v0.3 版本目标 | 先收口审查发现的数据完整性、安装与运行断点，再让策略、指标与学习真正驱动下一步行动；外部账号认证和连续运营验证仍独立记录 |
| 2026-08-09 | NX-028、NX-029 | 发布 v0.3.0 Alpha 1 | commit `48937e1`、tag `v0.3.0-alpha.1` 已推送；138 项测试、编译、Skill 校验、隔离安装和安装器 dry-run 通过 |
| 2026-08-09 | NX-028 | 验证远端发行物可复现安装 | 从 GitHub 的 `v0.3.0-alpha.1` 新克隆到临时目录，隔离 runtime 安装成功；`nextx version` 返回 `0.3.0`，`setup` 与渐进式 `next-step` 均成功 |
| 2026-08-09 | NX-028、NX-029 | 修复最新审核 P0/P1 并发布 Alpha 2 | `v0.3.0-alpha.2`；143 项回归、隔离构建/安装、Bookmark→Decision、Outcome、独立样本、Conversion、Artifact 契约、写锁与 Skill 语义校验通过；补齐 Windows HOME/UTF-8/Skill 镜像兼容 |
