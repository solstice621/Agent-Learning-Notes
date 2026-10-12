# Codex 01｜执行循环：输入接纳与请求快照

你让 Codex 修改 A 文件。它已经开始查代码，你又补了一句：“先别改 A，改 B。”界面收到了消息，但刚才发给模型的请求不会随之改写，已经执行的工具也不会自动撤销。

**Codex 把新要求先接住，再在准备后续模型请求时纳入；每次请求使用自己的一套模型和工具信息。**

先把三个名字对上：`Session` 管这个会话的历史和服务；`Turn` 是一轮持续处理用户任务的工作；一轮里可以多次问模型，每次请求对应一个 `StepContext`。正常路线是：接收输入 → 请求模型 → 执行工具 → 记录结果 → 再问模型。`codex-core` 承担这段业务逻辑，界面和 app-server 负责把请求送进来、把事件展示出去。

<!-- decision: C01-D1 | 新消息到了，为什么不立刻塞进正在执行的请求？ -->
## 运行中输入的排队与消费

运行中的补充输入先确认有可接收的活动 Turn；指定了预期 Turn ID 时，还要核对 ID。这样可以拒绝发给过期轮次的定向纠正。通过检查后，消息才进入待处理队列。接收成功说明消息进了队列，尚不等于模型已经读到。

`run_turn` 在循环开头决定是否取出这些消息：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L429-L436 -->
```rust
        // 笔记：只有允许接纳新输入的采样边界才取队列；取出后还要记录历史，模型才会看到。
        let pending_input = if can_drain_pending_input {
            sess.input_queue
                .get_pending_input(&sess.active_turn)
                .await
                .0
        } else {
            Vec::new()
        // 笔记：暂缓消费不等于丢弃消息；它仍留在队列中等待后续请求。
        };
```

取出的消息会经过输入 hooks、写入历史，随后才构造模型请求。第一次采样要先处理启动本轮的原始输入；压缩刚结束、还有模型或工具工作需要续接时，也可能暂缓读取队列。这些规则是在给新旧工作安排次序。[查看接纳与请求构造](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L418-L541)。

这里也不是“永远等当前请求自然结束”。启用 `InstantInterrupt` 时，新输入能触发当前采样的抢占路径，再安排后续请求；具体会视传输能力发送中断信号、排空响应或停止读取，再处理已有结果。无论走哪条路，新消息都不能倒流进已经发出的请求。[查看抢占处理](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L2627-L2655)。

<!-- decision: C01-D2 | 工具配置变了，为什么当前请求还保留旧版本？ -->
## StepContext：工具路由快照与动态权限

假设模型看到的工具参数是 `path`，等待回复期间插件更新，把它改成了 `file`。如果执行器直接查最新注册表，模型按旧说明发出的合法调用就可能失败。

因此，准备请求时捕获的 `StepContext` 同时持有模型设置、环境和工具路由。工具执行器继续保留这一份对象：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L45-L52 -->
```rust
#[derive(Clone)]
pub(crate) struct ToolCallRuntime {
    // 笔记：共享 Session 让异步工具能回写会话；并不为每个工具复制一份会话。
    session: Arc<Session>,
    // Tool calls may run later, so retain the step whose tool list advertised them.
    // 笔记：工具保留公布它时的 Step，防止等待期间工具目录更新后执行依据错位。
    step_context: Arc<StepContext>,
    tracker: SharedTurnDiffTracker,
    // 笔记：该锁由这一工具运行时及其克隆共享，用来区分可重叠与独占调用。
    parallel_execution: Arc<RwLock<()>>,
}
```

这里的 `Arc` 可以理解为“共享持有这份对象”。请求公布的工具和后来执行的工具由同一份路由连接起来；下一次请求再捕获新设置。[查看捕获过程](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L3865-L3989)。

但并非一切都被冻住。`StepContext.environments()` 仍会读取所属 Turn 的当前权限授予。模型看到的能力说明与执行时的许可各有职责，不能把“保留旧工具表”理解为“旧权限永久有效”。[查看权限读取](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/step_context.rs#L62-L73)。

这样做的代价是多了队列和对象生命周期：新要求可能需要等待，慢工具也会继续持有旧上下文。如果你的 Agent 只做短批处理、提交后输入和配置都不变，一个串行循环就能更容易地说明白。

## 自测

新插件刚安装好，正在返回的模型调用会自动切到它的新参数格式吗？

<details>
<summary>参考答案</summary>

不会。当前调用来自此前公布的工具表，继续使用对应 Step 的路由；后续请求捕获新工具信息后，模型才有机会按新格式调用。补充输入也不是撤销旧工具效果的机制。

</details>

证据与局限：以上来自固定版本的调用链；另读了[错误 Turn ID 的拒绝测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input_tests.rs#L877-L917)。本轮没有运行上游测试，示例中的 A/B 文件只是帮助理解的场景。
