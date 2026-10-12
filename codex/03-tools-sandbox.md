# Codex 03｜为什么取消不能只是 abort，工具并发也不能只靠 Promise/Task？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 先还原一个有作者证据的真实问题

官方 PR #51556（2026-10-07 合并）明确说明：中断 Turn 或结束 Code Mode cell，可能在动态工具 handler 发布 completion 前将它丢弃；取消必须结算 live events 和持久历史，同时不能让迟到响应重新进入模型上下文。[A1] 这不是本笔记虚构的故障，而是本次补查得到的直接设计动机。

因此目标包含两个看似冲突的要求：**用户要及时停止工作；记录和资源又必须有明确终态。** “取消快”不能用“把 future 扔掉”简单替代。

## 2. 决策 C03-D1：为什么一部分任务取消后仍然等待？

当前 `parallel.rs` 对 `finishes_on_cancellation`、已到终态、task 已完成等情况继续 join，其他情况可以 abort；执行门前的 readiness 和锁等待仍可取消。[F1] PR 对应说明还要求 hooks 和输出处理保持可取消，避免一个阻塞 hook 拖住取消。[A1]

| 候选取消方案 | 优点 | 反例 |
|---|---|---|
| 立即丢弃所有任务 | UI 很快返回 | 工具已执行但没有终态；资源可能仍存活 |
| 对所有步骤禁止取消直到完成 | 结算容易串行推理 | 阻塞网络/审批使用户无法及时停止 |
| 工作可取消，特定终态必须收敛 | 区分执行与结算 | 需要按 handler 生命周期判断，不是统一包装器 |

**分析：** 理想的取消路径是停止新工作、撤回后续结果进入上下文的资格、通知活动工作、保留必要终态、释放资源。每一步都有自己的完成点。等到结算不代表继续授权原任务；迟到的结果可以作为诊断事实被处理，却不能悄悄恢复已取消的控制流。

必须反对另一种过度推导：加入 CancellationToken 不等于能杀掉所有 OS 子进程，更不等于回滚写文件或远程支付。线程/async task 终止、进程组终止与业务补偿必须分别测试。

## 3. 决策 C03-D2：为什么把批准、并发和隔离分开？

Orchestrator 决定 Forbidden、NeedsApproval 等路径和沙箱尝试；ToolCallRuntime 使用共享/独占执行门协调 overlap。[F1][F2] 它们回答的是不同问题：能不能执行、何时可以和其他调用重叠、即使工具实现有误它能接触哪些资源。

一个工具获得批准，不代表它可与另一个修改同文件的工具安全并发；一个工具被标记可并发，也不代表它只能读文件。**共享读锁是调度约定，不是自动证明 handler 无副作用。** 用单个全局锁能简化竞争，却牺牲所有独立读操作；完全并发能提高 overlap，却把正确性负担推到每个工具及工作区冲突管理。

当前方案允许分类调度，设计成本是必须相信并审查分类。未来若同一工作区出现资源级竞争，可以研究按文件/仓库/会话的冲突域调度；但锁粒度更细会增加死锁、资源命名和动态读写集合成本，不能把它当无条件升级。

Exec Server 将进程/文件操作与上层协议分离。[F3] 这提供测试和远程执行边界，但增加连接丢失、迟到输出、进程存活状态和版本协商问题。`CODEX_TOOL_CALL_ID` 一类环境变量适合归因，不是不可伪造的身份凭证；不要将 tracing 标识误当安全认证。

## 4. 沙箱重试为什么是高风险决策点？

如果沙箱导致命令失败，重试是否放宽权限必须由策略与审批路径决定；不能写成“失败后自动裸跑”。单纯非零退出码可能是命令错误、资源不可用或策略阻止，应先分类。[F2][F3]

**反事实：** 把所有失败都自动切为 unsandboxed，等于将保护机制的正常拒绝当作故障修复。反过来，把所有拒绝都报成模型无能，又会污染评测数据。安全拒绝、工具业务失败、运行时基础设施失败需要不同标签。

## 5. 验证与何时选择更简单实现

**上游实验待运行：** 复用 PR 描述的故障窗口：等待响应、执行门前、blocked hook、响应与取消竞争。断言唯一终态、无迟到模型输入、无泄漏任务，另在隔离环境检查子进程。上游测试的存在不等于本轮执行过它们。

若仅运行可信的固定函数、不会启动外部进程、任务很短且不需运行中取消，可以用串行执行先换取清晰语义。若是多租户不可信代码执行，当前局部锁/审批分析不足以决定安全，需要 OS/VM、网络、凭证和资源配额的完整威胁模型。

**本篇结论：** 成熟取消设计在“快速返回”与“真正停止/结算”之间建立协议；并发调度和安全隔离是并列约束，不是互相替代的功能开关。

[A1]: https://github.com/openai/codex/pull/51556
[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L130-L275
[F2]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/orchestrator.rs#L1-L270
[F3]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/exec-server/README.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：需要审批时，拒绝会阻止后续路径

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

#### 逐段讲解

Forbidden 直接返回错误，不是向模型写一句警告后照常执行。NeedsApproval 先构造待批准 action，构造失败也以 Rejected 终止；审批自身的 `await?` 失败同样不会执行后面的成功赋值。

ApprovalContext 携带当前 Step 的 review context、调用 ID、工具名与取消通道，使批准针对具体动作，而不是一个与请求无关的全局按钮。`already_approved = true` 放在成功等待之后是一个状态推进点。

**不要过度推断：** 这里展示两个分支，不能推导所有工具都弹窗；同文件的 Skip 分支还受具体 review 策略影响。批准也不意味着选择了无隔离执行；沙箱选择发生在后面的独立步骤。

### 3. 核心源码 B：共享锁表达并发准入，不自动证明只读

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

### 4. 核心源码 C：取消已经到达，仍可能需要等待结果

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



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/03-tools-sandbox.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
