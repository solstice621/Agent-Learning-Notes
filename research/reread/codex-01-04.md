# Codex 01–04 源码重读记录

研究日期：2026-10-12。固定版本：`a9b0815167c27ab13719dd12d13b63e02b70d221`。本记录用于复核通俗笔记中的结论，不是动态运行报告。

已获取完整上游源码树，实际沿入口、调用者、核心函数、被调模块及相关测试阅读。未执行上游构建、模型请求、集成测试或故障注入。正文的 8 段代码已逐行与该源码树比较，一致；每段附固定 SHA、文件和精确行号。

## 整体架构定位

- [仓库 README](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/README.md#L1-L8)：确认研究对象是本地编码 Agent。
- [codex-core README](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/README.md#L1-L3)：core 实现业务逻辑，供多种 Rust UI 使用。
- [exec 入口对 app-server 协议类型的依赖](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/exec/src/lib.rs#L19-L59)与 [app-server 请求分发](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/message_processor.rs#L1643-L1660)：用户请求通过应用协议进入 turn processor；不是每一种 UI 自己实现一套模型循环。
- [turn processor 提交输入](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/request_processors/turn_processor.rs#L661-L688) → [core 的 start_or_steer](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L328-L386) → [RegularTask 调用执行循环](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tasks/regular.rs#L101-L124)。
- [采样请求创建工具执行器](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1604-L1684)：模型、工具、历史由核心循环衔接。四篇分别切入输入与视图、历史压缩、工具执行、模型传输。

## 01：C01-D1 与 C01-D2

原问题：输入接纳为何独立于运行中的请求；为何捕获 StepContext。

### 实际阅读链

1. 输入入口：上面的 app-server 与 RegularTask 调用链；并读 [定向 steer](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L634-L687)及 [steer_input 接纳实现](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L803-L896)。
2. 循环处理：[待处理输入、捕获视图、构造请求](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L418-L541)；[请求后决定继续和压缩](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L545-L655)。
3. 视图构造：[捕获模型与环境、构造工具路由](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L3858-L4024)；[StepContext 字段与权限读取](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/step_context.rs#L23-L73)。
4. 下游使用：[工具执行器保留原 Step](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L45-L65)、[用 Step 构造采样和工具执行器](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1604-L1684)。
5. 运行中输入：[监听队列触发 preempt](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1613-L1621)；[响应流处理抢占](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L2627-L2655)。
6. 已读测试：[steer_only_enforces_expected_turn_id](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input_tests.rs#L877-L917)；[指令刷新等待与取消](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/step_activation_tests.rs#L103-L158)。前者断言旧 Turn ID 被拒绝，后者检查取消能释放刷新守卫；不能拿后者声称已经动态验证所有配置快照。

### 确认与纠正

- 确认 C01-D1：接纳队列、写历史、形成请求是不同位置；初始输入优先于运行中追加输入，压缩后的续接也可能推迟队列读取。
- 收窄旧稿：不能概括成“输入只能等完整 Step 自然完成”。`InstantInterrupt` 打开时存在抢占路径；不同传输分支会中断、排空或丢弃当前流，再继续处理。抢占不等于回滚已执行效果。
- 补充入口差异：显式 `steer` 带预期 Turn ID；`start_or_steer` 调用同一 helper 时未提供预期 ID。正文已限定为“指定预期 ID 时核对”，不声称所有输入都具有同样的过期投递检查。
- 确认 C01-D2：设置、环境、MCP binding、工具路由由 Step 捕获；工具 runtime 保留这份对象，避免模型依据与 handler 错位。
- 修正旧稿的泛化空间：这不是全状态不可变快照。`StepContext.environments()` 明确读取 originating Turn 的当前 grants；描述性视图与实时授予共存已有实际源码，而不只是迁移建议。

### 证据边界

以上为静态调用关系及测试断言阅读。未测运行中输入的实际时延，未运行配置热切换、权限撤销或慢工具实验。正文 A/B 文件和参数变化是解释场景。

## 02：C02-D1 与 C02-D2

原问题：为何摘要之后仍需重建历史；为何活动历史和持久化历史共用稳定身份。

### 实际阅读链

1. 调用者：[run_auto_compact 的分支选择](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1435-L1508)；包括 TokenBudget、remote V2 和本地 Responses 摘要路径。
2. 本地摘要入口：[run_inline_auto_compact_task 与 run_compact_task](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L113-L170) → [本地压缩请求准备](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L259-L300) → [获得摘要后重建并替换历史](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L370-L425)。
3. 摘要以外的部分：[build_compaction_replacement_history 与 assemble_compaction_history](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L79-L111)；[WorldState 所包含的模块](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/context/world_state/mod.rs#L1-L68)；[按 Step 构造模型、工具与指令信息](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/world_state.rs#L59-L205)；[生成初始上下文](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4351-L4425)。
4. 保留策略：[近期用户消息的限额保留、裁剪与摘要追加](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L690-L769)。
5. 存档：[补齐 ID、保留并发目标更新、替换活动历史并持久化](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4157-L4265)。
6. 已读测试：[重建与活动历史一致](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/tests.rs#L2414-L2495)；[检查点保存目标变更及伴随恢复记录](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/tests.rs#L6165-L6285)；[中途压缩采用刷新后的全局指令](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/compact.rs#L5685-L5754)。

### 确认与纠正

- 确认 C02-D1：程序在摘要之后重建 WorldState 和初始上下文；“缩短历史”不是把一段摘要简单追加到原列表。
- 增加具体保留行为：本地实现从最近用户消息倒序选取，在预算内保留或裁剪文字，再恢复原顺序并加摘要。没有证据支持“全部早期约束都一定保留”。
- 收窄适用范围：不能将 `compact.rs` 的具体摘要算法写成所有 provider 的统一行为；主循环存在远端 V2 与 TokenBudget 分支。正文明确只沿本地摘要路径说明内容组织。
- 确认 C02-D2：ID 在克隆、活动替换与持久化记录构造之前分配；同一份 replacement history 同时进入 live 和 CompactedItem。
- 补充旧稿没有展开的真实竞争：压缩输入取快照后接受的目标修改，通过消息 ID 识别并追加到替换历史，避免旧摘要覆盖新目标更新。相关测试断言 `Clear` 留在 live 历史，同时检查持久化内容等于 live。
- 不夸大存档保证：内存替换先发生，随后才调用 `persist_rollout_items`；稳定 ID 与内容一致不构成内存/磁盘原子提交。

### 证据边界

测试只阅读未运行；未评估摘要语义保真、token 节省、崩溃恢复窗口。正文的成本与简单窗口比较是工程推导，不是性能测量。

## 03：C03-D1 与 C03-D2

原问题：为何取消后有些任务仍需要等待；为何批准、并发调度与隔离分别实现。

### 实际阅读链

1. 调用者：[采样请求创建 ToolCallRuntime](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1624-L1633)；[按序收集直接调用结果并记录历史](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L2462-L2489)；[采样结束时排空工具及检查取消](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L3159-L3179)。
2. 调度核心：[ToolCallRuntime 的状态与共享锁](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L45-L65)；[读取工具并行/取消属性](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L140-L153)；[可取消的准备、执行门、dispatch 与取消分支](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L202-L295)。
3. handler：[DynamicToolHandler 的 finishes_on_cancellation 声明及等待/终态发布](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/handlers/dynamic.rs#L172-L273)。
4. 结算：[PostToolUse 仍可取消](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/registry.rs#L825-L859)；[终态通知的单次认领](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/registry.rs#L899-L909)。
5. shell 的下游：[unified_exec 创建审批需求与调用 Orchestrator](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/unified_exec/process_manager.rs#L1462-L1545)；[审批与沙箱策略](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L127-L235)；[限制沙箱重试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L401-L453)。
6. 架构下层：[exec-server 的进程/文件及协议职责](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/exec-server/README.md#L1-L35)；[core 的平台沙箱说明](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/README.md#L21-L63)。
7. 已读测试：[完成后取消仍保留 Completed](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L801-L877)；[中断动态工具与 blocked hook](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/dynamic_tool_cancellation.rs#L90-L167)；[cell 终止后的迟到回复排除及持久化唯一完成](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/dynamic_tool_cancellation.rs#L170-L347)；[并行工具的同步障碍与时长断言](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/tool_parallelism.rs#L92-L151)。

### 确认与纠正

- 确认 C03-D1：`finishes_on_cancellation` 的 handler 会在取消后完成自己的收尾；一般分支 abort 后仍等待 join 并构造中止输出。已经到终态或 task 已完成时保留实际结果。
- 以实际源码取代正文依赖 PR 历史叙事：动态 handler 取消其 oneshot 等待，发出 Failed completion；这解释了为什么粗暴丢弃 future 会漏终态。正文不再要求读者先理解一条 PR。
- 限定迟到回复结论：直接引用 terminated Code Mode cell 场景的后续模型输入与 rollout 断言，不由一段 cancellation token 代码宣称整个系统所有结果都具备相同保证。
- 确认 C03-D2：并行标记通过共享/独占锁调度；审批和沙箱在需要这些机制的具体 runtime 路径中处理。
- 明确锁的范围：`parallel_execution` 是每个 `ToolCallRuntime::new` 创建的锁，经 runtime clone 共享。不是全 Session、全进程或全工作区互斥，也不能由“read lock”判断 handler 只读。
- 不外推 OS 行为：本轮没有核对子进程终止、进程组清理或业务补偿的完整保证。

### 证据边界

没有运行上述测试和外部进程实验。关于简单串行函数何时足够属于设计取舍，不声称优于上游实现。正文只保留对理解两项问题直接有用的机制。

## 04：C04-D1 与 C04-D2

原问题：为什么 Turn 路由不能跟整个 Session 走；为何历史变长仍不一定能增量续接。

### 实际阅读链

1. 上游模块自述：[ModelClient / ModelClientSession 的职责](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1-L26)；[会话状态、Turn 令牌与 WebsocketSession](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L198-L354)。
2. 调用者：[run_turn 获取本轮 client session](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L164-L187)；[采样请求使用 client_session.stream](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L2561-L2578)。
3. 生命周期：[new_session 接回缓存与重置路由令牌](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L665-L682)；[缓存领取、归还与 HTTP 降级](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L697-L733)；[Drop 归还 WebsocketSession](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1412-L1417)；[认证归属变化时重置](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1650-L1694)。
4. 增量判断：[显式请求属性比较](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L380-L450)；[条目比较中的元数据例外](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L453-L470)；[上一输入加上一输出形成基线](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L1468-L1532)。
5. 下游编码：[合法续接或完整发送分支及 ResponseCreateWsRequest](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client.rs#L2041-L2122)。
6. 已读测试：[跨 Turn 复用连接与 previous_response_id](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/client_websockets.rs#L1355-L1453)；[同一 Turn 的前缀增量](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/client_websockets.rs#L1963-L2012)；[工具实质元数据变化与普通元数据例外](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/client_tests.rs#L824-L960)。

### 确认与纠正

- 确认 C04-D1：`x-codex-turn-state` 的协议归属是 Turn，每次 new_session 新建 OnceLock；同一轮需要复用，不能带到新一轮。认证归属改变还会清掉旧状态。
- 重要修正：源码注释中“per-turn caches”不能覆盖实际缓存归还行为。WebsocketSession 被 `Drop` 存回 ModelClient，下一轮领取；因此连接、完整请求基线和 response ID 可以跨 Turn 保留，且有专门集成测试。正文明确区分路由令牌与续接缓存。
- 确认 C04-D2：续接基线是上一请求输入加服务器产生的输出，不是只有旧输入；完成前缀比较后才取剩余条目发送。
- 收窄“请求属性不变”的含义：比较显式列举 model/tools/tool_choice 等字段；client_metadata、stream_options、access_programs 不一概按全量 JSON 相等处理。条目忽略特定内部元数据，但实质工具结果元数据改变会使续接失效。
- 确认实现选择：HTTP fallback 属于会话状态，触发后本会话后续 Turn 继续 HTTP；未发现于所读路径中自动恢复 WebSocket 的承诺。

### 证据边界

未运行 mock WebSocket 服务、身份切换或断流测试；没有性能、token 成本或失败率测量。正文“完整发送更易排查”“复杂度是否值得”是工程推导。
