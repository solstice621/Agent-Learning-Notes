# 源码地图与摘录索引

[总目录](README.md) · [实际阅读记录](research/reread/README.md) · [版本锁](source-lock.json)

先读 [Codex 整体架构](codex/00-architecture.md)、[OpenCode 整体架构](opencode/00-architecture.md) 或 [DSH 整体架构](dsh/00-architecture.md)，再按下表查找专题摘录。表格覆盖 24 篇专题选择的原码位置，不是全部阅读文件清单；架构篇的调用链证据另在各篇就近列出。完整阅读路径见[重读记录](research/reread/README.md)。

## codex

架构入口：[执行内核说明](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/README.md)。固定版本 `a9b0815167c27ab13719dd12d13b63e02b70d221`。

| 摘录文件 | 定位范围 | 主笔记 |
|---|---|---|
| `codex-rs/app-server/src/request_processors/daemon_continuation.rs` | [L74–L87](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_continuation.rs#L74-L87) | [07](codex/07-persistence-reliability.md) |
| `codex-rs/app-server/src/request_processors/daemon_snapshot.rs` | [L30–L40](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_snapshot.rs#L30-L40) | [07](codex/07-persistence-reliability.md) |
| `codex-rs/app-server/src/turn_admission.rs` | [L52–L62](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/turn_admission.rs#L52-L62) | [05](codex/05-extension-architecture.md) |
| `codex-rs/core/src/agent/control/api.rs` | [L112–L120](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/api.rs#L112-L120) | [06](codex/06-task-orchestration.md) |
| `codex-rs/core/src/agent/control/spawn.rs` | [L326–L338](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L326-L338) | [06](codex/06-task-orchestration.md) |
| `codex-rs/core/src/client.rs` | [L669–L681](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L669-L681)、[L1486–L1500](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1486-L1500) | [04](codex/04-llm-streaming.md) |
| `codex-rs/core/src/compact.rs` | [L86–L95](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L86-L95) | [02](codex/02-context-session.md) |
| `codex-rs/core/src/session/mod.rs` | [L4213–L4226](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4213-L4226) | [02](codex/02-context-session.md) |
| `codex-rs/core/src/session/turn.rs` | [L429–L436](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L429-L436) | [01](codex/01-agent-loop.md) |
| `codex-rs/core/src/tools/parallel.rs` | [L45–L52](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L45-L52)、[L213–L224](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L213-L224)、[L260–L272](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L260-L272) | [01](codex/01-agent-loop.md)、[03](codex/03-tools-sandbox.md) |
| `codex-rs/ext/extension-api/src/registry.rs` | [L112–L125](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L112-L125) | [05](codex/05-extension-architecture.md) |
| `codex-rs/rollout-trace/src/thread.rs` | [L106–L118](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/thread.rs#L106-L118) | [08](codex/08-observability-evaluation.md) |
| `codex-rs/rollout-trace/src/writer.rs` | [L91–L105](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/writer.rs#L91-L105) | [08](codex/08-observability-evaluation.md) |

完整阅读范围：[01–04](research/reread/codex-01-04.md)、[05–08](research/reread/codex-05-08.md)。

## opencode

架构入口：[V2 模块分工](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/README.md)。固定版本 `60a212c0769acd96b446acbadeb790486830f91d`。

| 摘录文件 | 定位范围 | 主笔记 |
|---|---|---|
| `packages/core/src/plugin/supervisor.ts` | [L79–L90](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/plugin/supervisor.ts#L79-L90) | [05](opencode/05-extension-architecture.md) |
| `packages/core/src/session/execution.ts` | [L76–L86](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L76-L86)、[L128–L136](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L128-L136) | [07](opencode/07-persistence-reliability.md) |
| `packages/core/src/session/history.ts` | [L83–L95](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/history.ts#L83-L95) | [02](opencode/02-context-session.md) |
| `packages/core/src/session/run-coordinator.ts` | [L136–L145](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L136-L145) | [01](opencode/01-agent-loop.md) |
| `packages/core/src/session/runner/llm.ts` | [L165–L173](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L173)、[L206–L217](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L206-L217)、[L278–L286](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L278-L286) | [01](opencode/01-agent-loop.md)、[02](opencode/02-context-session.md)、[04](opencode/04-llm-streaming.md) |
| `packages/core/src/session/runner/publish-llm-event.ts` | [L586–L595](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/publish-llm-event.ts#L586-L595) | [03](opencode/03-tools-sandbox.md) |
| `packages/core/src/session/runner/retry.ts` | [L78–L90](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/retry.ts#L78-L90) | [04](opencode/04-llm-streaming.md) |
| `packages/core/src/session/runner/step.ts` | [L204–L209](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L204-L209) | [04](opencode/04-llm-streaming.md) |
| `packages/core/src/state.ts` | [L172–L184](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/state.ts#L172-L184) | [05](opencode/05-extension-architecture.md) |
| `packages/core/src/tool.ts` | [L225–L235](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool.ts#L225-L235) | [03](opencode/03-tools-sandbox.md) |
| `packages/core/src/tool/plugin/subagent.ts` | [L203–L213](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L203-L213)、[L234–L244](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/tool/plugin/subagent.ts#L234-L244) | [06](opencode/06-task-orchestration.md) |
| `packages/server/src/event-feed.ts` | [L48–L54](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L48-L54)、[L63–L68](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L63-L68) | [08](opencode/08-observability-evaluation.md) |

完整阅读范围：[01–04](research/reread/opencode-01-04.md)、[05–08](research/reread/opencode-05-08.md)。

## dsh

架构入口：[插件装配与执行流程](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/architecture.md)。固定版本 `d743267388641bc76f17c45ce8b4c231aed1d32c`。

| 摘录文件 | 定位范围 | 主笔记 |
|---|---|---|
| `packages/core/agent-loop/src/agent.ts` | [L163–L173](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L163-L173)、[L318–L328](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/agent.ts#L318-L328) | [01](dsh/01-agent-loop.md) |
| `packages/core/agent-loop/src/assistant-stream.ts` | [L83–L96](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/assistant-stream.ts#L83-L96) | [04](dsh/04-llm-streaming.md) |
| `packages/core/agent-loop/src/index.ts` | [L189–L198](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L189-L198)、[L876–L883](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L876-L883) | [05](dsh/05-extension-architecture.md)、[07](dsh/07-persistence-reliability.md) |
| `packages/core/agent-loop/src/tool-calls.ts` | [L148–L159](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L148-L159)、[L199–L209](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L199-L209) | [03](dsh/03-tools-sandbox.md) |
| `packages/core/session/src/index.ts` | [L993–L1004](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L993-L1004) | [02](dsh/02-context-session.md) |
| `packages/core/session/src/surface.ts` | [L567–L576](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/surface.ts#L567-L576) | [02](dsh/02-context-session.md) |
| `packages/fs/tool-fs/src/read.ts` | [L137–L147](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/fs/tool-fs/src/read.ts#L137-L147) | [05](dsh/05-extension-architecture.md) |
| `packages/goal/goal-round-driver/src/index.ts` | [L142–L154](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L142-L154)、[L264–L270](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/goal/goal-round-driver/src/index.ts#L264-L270) | [06](dsh/06-task-orchestration.md) |
| `packages/llm/llm-deepseek/src/adapter.ts` | [L43–L49](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/llm/llm-deepseek/src/adapter.ts#L43-L49) | [04](dsh/04-llm-streaming.md) |
| `packages/session/session-checkpoint-policy/src/index.ts` | [L70–L75](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L70-L75) | [07](dsh/07-persistence-reliability.md) |
| `packages/session/session-telemetry/src/coordinator.ts` | [L183–L194](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L183-L194)、[L209–L213](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-telemetry/src/coordinator.ts#L209-L213) | [08](dsh/08-observability-evaluation.md) |

完整阅读范围：[01–04](research/reread/dsh-01-04.md)、[05–08](research/reread/dsh-05-08.md)。

## 怎样核验

每段代码前的 `source` 或 `annotated-source` 标记包含完整提交与行号。原文块只规范换行；注解块额外去掉独立的 `// 笔记：` 注释行。其他代码、缩进与上游注释仍须一致，不把改写后的伪代码当作原文。默认联网读取固定文件；也可使用已下载且带版本标记的源码目录进行本地比对，报告区分两种模式。

阅读上游测试不等于运行通过；片段匹配不等于所有解释正确。方法见 [证据说明](RESEARCH_METHOD.md)，许可见 [第三方声明](THIRD_PARTY_NOTICES.md)。
