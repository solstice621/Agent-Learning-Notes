# Codex 03｜工具执行：取消收尾与权限控制

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

模型调用了一个由宿主应用处理的动态工具。界面已经显示“执行中”，用户此时点了停止。如果立即丢掉等待工具返回的任务，界面和历史里可能永远只留下“执行中”，没有失败或完成记录。

**取消既要停止继续等待，也要让已开始的调用留下明确结果；哪些工具可以同时跑、允许跑什么，则由另外的规则负责。**

在整个执行链上，采样循环接到模型的工具调用后，交给 `ToolCallRuntime` 调度，再由路由找到 handler。普通模型直接发起的调用结果会由采样循环收集并写入历史，供下一次模型请求使用。

<!-- decision: C03-D1 | 取消后继续等待，是不是没有真正停止？ -->
## 取消后的工具结算

动态工具 handler 等宿主回复时也监听取消。收到取消后，它结束等待，生成失败条目，发出完成事件。它需要一小段继续运行的机会，才能把这件事办完。[查看动态工具的取消与完成](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/handlers/dynamic.rs#L235-L273)。

所以调度器没有统一执行 `abort`：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L260-L272 -->
```rust
            // 笔记：同时等待工具完成和取消信号；两者接近发生时，要保留已形成的真实终态。
            let mut result = tokio::select! {
                res = &mut dispatch_handle => res.map_err(Self::tool_task_join_error)?,
                _ = cancellation_token.cancelled() => {
                    // Dynamic handlers observe the token and publish their terminal item themselves.
                    // 笔记：自己负责取消收尾的 handler 获得继续运行的机会，才能发出最终失败或完成记录。
                    if finishes_on_cancellation
                        || call_state.terminal_outcome_reached.load(Ordering::Acquire)
                        || dispatch_handle.is_finished()
                    {
                        // 笔记：等待已完成或自行收尾的任务返回，保留其结果。
                        dispatch_handle.await.map_err(Self::tool_task_join_error)?
                    } else {
                        let secs = started.elapsed().as_secs_f32().max(0.1);
                        abort_dispatch_span.record("aborted", true);
                        // 笔记：其他仍未结束的 handler 才被中止；中止异步任务本身不会撤销外部副作用。
                        dispatch_handle.abort();
```

`finishes_on_cancellation` 表示 handler 自己会处理取消并完成收尾；已到终态或已完成的任务也继续等待其返回。其他任务可以中止，调度器随后生成中止结果。这样能避免“工具已经成功，恰巧此刻用户取消，于是成功被改写成失败”的竞争。

等待执行门或尚未准备好的工具仍然可以取消，前后 hooks 也有可取消路径。因此不能把这一规则理解为“从开始到结束都必须死等”。同样，结束 Rust 任务不会自动撤销已经写入的文件；外部进程是否停止，属于下层执行器的责任。

<!-- decision: C03-D2 | 获得批准的工具，为什么还不能随便并行？ -->
## 审批、并发控制与沙箱隔离

假设模型同时要求读两个文件，又要求修改文件。批准只回答“这次操作能不能做”，并不证明几个调用互相不会干扰。调度器还根据工具的并行声明，通过共享锁或独占锁进入执行：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L213-L224 -->
```rust
                    // 笔记：这里读取的是工具的并行声明，不是在判定命令是否只读文件。
                    if supports_parallel {
                        // 笔记：共享许可可被多个可并行调用持有。
                        Either::Left(lock.read().await)
                    } else {
                        // 笔记：独占许可需要等待其他持有者退出；锁守卫保留期间它才能独自执行。
                        Either::Right(lock.write().await)
                    }
                }
                // 笔记：排队等待许可也能响应取消，尚未进入 handler 的调用无需继续等锁。
                .or_cancel_tool(&invocation_cancellation_token)
                .await?;
                // Admission through the parallel-execution gate marks the end
                // of dispatch waiting and the start of handler execution.
                // 笔记：拿到许可后才记执行起点，避免把排队耗时算成 handler 的执行耗时。
                if let Some(execution_started_at) = execution_started_at {
                    let _ = execution_started_at.set(Instant::now());
```

共享锁允许多个声明可并行的调用重叠，独占锁需要单独进入。这里的“读锁”只是锁的名称，并不证明工具只读文件；分类是否合理，仍要由工具实现和注册配置保证。而且锁属于这一 `ToolCallRuntime`，不能据此推导整个工作区里的所有任务都互斥。

对 shell 等需要执行环境的工具，还会经过 `ToolOrchestrator`。三个检查可以这样区分：

| 检查 | 回答的问题 |
|---|---|
| 审批与策略 | 这次操作是否允许执行？ |
| 并发执行门 | 它何时能与其他调用重叠？ |
| 沙箱 | 执行时实际能访问哪些资源？ |

Orchestrator 根据策略批准或拒绝，选择沙箱，再调用具体 runtime。沙箱拒绝后的重试还有专门条件，并非命令一失败就脱离沙箱再跑。[查看审批](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L166-L235)与[重试限制](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L419-L453)。

这些规则换来了明确的中止记录和受控并发，代价是每个 handler 都要遵守生命周期约定。只执行短小、可信的固定函数时，可以先串行调用；加入运行中取消和外部工具后，再明确谁负责收尾。

## 自测

动态工具已记录取消，宿主随后才返回“成功”。这个迟到结果应该让原调用重新成功吗？

<details>
<summary>参考答案</summary>

不应该。原等待已经结束，晚到结果不能恢复已取消的执行。上游针对终止 Code Mode cell 的测试检查了后续模型请求不含迟到内容，并检查历史只有一次完成记录。

</details>

证据与局限：已读[迟到结果测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/dynamic_tool_cancellation.rs#L170-L347)和[完成后遇到取消的测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L801-L877)，本轮未执行；这些局部保证不等于对所有外部进程和副作用的回滚保证。

---

固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/codex-01-04.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
