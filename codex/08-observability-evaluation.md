# Codex 08｜Observability / Evaluation：观测边界与确定性测试

[总目录](../README.md) · P2（学习顺序） · 对照：[OpenCode](../opencode/08-observability-evaluation.md) / [DSH](../dsh/08-observability-evaluation.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。下面展示实际观测调用点和上游测试原文；读到测试不等于本轮执行通过。

## 1. 本篇研究问题

为何看到一个最终回答不足以解释任务？模型传输、工具等待、handler 执行、结果准备和下一次请求是不同阶段。测试还应尽量固定模型行为，才能把 Harness 的问题与模型随机性分开。

## 2. 核心源码 A：为工具执行建立关联上下文

源码：[`tools/parallel.rs`，L190–L285](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L190-L285)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L190-L285 -->
```rust
        // Code-mode callbacks can resume outside the turn's local span ancestry.
        let dispatch_span = trace_span!(
            "dispatch_tool_call_with_code_mode_result",
            otel.name = %call.tool_name,
            tool_name = %call.tool_name,
            thread.id = %session.thread_id,
            call_id = call.call_id.as_str(),
            aborted = false,
        );
        let abort_dispatch_span = dispatch_span.clone();
```

注释指出 Code Mode 的回调可能在原 Turn 的 span 继承链之外恢复，所以这里显式建立 dispatch span。thread 与 call 的关联使调查者能把同名工具的不同调用区分开。

`aborted` 初始为 false，后续取消路径可以记录 true；clone 保留同一观测对象的句柄。**不要误读：** trace 字段不是授权事实，`call_id` 也不直接成为低基数指标标签；指标聚合与原始 trace 的数据模型应分开。

## 3. 核心源码 B：result-ready 早于采样循环最终收集

同一源码范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L190-L285 -->
```rust
                // The sampling loop collects results in order only after its stream ends.
                // Record readiness here, before either caller encodes or collects the result.
                // A fatal error still propagates to the caller instead of producing a tool
                // result; unlike a normal tool failure, it has no readiness event.
                if !matches!(&result, Err(FunctionCallError::Fatal(_))) {
                    call_trace::result_ready(
                        thread_id,
                        &turn.sub_id,
                        &dispatch_tool_name,
                        &dispatch_call_id,
                        trace_source,
                    );
                }
```

handler 的结果就绪和结果被下一模型请求使用不是同一时刻。这里在编码/收集前记录 readiness，帮助区分“工具本身慢”和“工具已经好了，系统仍等待其他工作”。

Fatal 不发这个 ready 事件，直接传播。这意味着缺少 ready 可能来自特定异常路径，不能直接当成工具仍在运行；诊断应结合其他事件和失败记录。

[Rollout Trace 文档](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/README.md) 进一步将原始运行证据与离线语义图分开，并说明本地 trace 是 best-effort。因此它不是业务恢复日志的替代品。

## 4. 核心源码 C：用 barrier 验证真实并发

源码：[`tests/suite/tool_parallelism.rs`，L93–L177](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/tool_parallelism.rs#L93-L177)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/tool_parallelism.rs#L93-L177 -->
```rust
    let parallel_args = json!({
        "sleep_after_ms": 300,
        "barrier": {
            "id": "parallel-test-sync",
            "participants": 2,
            "timeout_ms": 1_000,
        }
    })
    .to_string();
```

同一测试让 mock 模型发出两个参数相同的调用：

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/tool_parallelism.rs#L93-L177 -->
```rust
    let first_response = sse(vec![
        json!({"type": "response.created", "response": {"id": "resp-1"}}),
        ev_function_call("call-1", "test_sync_tool", &parallel_args),
        ev_function_call("call-2", "test_sync_tool", &parallel_args),
        ev_completed("resp-1"),
    ]);
```

### 逐段讲解

同一个 barrier 需要两个参与者。如果严格串行地等第一个调用完成才启动第二个，第一个就无法及时越过屏障。它比“总耗时看起来较短”更直接地约束调用确实重叠。

mock SSE 固定模型输出，避免真实模型偶尔只发一个调用导致测试不再测同一件事。此测试还包含 warmup 和耗时断言；测试阈值不是线上延迟保证，skip 条件也不能当作通过。

**设计分析：** 正确性测试先检查同步关系，性能实验再测延迟分布；不要拿一条 CI 时间阈值宣称整体 Agent 吞吐提高。

## 5. 待运行练习

先运行并确认该测试没有被跳过，再增加受控的 exclusive 调用或取消。对同一调用记录等待、执行、ready、最终入历史四个时刻，并分别关联模型请求。

单独评估任务正确性、传输重试成本、压缩成本和工具开销；不能只统计最后一个 response 的 usage。原始 trace 可能含 Prompt、工具结果与路径，只在本地合成项目使用，不上传到公开仓库。

## 6. 验收

交付一份失败复盘：哪些是观察到的事实，哪些是从缺失事件推测的，哪些证据仍需要补齐。能解释 result-ready 为什么不等于模型已见结果，以及 barrier 测试为什么比单纯 sleep 更能证明并发关系。

原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
