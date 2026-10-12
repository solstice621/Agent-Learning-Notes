# Codex 03｜Tool / Sandbox：许可、执行门与取消结算

[总目录](../README.md) · P0 · 对照：[OpenCode](../opencode/03-tools-sandbox.md) / [DSH](../dsh/03-tools-sandbox.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。下面是运行时代码原文；未运行安全实验。审批、并发门与 OS 沙箱不是同一层。

## 1. 本篇的执行关系

ToolOrchestrator 负责审批及沙箱尝试；ToolCallRuntime 负责调度和取消；具体执行环境负责进程与文件系统效果。研究时分别问“能否执行”“什么时候执行”“在哪里执行”“取消之后谁收尾”。

## 2. 核心源码 A：需要审批时，拒绝会阻止后续路径

源码：[`tools/orchestrator.rs`，L173–L231](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L173-L231)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L173-L231 -->
```rust
            ExecApprovalRequirement::Forbidden { reason } => {
                return Err(ToolError::Rejected(reason.clone()));
            }
            ExecApprovalRequirement::NeedsApproval { reason, .. } => {
                let action = tool
                    .approval_action(req, &tool_ctx.call_id)
                    .map_err(|err| {
                        ToolError::Rejected(format!("could not prepare approval action: {err}"))
                    })?;
                let approval_ctx = ApprovalContext {
                    review_context: GuardianReviewContext::from(&tool_ctx.step_context),
                    cancellation_token: Some(tool_ctx.cancellation_token.clone()),
                    call_id: tool_ctx.call_id.clone(),
                    tool_name: tool_ctx.tool_name.clone(),
                    strict_auto_review,
                    approval_reason: reason.clone(),
                    retry_reason: None,
                    network_approval_context: None,
                };
                tool_ctx
                    .session
                    .request_approval(action, approval_ctx)
                    .await?;
                already_approved = true;
            }
```

### 逐段讲解

Forbidden 直接返回错误，不是向模型写一句警告后照常执行。NeedsApproval 先构造待批准 action，构造失败也以 Rejected 终止；审批自身的 `await?` 失败同样不会执行后面的成功赋值。

ApprovalContext 携带当前 Step 的 review context、调用 ID、工具名与取消通道，使批准针对具体动作，而不是一个与请求无关的全局按钮。`already_approved = true` 放在成功等待之后是一个状态推进点。

**不要过度推断：** 这里展示两个分支，不能推导所有工具都弹窗；同文件的 Skip 分支还受具体 review 策略影响。批准也不意味着选择了无隔离执行；沙箱选择发生在后面的独立步骤。

## 3. 核心源码 B：共享锁表达并发准入，不自动证明只读

源码：[`tools/parallel.rs`，L190–L285](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L190-L285)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L190-L285 -->
```rust
                let guard = async {
                    if let Some(tool_runtime) = tool_runtime
                        && let Some(readiness) = tool_runtime.wait_until_ready(&session)
                    {
                        readiness.await;
                    }

                    if supports_parallel {
                        Either::Left(lock.read().await)
                    } else {
                        Either::Right(lock.write().await)
                    }
                }
                .or_cancel_tool(&invocation_cancellation_token)
                .await?;
```

先等待工具就绪，再进入共享/独占门；整个等待仍接受取消。`supports_parallel` 决定拿读锁还是写锁，但锁类型不能证明工具业务没有副作用：这里的 read 是锁的共享模式，不是文件系统只读审计。

guard 在 handler 执行期间持有，并在调用完成后显式 drop。**分析：** 如果提前释放，exclusive 工具就可能与尚未结束的 handler 重叠；如果把取消仅加在 handler 内，等待锁的任务可能迟迟无法响应停止。

该门属于当前运行时调度范围，不是多节点任务锁，也不能限制不经这个入口执行的任意进程。

## 4. 核心源码 C：取消已经到达，仍可能需要等待结果

同一 `parallel.rs` 定位范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L190-L285 -->
```rust
                    if finishes_on_cancellation
                        || call_state.terminal_outcome_reached.load(Ordering::Acquire)
                        || dispatch_handle.is_finished()
                    {
                        dispatch_handle.await.map_err(Self::tool_task_join_error)?
                    } else {
                        let secs = started.elapsed().as_secs_f32().max(0.1);
                        abort_dispatch_span.record("aborted", true);
                        dispatch_handle.abort();
```

这是取消分支内部的原文，不是完整 if 语句。前三个条件分别关心 handler 的取消收尾契约、业务终态、异步任务是否已结束。满足任一条件就等待 join；否则走 abort，并在后续代码处理 join 结果。

`Ordering::Acquire` 参与终态标记的同步读取，但不能单凭这一个 load 证明整个内存顺序协议。要完整验证，必须继续追踪对应 store 和共享数据。

**关键结论：** cancel request、handler 停止、result settlement 是三个时刻。已经完成的副作用不会因为 task 被 abort 自动回滚。

## 5. Sandbox / Exec Server 的阅读边界

[Exec Server 文档](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/exec-server/README.md) 描述 RPC、PTY、远程连接与进程管理。`threadId/toolCallId` 的进程环境变量用于关联，不是不可伪造的授权令牌。本文不把传输重连等同于命令 exactly-once，也未证明某个 OS 后端的全部隔离能力。

## 6. 实验与验收

基于上游 [tool_parallelism.rs](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/tool_parallelism.rs)，用 gated 工具分别在等就绪、等锁、执行中和已完成时取消。核对开始/结束、guard 生命周期、结果事件与子进程，不把 UI 显示取消当作验收。

另用临时工作区区分审批拒绝、受限路径被阻止、执行后端不可用。不要关闭真实环境的所有审批来做测试。

应能说明为什么许可与并发分别建模、为什么读锁不证明只读、为什么取消后仍需 join。源码许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
