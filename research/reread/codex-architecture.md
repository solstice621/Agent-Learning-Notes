# Codex 整体架构与代码注释复核记录

研究日期：2026-10-12。固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。

本轮新增[整体架构篇](../../codex/00-architecture.md)，并为 `research/decisions/codex/01` 至 `08` 的全部 16 段源码摘录补充中文注释。目的在于让读者先学会追踪正常任务，再理解各专题中的取消、压缩、恢复等规则。现有 C01-D1 至 C08-D2 共 16 个问题保留。

## 研究方式与核验结果

实际重新阅读固定版本源码，从客户端入口一路跟到输入接纳、普通任务、模型流、工具调度、历史存储和客户端事件。下面是静态源码结论；没有运行上游 Rust 构建、测试、真实模型请求、沙箱实验或重启实验。

16 个原有摘录改用 `annotated-source` 标记；新增 56 行独立的 `// 笔记：` 注释，解释状态归属、条件分支、异步等待和操作后果。逐块移除这些新增行后，与每个固定源码行范围精确比较，16/16 一致。没有修改原始代码行，也没有把讲解代码当作上游实现。

架构正文包含 40 处固定源码行范围，涉及 27 个不同源码文件；已检查路径存在、行号有效、SHA 与 source-lock 一致，并逐项核对支撑关系。范围检查只证明引用可定位，不能替代正文结论的人工复核。架构篇的两张 Mermaid 图是据这些调用关系绘制的教学图，不是运行 trace。

## 正常任务的实际调用链

| 交接位置 | 实际阅读与可证明的职责 |
|---|---|
| 客户端模式 | [CLI 分发](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/cli/src/main.rs#L1095-L1188)选择交互界面或 exec；[exec 入口](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/exec/src/lib.rs#L1020-L1026)实际创建进程内 app-server client。 |
| 应用协议到核心 | [请求分发](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/message_processor.rs#L1643-L1660) → [turn processor 提交](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/turn_processor.rs#L661-L699) → [start_or_steer](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L328-L454)。空闲时启动普通任务，活动时可追加输入。 |
| 任务到采样循环 | [RegularTask](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tasks/regular.rs#L101-L126)调用 run_turn；[输入记录](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L365-L377)与[循环内请求构造](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L418-L541)分别确认历史及请求边界。 |
| Prompt 到模型流 | [Prompt 与 ToolCallRuntime 构造](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1624-L1684) → [ModelClientSession::stream](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L2561-L2580)。 |
| 模型输出到工具 | [handle_output_item_done](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/stream_events_utils.rs#L315-L357)识别并记录调用，再排入工具 future，同时设置 needs_follow_up；[工具运行时](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L127-L159)继续使用原 Step 路由。 |
| 命令执行 | [unified_exec](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/unified_exec/process_manager.rs#L1462-L1545)准备审批要求并调用 Orchestrator；[exec-server 边界](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/exec-server/README.md#L1-L15)确认其进程/文件职责。 |
| 结果与续接 | [drain_in_flight](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L2462-L2489)收集并记录直接工具结果；[继续条件](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L545-L579)合并模型续接要求和待处理输入。 |
| 最终收尾与通知 | [结束 hooks](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L657-L708)也能要求继续；[任务统一收尾](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tasks/mod.rs#L819-L885)产生终态；[宿主事件监听](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/thread_lifecycle.rs#L323-L389)与[完成协议通知](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/bespoke_event_handling.rs#L1330-L1353)连接核心到客户端。 |

## 状态、并发与持久化边界

- [CodexThread](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/codex_thread.rs#L208-L219)持有 Session 和 IO；[ThreadManager](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/thread_manager.rs#L250-L255)负责已加载对象。Thread 身份与当前内存对象不等同。
- [Session 字段](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/session.rs#L60-L100)持有活动 Turn 槽位、输入队列、状态和服务；[ActiveTurn / RunningTask / TurnState](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/state/turn.rs#L29-L111)进一步区分任务、取消令牌和等待项。
- [StepContext](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/step_context.rs#L23-L73)固定请求使用的工具和设置，同时访问所属 Turn 当前授予；[ModelClient 说明](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1-L26)确认业务会话与轮内通信对象的不同寿命。
- [工具共享锁](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L45-L65)属于该运行时及其 clone；[后台工作授权](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_context.rs#L377-L382)保留在原 Turn 上。单一 active_turn 不能推出整个系统全局串行。
- [活动历史先更新，随后调用保存](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L3710-L3741)；[保存失败](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4628-L4636)返回 false；[默认事件路径](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L2673-L2702)不能当作磁盘事务确认。
- [本地写入](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/local/live_writer.rs#L327-L383)先完成 JSONL 写入，再投影 SQLite。没有把文件 flush 扩写为断电后的硬件持久性保证。

## 扩展与子任务边界

- [宿主安装扩展](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/extensions.rs#L50-L121)与[按职责注册](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L112-L125)共同证明 ExtensionRegistry 是进程内装配点，不能与 MCP 协议或 Skills 混称。
- [恢复 V2 子任务元数据](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L190-L274)、[按需加载再发送](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/api.rs#L112-L120)、[卸载锁与停止流程](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/residency.rs#L34-L101)说明身份、驻留、运行三件事分开管理。
- [父对象校验](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L326-L338)只在提供 parent 的分支发生，不能泛化成所有消息发送都先执行这一组检查。

## 本轮修正与教学处理

1. 加入正常流程，而不只把原有异常专题重新列一遍。读配置的场景明确标为说明场景，不冒充一次真实执行。
2. 首轮 Step 准备可以早于用户输入记录；正文只保证输入记录后才形成包含它的请求，不把“记录输入 → 捕获 Step”写成所有轮次的唯一内部顺序。
3. 无工具续接、无新输入还不是完整结束条件；结束 hooks 也可要求继续。架构正文在完成路径补上该条件。
4. 分开讲模型输入条目、持久历史、客户端事件和诊断 trace。收到工具完成通知不等于后续模型已读到结果，更不等于任务验收通过。
5. 注释复审将“其他 handler 被中止”移动到真正的 abort 分支，避免贴在 await 分支误导读者；`try_admit` 拒绝后是否保留输入归调用方处理，不给出许可方法自身没有的保证。
6. 保留原有八篇专题和十六个问题；架构篇按执行、长任务和宿主能力安排阅读路径，统一为先 01 → 03 → 04，再读后续机制。

后续若改变固定源码版本，需要重新追踪以上交接点和各摘录；不能只替换链接中的 SHA。
