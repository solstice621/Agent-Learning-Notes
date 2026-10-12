# 官方源码索引

[总目录](README.md) · [版本锁](source-lock.json)

本版的代码块直接摘录自以下 **24 个不同源码/测试文件**。每篇标明实际定位范围，`source` 标记对应紧随其后的代码块；核验脚本输出准确匹配行。此清单不是全仓库审计，也不表示每个文件都全文读完。

## Codex｜10 个节选来源

统一前缀 `codex-rs/`，固定 Commit `a9b0815167c27ab13719dd12d13b63e02b70d221`。

| 源码 | 核对范围 | 用于专题 |
|---|---|---|
| `core/src/session/turn.rs` | 420–560 | 01 |
| `core/src/compact.rs` | 66–130 | 02 |
| `core/src/tools/orchestrator.rs` | 173–231 | 03 |
| `core/src/tools/parallel.rs` | 190–285 | 03、08 |
| `core/src/client.rs` | 259–365 | 04 |
| `ext/extension-api/src/registry.rs` | 135–225 | 05 |
| `core/src/agent/control/spawn.rs` | 310–372 | 06 |
| `core/src/session/daemon_recovery.rs` | 文件开头至末尾 | 07 |
| `thread-store/src/store.rs` | 1–230，节选策略和持久化接口 | 07 |
| `core/tests/suite/tool_parallelism.rs` | 93–177 | 08 |

入口：[固定 Codex 源码树](https://github.com/openai/codex/tree/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs)。测试文件只做源码阅读，没有在本轮运行。辅助阅读包括 ThreadStore、Exec Server、Rollout Trace 的官方 README，各篇给出固定链接。

## OpenCode｜7 个节选来源

统一前缀 `packages/`，固定 Commit `60a212c0769acd96b446acbadeb790486830f91d`。

| 源码 | 核对范围 | 用于专题 |
|---|---|---|
| `core/src/session/execution.ts` | 66–182 | 01、07 |
| `core/src/session/runner/llm.ts` | 165–282 | 01、02 |
| `core/src/session/runner/step.ts` | 86–150 | 03 |
| `core/src/session/runner/retry.ts` | 25–109 | 04 |
| `core/src/plugin/supervisor.ts` | 65–168 | 05 |
| `core/src/tool/plugin/subagent.ts` | 166–269 | 06 |
| `server/src/event-feed.ts` | 文件开头至末尾 | 08 |

入口：[固定 OpenCode 源码树](https://github.com/anomalyco/opencode/tree/60a212c0769acd96b446acbadeb790486830f91d/packages)。辅助阅读包括 `specs/v2/session.md`、`tools.md`、事件流设计、历史 Catalog 决策记录和 EventFeed 测试；历史方案不当作当前 API。

## DSH｜7 个节选来源

统一前缀 `packages/`，固定 Commit `d743267388641bc76f17c45ce8b4c231aed1d32c`。

| 源码 | 核对范围 | 用于专题 |
|---|---|---|
| `core/agent-loop/src/agent.ts` | 156–191、307–541 | 01、04 |
| `core/session/src/index.ts` | 800–1020，另读类型校验上下文 | 02 |
| `core/agent-loop/src/tool-calls.ts` | 140–250 | 03 |
| `core/agent-loop/src/index.ts` | 110–222 | 05 |
| `goal/goal-round-driver/src/index.ts` | 88–199 | 06 |
| `session/session-checkpoint-policy/src/index.ts` | 文件开头至末尾 | 07 |
| `session/session-telemetry/src/coordinator.ts` | 1–270，节选捕获/交接/隔离方法 | 08 |

入口：[固定 DSH 源码树](https://github.com/deepseek-ai/deepseek-harness/tree/d743267388641bc76f17c45ce8b4c231aed1d32c/packages)。辅助阅读包括 Session、Persistence、Sandbox、Compaction、LLM、Goal、Subagent、Telemetry 的接口/文档。其中 telemetry service 的 `src/index.ts` 也已展开，但不含本版代码节选，故不计入上表。

## 引用方法与边界

代码块中的内容保留原始语言、变量与注释。外层笔记重新组织顺序、选择片段并附中文解释；不声称每段都能单独编译。每段的定位范围可以略宽于实际代码块，联网核验会返回实际起止行。

自动比对只规范 CRLF/LF，不忽略缩进或代码改写。行号范围以固定提交文件为准，不是连接器外层 JSON 的行号。联网失败不得标记一致性通过。

源码、注释和设计文档可能不同步，差异见 [ERRATA.md](ERRATA.md)。未经读取的实现不补成事实；架构分析与实验假设放在代码块外。版权归属与许可证副本见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
