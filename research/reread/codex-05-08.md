# Codex 05–08 重新阅读记录

固定版本：`a9b0815167c27ab13719dd12d13b63e02b70d221`。研究对象为该版本的本地完整源码。正文以第一次阅读的理解顺序重写；本记录保留调用链、结论修订和验证范围。

验证状态：这四篇的上游测试均为**源码阅读，未运行**。未启动 Codex 服务、模型调用、崩溃注入或性能测量。正文中的场景用于解释机制，不冒充实际故障观测。

共同架构入口：
- [README.md:1-8](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/README.md#L1-L8)：确认本地编码 Agent 与 CLI、应用等入口关系。
- [codex-rs/core/README.md:1-3](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/README.md#L1-L3)：Core 是供不同 Rust UI 使用的业务逻辑。
- [codex-rs/app-server/src/lib.rs:986-1065](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/lib.rs#L986-L1065)：MessageProcessor 装配、恢复启动、关闭快照与主事件循环；作为 05/07 的宿主位置。

## 05：扩展装配与新工作接纳

旧问题：C05-D1 类型化贡献接口；C05-D2 输入消费前的执行准入。保留问题编号，但纠正 D2 的主解释。

已读证据链：
- [codex-rs/app-server/README.md:22-26](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/README.md#L22-L26)：宿主文档明确关闭时拒绝新工作。
- [codex-rs/app-server/src/extensions.rs:50-121](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/extensions.rs#L50-L121)：真实装配函数安装 queue、memory、MCP、Skills 等扩展，最后 build。
- [codex-rs/ext/extension-api/src/registry.rs:20-203](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L20-L203)：builder 与不可变注册表、不同职责接口、缺省允许的 admission。
- [codex-rs/core/src/session/mod.rs:4405-4437](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4405-L4437)：消费 ContextContributor 的具体位置，以及 prompt slot 如何决定片段去向。
- [codex-rs/ext/extension-api/src/turn_admission.rs:1-12](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/turn_admission.rs#L1-L12)：permit 贯穿提交；steering、mailbox、父任务委派的例外。
- [codex-rs/app-server/src/turn_admission.rs:11-82](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/turn_admission.rs#L11-L82)：closed 和 active；短锁同时保护接纳与关闭；Drop 释放提交计数。
- [codex-rs/core/src/session/turn_input.rs:340-451](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L340-L451)：先尝试 steering；启动分支索取 permit，然后应用配置、记录输入、spawn。
- [codex-rs/core/src/session/turn_input.rs:461-529](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L461-L529)：idle 启动检查，以及 review delegate 的明确例外。
- [codex-rs/app-server/src/lib.rs:255-275](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/lib.rs#L255-L275)：关闭信号调用 begin_drain。
- [codex-rs/app-server/src/lib.rs:1058-1065](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/lib.rs#L1058-L1065)：退出判断先观察提交数，再观察已运行轮数，防止漏掉正在发布的轮次。
- [codex-rs/ext/extension-api/tests/registry.rs:217-265](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/tests/registry.rs#L217-L265)：各类 contributor 经 build 后仍在对应名单，审批分派结果可检查。
- [codex-rs/app-server/src/turn_admission_tests.rs:6-28](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/turn_admission_tests.rs#L6-L28)：已接纳工作保留计数；关闭拒绝新工作；drop 两个 permit 后归零。
- [codex-rs/core/tests/suite/turn_input_submission.rs:221-268](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/turn_input_submission.rs#L221-L268)：mock 模型请求验证被拒输入没有进入后续请求。

确认与修订：

- 原文将 admission 主要讲成模型/执行容量不足；真实宿主实现是关闭排空。正文以关闭窗口为例，不再由 permit 类型推测未知资源配额实现。
- permit 生命周期保护的是准备/提交窗口，已运行轮次另行计数；没有写成持有到整轮完成。
- extension 是进程内类型化装配，不等于用户插件协议或 MCP 的统称；类型约束不提供进程沙箱。
- 将候选方案大表压成“万能回调、类型化入口、直接函数”三者的一段取舍。

未验证：实际关闭时序与写入失败注入未运行；不同扩展内部的共享状态安全未全面审计。

## 06：可继续子会话的身份、驻留与父归属

旧问题：C06-D1 持久身份与按需加载；C06-D2 当前父对象的归属校验。

已读证据链：
- [codex-rs/core/src/thread_manager.rs:2217-2225](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/thread_manager.rs#L2217-L2225)：根会话 resume 时调用元数据恢复。
- [codex-rs/core/src/agent/control/spawn.rs:190-274](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L190-L274)：读取持久 agent graph 的 open 后代关系与 stored thread metadata，仅恢复身份。
- [codex-rs/core/src/agent/control/api.rs:100-178](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/api.rs#L100-L178)：send 解析目标、按需加载，并持有 residency pin 到实际提交完成。
- [codex-rs/core/src/thread_manager.rs:1263-1295](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/thread_manager.rs#L1263-L1295)：通过已加载直接父会话恢复子任务的对外入口。
- [codex-rs/core/src/agent/control/api.rs:192-199](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/api.rs#L192-L199)：该入口转至 ensure_v2_agent_loaded(Some(parent))。
- [codex-rs/core/src/agent/control/spawn.rs:294-402](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L294-L402)：父对象与当前注册对象相等、运行状态、V2 和 registry；持久归属一致性。
- [codex-rs/core/src/agent/control/spawn.rs:403-561](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L403-L561)：当前父配置、角色配置保护、环境匹配、本地权限交集与远程变更拒绝。
- [codex-rs/core/src/agent/control/spawn.rs:599-668](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L599-L668)：预留驻留位置，重新加载历史，完成登记后发布对象；发送者取消不截断登记。
- [codex-rs/core/src/agent/control/residency.rs:34-101](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/residency.rs#L34-L101)：逐对象写锁排除发送，完成历史保存/停止再卸载，避免删除替代对象。
- [codex-rs/core/src/agent/control/residency.rs:156-173](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/residency.rs#L156-L173)：pin 是读锁，拿到锁后再次确认当前对象身份。
- [codex-rs/core/src/agent/control/residency.rs:176-263](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/residency.rs#L176-L263)：容量满时尝试卸载可选对象，失败明确报告 AgentLimitReached。
- [codex-rs/core/src/agent/control/residency.rs:304-326](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/residency.rs#L304-L326)：可卸载状态还受 active turn、durable sleep、trigger-turn mailbox 约束。
- [codex-rs/core/src/agent/control_tests.rs:1016-1024](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control_tests.rs#L1016-L1024)：发送者恢复与父驱动恢复两条测试入口。
- [codex-rs/core/src/agent/control_tests.rs:1276-1443](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control_tests.rs#L1276-L1443)：查看 Unloaded 不触发加载；重载保留模型/提供者和父环境；发送完成才释放 pin。
- [codex-rs/core/src/agent/control_tests.rs:1446-1571](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control_tests.rs#L1446-L1571)：恢复根会话不会立即重开所有后代 runtime；恢复身份仍可关闭指定子任务。
- [codex-rs/core/src/agent/control/spawn.rs:81-157](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L81-L157)：复核旧文上下文筛选与累计 token 不继承；为集中主线从正文移除。

确认与修订：

- “存在/加载/运行”分离得到真实读取、卸载、重载链支持；不虚构内存降低百分比。
- 完整父对象检查仅在 `parent: Some(...)` 分支发生；sender-driven reload 保留另一条路径。旧文若概括为所有加载都逐项检查父对象会过宽，正文补上条件。
- 以实际读锁/写锁解释 pin，而不只依赖函数注释。
- 权限行为具体到已读分支：缓存本地环境可做权限交集；缓存远程执行环境权限变化被拒绝。未泛化到整个产品所有恢复模式。

未验证：未执行运行时卸载竞争、迟到旧父操作或权限变更实验；未断言所有状态或无持久身份的 fixture 均可重载。

## 07：持久化确认与受管理的重启恢复

旧问题：C07-D1 分级持久化检查点；C07-D2 保守选择可恢复任务。

已读证据链：
- [codex-rs/thread-store/src/store.rs:68-94](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L68-L94)：各 PersistContext 与 allows_background_persistence 契约。
- [codex-rs/thread-store/src/store.rs:145-201](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L145-L201)：恢复历史、追加、persist、flush、shutdown、discard 的承诺差异。
- [codex-rs/thread-store/src/live_thread.rs:246-309](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/live_thread.rs#L246-L309)：Session-facing 包装如何追加、处理元数据与等待存储。
- [codex-rs/thread-store/src/local/mod.rs:544-566](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/local/mod.rs#L544-L566)：本地后端 SubagentSpawn 返回、ThreadPreparation flush、其他 persist 分支。
- [codex-rs/thread-store/src/local/live_writer.rs:327-383](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/local/live_writer.rs#L327-L383)：先确认 JSONL 写入，再更新可重建 SQLite 视图；普通 append 也等待 flush。
- [codex-rs/rollout/src/recorder.rs:1048-1101](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout/src/recorder.rs#L1048-L1101)：AddItems 排队与 Persist/Flush 等待 oneshot ACK 的区别。
- [codex-rs/rollout/src/recorder.rs:1816-1845](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout/src/recorder.rs#L1816-L1845)：writer 内部 flush/persist 路径及失败后重试。
- [codex-rs/rollout/src/recorder.rs:1908-1917](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout/src/recorder.rs#L1908-L1917)：文件 write/flush 的具体调用；不扩大为 fsync 保证。
- [codex-rs/core/src/session/turn.rs:438-451](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L438-L451)：输入处理完才写 RecordedTurnInput 标记。
- [codex-rs/core/src/session/daemon_recovery.rs:22-55](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/daemon_recovery.rs#L22-L55)：普通、未取消、有输入标记、单一本地环境、FromThread 的采集条件。
- [codex-rs/app-server/src/request_processors/daemon_snapshot.rs:15-54](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_snapshot.rs#L15-L54)：遍历持久根线程、取中断快照、Standard 持久化成功后才加入候选。
- [codex-rs/app-server/src/daemon_thread_recovery.rs:10-49](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/daemon_thread_recovery.rs#L10-L49)：写快照与启动时消费快照、后台恢复。
- [codex-rs/app-server/src/request_processors/daemon_continuation.rs:23-135](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/daemon_continuation.rs#L23-L135)：重新读历史、跳过完成/被替代、检查环境权限、关闭旧轮并尝试新 continuation。
- [codex-rs/rollout/src/recorder_tests.rs:991-1025](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout/src/recorder_tests.rs#L991-L1025)：写入失败后重开文件，flush 返回成功前能够读到排队内容。
- [codex-rs/app-server/tests/suite/v2/daemon_update_recovery.rs:462-738](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/tests/suite/v2/daemon_update_recovery.rs#L462-L738)：不同状态和配置的重启恢复用例；检查旧轮 interrupted、新轮 ID 不同。

确认与修订：

- 把“通用崩溃后原地恢复”的潜在印象改为“受管理关闭生成候选；重启后启动新一轮继续”。真正的突然退出可能来不及保存这份交接。
- Standard 是调用方等待边界；allow-background 是接口许可，不代表本地所有写都立即返回。
- 旧文说“应研究哪个是真源”，现已确认当前本地路径 JSONL 为 canonical，SQLite 是可重建 projection；更新后者失败记 warning。
- `RecordedTurnInput` 表示输入进入记录流程，不能独立代替后续持久化确认。
- 副作用后、结果记录前失败仍有不确定性；恢复提示要求重新查现场，不是完整 exactly-once 协议。

未验证：未运行 daemon 升级/重启测试、写入故障测试；未测断电持久性。所读底层路径只看到文件 flush，未据此声称稳定介质同步。

## 08：过程诊断与任务评估

旧问题：C08-D1 原始证据与离线解释；C08-D2 尽力诊断与可靠业务记录的不同承诺。

该主题另由协作研究者独立核对真实 writer/reducer/工具测试；正文作者复读 README、两个引用片段、reducer 顺序与延迟关联、工具结果分类及关联测试。

已读证据链：
- [codex-rs/rollout-trace/README.md:1-214](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/README.md#L1-L214)：整体架构、可选本地诊断、文件布局、证据与关系图的区分。
- [codex-rs/core/src/session/session.rs:1234-1270](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/session.rs#L1234-L1270)：Session 创建 trace context 的真实入口。
- [codex-rs/core/src/thread_manager.rs:2492-2519](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/thread_manager.rs#L2492-L2519)：新生子线程共享 writer，恢复子线程避免重复 ThreadStarted 的区别。
- [codex-rs/core/src/client.rs:1837-1852](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1837-L1852)：模型请求记录发生在 stream_request 之前。
- [codex-rs/core/src/client.rs:2532-2547](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L2532-L2547)：响应端记录。
- [codex-rs/core/src/tools/tool_dispatch_trace.rs:62-109](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/tool_dispatch_trace.rs#L62-L109)：Direct response_item 与 CodeMode value 的来源和输出类型。
- [codex-rs/core/src/session/mod.rs:2670-2688](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L2670-L2688)：产品 rollout 持久化和诊断 trace 不是同一次写调用。
- [codex-rs/rollout-trace/src/writer.rs:85-140](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/writer.rs#L85-L140)：payload 先写，事件分配 seq 与追加在同一把 Mutex 下。
- [codex-rs/rollout-trace/src/thread.rs:101-118](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/thread.rs#L101-L118)：启动失败 warning 并回退 Disabled。
- [codex-rs/rollout-trace/src/thread.rs:460-523](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/thread.rs#L460-L523)：payload/事件写失败不会向 Session 传播为 fatal error。
- [codex-rs/rollout-trace/src/inference.rs:169-196](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/inference.rs#L169-L196)：记录可为 logical request，不能当成恒为 exact wire capture。
- [codex-rs/rollout-trace/src/reducer/mod.rs:68-83](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/reducer/mod.rs#L68-L83)：按文件行读取 apply_event，没有按 seq 排序或单调性检查。
- [codex-rs/rollout-trace/src/reducer/mod.rs:113-128](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/reducer/mod.rs#L113-L128)：流结束记录响应之前，工具可能执行完；延后关联来源和生命周期。
- [codex-rs/rollout-trace/src/reducer/conversation.rs:28-190](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/reducer/conversation.rs#L28-L190)：从请求 input 和响应 output_items 形成模型侧对话记录。
- [codex-rs/core/src/tools/tool_dispatch_trace_tests.rs:118-207](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/tool_dispatch_trace_tests.rs#L118-L207)：实际 dispatch 后检查 Direct/CodeMode 输出与来源归属。
- [codex-rs/rollout-trace/src/reducer/conversation_tests.rs:1208-1301](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/reducer/conversation_tests.rs#L1208-L1301)：工具调用、返回、后续请求的 model-visible output item 建立关系。
- [codex-rs/rollout-trace/src/thread_tests.rs:112-165](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/thread_tests.rs#L112-L165)：Disabled 接口可调用且不构造 payload；不是磁盘故障恢复测试。
- [codex-rs/rollout-trace/src/writer.rs:170-263](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/src/writer.rs#L170-L263)：writer 写出 bundle 再 reducer 的基本结构测试。

确认与修订：

- “先观察后解释”的方向成立，但 reducer 实际逐行读取，不能写成自动按 seq 排序乱序输入。
- payload 在引用事件之前写文件的次序成立，不是跨文件事务或 fsync 承诺。
- 模型请求证据可为逻辑请求表示，不能声称已证明服务端实际接收每字节。
- 以终端输出、Code Mode 返回值、下一模型请求三个层次替代大段观察术语。
- 删除与本篇主线距离较远的并发性能与时序阈值段落，换用真实结果关联测试；补充环境/传递/模型判断/验收覆盖四类易懂归因。

未验证：未现场生成 bundle、模拟 trace writer 故障或重复 reduce；未运行任务质量评估。上游结构测试不等于完成了真实 bug 修复的验收。
