# Codex 01｜为什么要把输入接纳、Turn 与请求快照分开？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从一个足够简单的方案开始

先设想一个只有 `messages` 数组的实现：新消息立即 append，模型返回工具调用后直接执行，再把结果 append。单用户、不允许执行中追加输入、配置永不改变时，这种循环完全可能够用。**本篇不是证明简单循环错误，而是研究哪些新增需求使它不再足够。**

当前源码需要处理执行期间的输入、每次请求的模型/能力视图，以及向模型和工具传播的取消。`run_turn` 在规定边界处理 pending input，随后构造实际请求，向采样函数传入 `Arc<StepContext>` 与 child cancellation token。[F1] 这些是实现事实，不是已经查明的最初产品需求。

## 2. 决策 C01-D1：输入到达为什么不立即改变当前推理？

**反事实场景（分析构造）：** 模型已收到“修改 A”，调用一个耗时工具；用户此时说“不要改 A，改 B”。修改本地 messages 数组无法改变已经发到模型端的请求，也不能回滚工具已经发生的效果。系统必须规定纠正意见属于当前 Step 的后续输入、下一 Turn，还是一次显式中断，而不是假装所有事情发生在同一瞬间。

源码把取 pending input 的时机交给 `can_drain_pending_input`；初始输入和压缩后尚未完成的模型/工具工作会影响何时消费队列。[F1] **推导：** 接纳边界的价值，是让“收到”“准许进入当前执行”“已形成模型请求”成为可区分的事实。它不意味着所有到达的输入都应该延迟，也不保证用户修改可以撤销过去。

| 候选方案（研究比较，并非作者全部实际考虑过） | 得到什么 | 必须承受什么 |
|---|---|---|
| 禁止运行中输入 | 控制流最简单 | 失去及时纠正能力，用户必须等待 |
| 每次输入都立即 cancel 并重启 | 新意图较快接管 | 高频输入造成工作浪费；副作用和终态仍需结算 |
| 新输入仅放下一 Turn | 边界清楚 | 长 Turn 中的纠正反馈较慢 |
| 在规定 Step 边界接纳 | 允许不重启整任务的调整 | 需要队列、接纳顺序及取消竞争规则 |

合理的选择取决于产品交互契约。不能因为 Codex 有队列，就把所有系统都做成可插队聊天；批量评测任务可以规定输入提交后不可修改。

## 3. 决策 C01-D2：为什么按请求捕获 StepContext，而不是处处读取最新配置？

源码注释直接说明：上下文、公布的工具和工具调用共享同一个请求视图；`for_prompt` 使用 StepContext 的模态信息，采样与工具阶段继续持有该视图。[F1][F2] 这属于**源码中明确写出的局部理由**，不需要替作者补历史故事。

设请求在 t0 公布了工具定义 V1；t1 用户切换模型或插件；t2 模型按 V1 返回参数。若执行器按 V2 解析或处理，会发生“决策依据与执行语义不一致”。把所有状态在会话创建时永久冻结虽能避免这种错位，却让新设置直到重启才能生效。Step 快照是两者之间的边界：当前请求内部保持一致，后续请求可以看到变化。

但**一致性不等于授权永不过期**。快照可以固定工具 schema、模型配置、结果解析方式；紧急撤销权限是否必须在执行点重新检查，是另一条政策。不能从 `Arc` 或“共享请求视图”推导出撤销永远无效，也不能声称源码已实现某种集群版本协议。

最有价值的抽象是区分“描述性配置快照”和“准许产生副作用的实时权利”。平台设计中可分别记录 configuration version 与 policy generation，但这是迁移建议，不是本段已经实现的两个字段。

## 4. 付出的成本与改变选择的条件

快照使旧对象可能被慢工具持续持有；队列使用户看见“已提交”时工作尚未采样。维护者还要追踪 Session、Turn、Step 和 transport attempt 的不同生命周期。若只有不可变输入的短任务，这些抽象可能是多余的；若存在大量配置热变更，则快照释放时间、历史保留与撤权时机反而要成为明确指标。

不能用一个 `finished` 判断所有层次：模型已输出答案、工具已停止、输入队列已清空、持久化已确认是不同命题。此处源码证明调用关系，不证明每一个下游动作都已完成稳定存储或 OS 资源回收。

## 5. 如何验证，而不是只认同这个故事

**上游实验待运行：** 用 mock provider 把请求冻结在 t0，改变工具定义后再返回旧版调用，比较请求声明、实际 handler 和下一 Step 的配置；另在慢工具执行中加入纠正输入，分别不取消、主动取消，记录接纳与结果顺序。验收要检查请求和副作用，不只看最终回答。

**反证标准：** 若在配置不可变的任务上，分层后没有更清楚的故障恢复或交互需求，却显著增加维护面，应接受更简单方案。若权限撤销后旧工具仍不受约束地运行，则需要审计执行授权层，而不能把请求快照本身当作安全保证。

**本篇应带走的判断：** 边界的作用不是让代码更“企业级”，而是为异步系统中不能同时发生的事实规定顺序。读下面的源码时，逐一寻找取队列、形成请求、持有快照和向下取消的真实位置。

[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L420-L665
[F2]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/tools/parallel.rs#L1-L275

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：到达的输入并不立即进入请求

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

#### 逐段讲解

`can_drain_pending_input` 是消费队列的条件，不是“是否有消息”。即使 UI 已经接到用户新输入，本次采样也可能暂不消费。源文件附近的注释给出两个延期场景：Turn 初始输入应先获得采样机会；自动压缩之后还有模型/工具后续工作要处理。

`get_pending_input(&sess.active_turn)` 表示取输入时仍绑定当前活动 Turn。这里不应猜测返回元组其他字段的语义；节选只使用 `.0`。真正要沿代码跟踪的是输入从队列到历史的接纳点。

`run_hooks_and_record_inputs` 把输入钩子与记录工作放在下一请求前。返回条件为真时停止本次循环，因此不是任何收到的文本都一定进入下一次模型调用。**从此调用点能证明顺序，不能单靠函数名证明已经 fsync。**

**思考反例：** 如果模型请求在接纳函数完成之前构造，用户已经提交的纠正意见可能不在模型输入中；如果重试时再次消费队列，则新输入可能在同一个逻辑步骤被提前提升。

### 3. 核心源码 B：先生成模型视图，再传递执行快照

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

#### 逐段讲解

`clone_history()` 取得运行时历史，再由 `for_prompt(...)` 依据输入模态形成模型视图。因此持久化记录、运行时历史、实际请求是三个需要分别检查的层次，不应直接拿聊天记录替代请求。

这里的模态信息来自 `step_context.settings.model_info`；`run_sampling_request` 又收到同一个 `Arc<StepContext>`。源文件前面的捕获点明确要求上下文、声明给模型的工具和实际工具调用共享一次请求视图。**分析：** 这是一种请求级快照边界，用来避免声明时与执行时配置错位；不是跨机器配置一致性协议。

`&mut client_session` 使本 Turn 的传输状态可以在多次请求间更新；它与长期 Session 不是同一个对象。其内部路由状态详见 [04](04-llm-streaming.md)。

`child_token()` 给下层传入取消通道，但看到取消 token 不等于所有子进程已停止；下层仍需落实取消、清理和结果结算。工具侧见 [03](03-tools-sandbox.md)。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/01-agent-loop.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
