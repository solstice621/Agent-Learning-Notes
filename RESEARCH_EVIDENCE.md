# 设计动机证据与本轮补查

[总目录](README.md) · [方法](RESEARCH_METHOD.md)

## 1. 能直接归因给作者的新增材料

| 材料 | 支持的具体理由 | 不支持的外推 |
|---|---|---|
| [Codex PR #51556](https://github.com/openai/codex/pull/51556) | 中断不能丢掉动态工具终态；需要排除迟到模型上下文 | 所有子进程/所有工具平台都已无泄漏 |
| [Codex 相关合并提交](https://github.com/openai/codex/commit/18e28fe1b96db7e1d6b13584bec37c41f71b8b0e) | 确认该变更背景与回归测试目标；2026-10-07 | 本轮运行过这些回归测试 |
| [Codex timing 测试提交](https://github.com/openai/codex/commit/d4eed6dca57fc72298808aed5a4bfe43285bf98f) | direct/nested Code Mode 计时事件的重复计数需要断言 | 所有费用归因已准确 |
| [OpenCode EventFeed 决策](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/event-stream-architecture.md) | 减少重复编码且维持每连接独立失败；共享 PubSub 的候选取舍 | 编码微基准可换算成端到端 Agent 提速 |
| [OpenCode Catalog 历史决策](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/catalog-config-plugin-lifecycle.md) | 任意 Config transform 扩大 reload 范围，选域内 Catalog transform | 文中历史 API 草图就是当前 SDK |
| [DSH Handle-based persistence 决策](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/.agents/notes/implemented/architecture/2026-08-27-handle-based-session-persistence.md) | 归属隐式、修复职责混合、revision 重试使 ownership 无处安放 | ADR 当时标为 planned 的跨进程层已经被本轮验证 |
| [DSH Attempt stream settlement 决策](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/.agents/notes/implemented/architecture/2026-09-01-v2-embedded-assistant-streams.md) | 逐 chunk 顶层事件写放大；只存成功文本又丢证据；结算前硬故障丢流是明确代价 | payload 字节也只随 attempt 数增长，或 live stream 是 WAL |

以上是选定记录，不是对全部 Issue/PR 历史的穷尽检索。没有发现直接动机的决策，正文保持设计推导身份。

## 2. 本轮进一步核对的关键实现

[OpenCode run-coordinator.ts](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L1-L245) 明确说明 pendingWake 防止 drain 与 idle transition 之间丢唤醒，以及 awaitSettlement/awaitIdle 的差别。

[DSH tool-calls.ts](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L115-L260) 将 inFlight、slots、committed 分开；由此推导“在途有界不限制全部结果积压”。这是一项静态资源边界分析，不是测得的内存泄漏。

[DSH Session 源码](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L790-L1015) 对输入快照/冻结，按 generation 决定投影缓存，并返回新外层数组；增量投影与完整数组复制的复杂度应分开。

[DSH telemetry coordinator](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L1-L300) 的 per-event containment 与 handoff high watermark，可留下被后续成功记录越过的缺口；这是 best-effort 边界，不是自动定性为 bug。

[DSH checkpoint-policy](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L1-L100) 给出模型/顶层工具前的检查点；只有挂载且经过该路径时才能依赖，不能推广到任意 profile。

## 3. 延续的固定源码证据

各主笔记保留上一版全部 70 个原文代码块及其定位链接；涉及 client、compact、extension registry、spawn、ThreadStore、execution、step、retry、supervisor、subagent、Session、Goal Driver、EventFeed 等。代码与官方固定文件的一致性在 CI 重新验证，不依靠本笔记重复转述。

其他官方契约、测试文件沿各篇 F/D/T 引用直接访问。源码片段检查覆盖片段真实性；它不宣称全部长文件都被逐行审计，也不证明每个声明的契约已有动态验证。

## 4. 证据用途矩阵

| 问题 | 首选证据 | 本轮状态 |
|---|---|---|
| 现有实现在哪个边界提交/等待？ | 固定源码与相邻分支 | 静态分析＋摘录匹配 |
| 作者当时为什么改变？ | 明确 Why、Problem、Alternatives 的记录 | 选定 PR/ADR 补查 |
| 不这样做能否产生反例？ | 推导＋独立最小模型 | 22 项机制模型运行 |
| 真实产品是否出现该问题？ | 上游测试、复现日志、平台实验 | 未运行，不能仅由反例认定 |
| 哪个实现更快或更好？ | 可比工作负载与端到端测量 | 无实测排名 |

为了学习选择方案，保留“作者未说明”和“本轮尚未运行”是必要信息，不应被通用架构术语填满。
