# Codex 08｜为什么先保存运行证据，再离线解释，而不是边运行边生成一张万能图？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 先判断我们真正需要观察什么

聊天记录可以说明用户与模型交换了什么，但 Code Mode 内部工具调用、终端进程、子 Agent 消息和压缩边界可能不在同一个表示层。仅保存最终回答无法回答“哪次请求产生这次工具、模型是否真的看到完整结果”。

Rollout Trace 文档明确选择先记录原始事件与 payload references，再由离线 reducer 形成语义图；区分 model-visible ConversationItem 与 ToolCall、CodeCell、TerminalOperation 等运行时对象。[A1] 本篇据此研究两项边界，而不是主张日志越多越好。

## 2. 决策 C08-D1：为什么把解释移出热路径？

| 方案 | 收益 | 代价与故障面 |
|---|---|---|
| 只存最终转录 | 低存储与隐私暴露 | 缺少执行来源与失败细节 |
| 热路径直接更新完整语义图 | 查询即刻可用 | 运行时与图 schema 耦合；乱序关联增加热路径复杂度 |
| 原始证据＋离线 reducer | 解释逻辑可迭代、可重新归约 | 多一份 schema、归约时间与证据完整性检查 |
| 保存所有底层字节永久不删 | 可能覆盖更多调试需求 | 成本与敏感数据累积，查询语义仍没解决 |

官方文档给出了 Observe first/interpret later 的明确方向，并规定 payload 先于引用事件、原始事件按 seq 归约、运行时输出不能冒充模型可见输入。[A1] **推导：** reducer 修复后可重新解释原始证据，而不必重跑一个昂贵且可能非确定的模型任务；但如果原本没有记录相关事实，离线分析无法凭空补全。

这并非鼓励热路径做任何事情都“异步丢到日志”。writer 的开销、序列分配、payload 大小和失败行为仍需约束。把昂贵图构造移走，只是移除了部分工作。

## 3. 决策 C08-D2：为什么诊断记录不能同时充当可靠业务账本？

文档明确 trace 是可选的本地诊断，不是自动上传 telemetry，写入 best-effort，不应因为诊断故障让 Session 失败。[A1] 这意味着“没有 trace”不能证明工具没运行；“trace 记录完成”也不保证用于业务恢复的历史已经 durable。

**冲突分析：** 诊断通常希望任务在 sink 故障时继续；审计账本可能要求关键动作未记账便不执行；计费要求完整和去重；训练轨迹要求准确还原模型所见。它们可能共享事实来源，却不能无条件共享交付承诺。

如果法规或关键操作要求不可抵赖日志，需要明确 fail-closed 的审计通路与持久性协议。那是另一个执行约束，不能把当前 best-effort 开关改个名字就满足。对于个人本地使用，则不应默认为了调试把全部 Prompt、终端输出和路径上传。

## 4. 怎样评估 Harness，而不是误测模型能力？

工具并发测试使用 mock SSE 固定模型输出，再用 barrier 证明调用确实重叠。[F1] 它把模型随机性移出调度正确性问题。相关 timing guard 的提交还专门检查 direct 与 nested Code Mode 调用不会重复产生某项计时事件。[A2]

**设计推导：** 状态机正确性应使用确定性输入；模型任务质量另设任务集；吞吐、排队与费用也要分开。一个成功率变差可能来自模型决策、工具拒绝、环境故障、协议错误或评分器，不应全归到模型。把 nested call 和外层调用混算还可能双重计费或双重统计延迟。

测试中的时间阈值是带执行环境余量的断言，不是产品 SLO。屏障验证 overlap，也不证明并发提升了真实任务正确率。实际 benchmark 必须写出工作负载、缓存状态、模型配置、工具权限、失败/跳过数量和分位数。

## 5. 验证与何时简化

**上游实验待运行：** 在合成任务中开启本地 trace，沿一个工具查到请求、runtime output 与下一请求的 model-visible content；制造 writer 失败，确认与业务路径的承诺一致；同一 bundle 多次 reduce 检查结构一致。禁止公开上传含敏感信息的原始 bundle。

本轮机制实验只验证重复计数/交付与业务事实不能混同的抽象关系，不运行真实 Codex。若系统只有一个固定无工具调用，结构化日志已能定位全部问题，就没有必要立即搭完整语义图。

**读后判断：** 先确定要回答的因果问题，再决定证据、身份、持久性和隐私预算。可观察性不是给每个函数加一行日志，而是能够区分“看到了什么”“做了什么”“记录可靠到了哪里”。

[A1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/README.md
[A2]: https://github.com/openai/codex/commit/d4eed6dca57fc72298808aed5a4bfe43285bf98f
[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/tests/suite/tool_parallelism.rs#L1-L220

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：为工具执行建立关联上下文

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

### 3. 核心源码 B：result-ready 早于采样循环最终收集

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

### 4. 核心源码 C：用 barrier 验证真实并发

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

#### 逐段讲解

同一个 barrier 需要两个参与者。如果严格串行地等第一个调用完成才启动第二个，第一个就无法及时越过屏障。它比“总耗时看起来较短”更直接地约束调用确实重叠。

mock SSE 固定模型输出，避免真实模型偶尔只发一个调用导致测试不再测同一件事。此测试还包含 warmup 和耗时断言；测试阈值不是线上延迟保证，skip 条件也不能当作通过。

**设计分析：** 正确性测试先检查同步关系，性能实验再测延迟分布；不要拿一条 CI 时间阈值宣称整体 Agent 吞吐提高。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/08-observability-evaluation.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
