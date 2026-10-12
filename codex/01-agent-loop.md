# Codex 01｜Agent Loop：从输入接纳到下一次模型请求

[总目录](../README.md) · P0 · 对照：[OpenCode](../opencode/01-agent-loop.md) / [DSH](../dsh/01-agent-loop.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。下列 Rust 块均是连续的原文节选，保留原缩进；不是重新实现的伪代码，也不是可独立编译的完整程序。源码链接的行号范围包含对应节选。实验尚未运行。

## 1. 要解决的工程问题

用户发出一个任务以后，模型可能调用工具、等待工具结果，再请求模型。执行期间用户还可能追加消息。Loop 必须回答：什么时候接纳新输入、哪些配置属于本次请求、取消怎样传入下层。

本篇的主线是 `run_turn`。Session 是长期容器，Turn 是当前工作生命周期，StepContext 是一次请求使用的执行视图。不要把模型请求数、工具调用数和用户轮次数混成同一个计数。

## 2. 核心源码 A：到达的输入并不立即进入请求

源码位置：[`core/src/session/turn.rs`，L420–L560](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L420-L560)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L420-L560 -->
```rust
        let pending_input = if can_drain_pending_input {
            sess.input_queue
                .get_pending_input(&sess.active_turn)
                .await
                .0
        } else {
            Vec::new()
        };

        if run_hooks_and_record_inputs(
            &sess,
            &turn_context,
            &turn_context.capture_current_model_info(),
            &pending_input,
            PersistContext::SteeredUserInput,
        )
        .await
        {
            break;
        }
```

### 逐段讲解

`can_drain_pending_input` 是消费队列的条件，不是“是否有消息”。即使 UI 已经接到用户新输入，本次采样也可能暂不消费。源文件附近的注释给出两个延期场景：Turn 初始输入应先获得采样机会；自动压缩之后还有模型/工具后续工作要处理。

`get_pending_input(&sess.active_turn)` 表示取输入时仍绑定当前活动 Turn。这里不应猜测返回元组其他字段的语义；节选只使用 `.0`。真正要沿代码跟踪的是输入从队列到历史的接纳点。

`run_hooks_and_record_inputs` 把输入钩子与记录工作放在下一请求前。返回条件为真时停止本次循环，因此不是任何收到的文本都一定进入下一次模型调用。**从此调用点能证明顺序，不能单靠函数名证明已经 fsync。**

**思考反例：** 如果模型请求在接纳函数完成之前构造，用户已经提交的纠正意见可能不在模型输入中；如果重试时再次消费队列，则新输入可能在同一个逻辑步骤被提前提升。

## 3. 核心源码 B：先生成模型视图，再传递执行快照

同一文件、同一定位范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L420-L560 -->
```rust
            let sampling_request_input: Vec<ResponseItem> = async {
                sess.clone_history()
                    .await
                    .for_prompt(&step_context.settings.model_info.input_modalities)
            }
            .instrument(trace_span!("run_turn.prepare_sampling_request_input"))
            .await;

            run_sampling_request(
                Arc::clone(&sess),
                Arc::clone(&step_context),
                Arc::clone(&turn_context.extension_data),
                Arc::clone(&turn_diff_tracker),
                &mut client_session,
                sampling_request_input,
                cancellation_token.child_token(),
            )
            .await
```

### 逐段讲解

`clone_history()` 取得运行时历史，再由 `for_prompt(...)` 依据输入模态形成模型视图。因此持久化记录、运行时历史、实际请求是三个需要分别检查的层次，不应直接拿聊天记录替代请求。

这里的模态信息来自 `step_context.settings.model_info`；`run_sampling_request` 又收到同一个 `Arc<StepContext>`。源文件前面的捕获点明确要求上下文、声明给模型的工具和实际工具调用共享一次请求视图。**分析：** 这是一种请求级快照边界，用来避免声明时与执行时配置错位；不是跨机器配置一致性协议。

`&mut client_session` 使本 Turn 的传输状态可以在多次请求间更新；它与长期 Session 不是同一个对象。其内部路由状态详见 [04](04-llm-streaming.md)。

`child_token()` 给下层传入取消通道，但看到取消 token 不等于所有子进程已停止；下层仍需落实取消、清理和结果结算。工具侧见 [03](03-tools-sandbox.md)。

## 4. 把两段代码串起来

执行关系是：待处理输入 → 接纳/记录 → 捕获或沿用 StepContext → 历史转换为请求 → 采样与工具处理 → 检查是否还需继续。附近成功分支还会结合模型后续需求与新输入决定下一轮；并非看到一段 assistant 文本就必然结束。

| 状态或对象 | 本段的责任 | 不能据此推出 |
|---|---|---|
| input_queue | 缓冲执行期间输入 | 每次网络重试都应重新消费 |
| StepContext | 一次请求的设置与能力视图 | 所有状态都不可变或全局一致 |
| sampling_request_input | 当前真正的模型输入 | 等于完整持久化日志 |
| child cancellation token | 向下层传播取消 | 取消即回滚已发生的副作用 |

## 5. 可验证的练习

使用 mock 模型先返回一个可控制完成时刻的工具。在工具未完成时追加用户输入，然后释放工具，记录接纳函数完成、模型请求构造、工具结果进入历史的先后。分别测试正常工具完成、取消和压缩后的继续，不在真实业务目录制造故障。

验收应给出三个 Step 的时序表，并在每次请求旁标出模型看到的输入、持有的 StepContext 和取消状态。不要用“最后回答正确”替代输入顺序断言。

## 6. 学习要点

能说明为什么新消息到达与成为模型上下文不同；为什么 `for_prompt` 是重要转换点；为什么 Loop 传下去的是快照和取消通道，而不只是一个 Prompt 字符串。

**范围限制：** 本篇静态检查调用点和相关分支，没有运行上游测试，也未证明全部钩子、模型与平台组合的行为。Rust 原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
