# Codex 02｜为什么上下文压缩需要重建历史，而不只是生成摘要？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 真正的问题：减少输入与保留行动依据之间的冲突

假设 Agent 已完成一次修改、发现一个失败测试、获得一个权限许可，并且还有一个未完成目标。最简单的压缩是保留最后 K 条消息；另一种是让模型把全部内容总结成一段话。这两种方法都有合理应用，但它们压缩的对象与系统必须继续执行的状态不一定相同。

源码中压缩结果不仅有文本，还有窗口与响应等元数据；replacement history 结合压缩后历史、初始上下文和 world state，最终构造新的活动历史。[F1] 本篇把这些事实解释为一个**带身份和恢复约束的状态变换**。这是分析框架，不把“摘要保证保真”当成作者承诺。

## 2. 决策 C02-D1：为什么不把所有东西都交给摘要模型？

摘要模型适合提炼语义，却不应该成为唯一的身份、工具协议或授权记录维护者。一个说明“已经运行测试”的摘要，不等于带退出码的测试结果；“用户批准了操作”的自然语言，也不应自动成为当前执行许可。

| 方案 | 有利条件 | 失败或损失的方式 |
|---|---|---|
| 固定保留末尾消息 | 短任务、近期信息最重要 | 早期目标和约束消失；裁剪可能切开 call/result |
| 全部总结成文本 | 对话理解、无严格工具协议 | 丢失对象身份、精确错误或未完成行动关系 |
| 只压缩工具大输出 | 大日志占主要空间 | 对累计目标、决策和消息数量帮助有限 |
| 摘要加确定性重建 | 需要继续执行与恢复 | 更多元数据、重建逻辑和验证成本 |

Codex 的已读函数先构造初始上下文/world-state updates，再把 prefix、context 与 compacted history 组合。[F1] **推导：** 将可确定重建的事实从有损摘要中分离，能缩小必须依赖模型准确记忆的范围；但到底保留哪些信息、所有压缩路径是否相同，不能由一个 helper 证明。

反例也应保留：若实验发现大多数输入来自单个超长工具结果，完整摘要调用可能比结果裁剪更贵、更慢；不应为了架构一致而对所有任务都套语义摘要。

## 3. 决策 C02-D2：为什么 live 与 persisted history 要共用稳定身份？

源码注释明确 `replace_compacted_history` 在构造持久化 CompactedItem 前补齐缺失 item ID，以保证 live 和 persisted history 一致。[F1] 这比“为了恢复”更具体：它要求同一次状态替换的对象身份在两边相同。

**反事实时间线：** t0 内存摘要生成 ID=a；t1 持久化代码又生成 ID=b；t2 某个后续引用仍指向 a；t3 重启读到只有 b 的历史。即使摘要文字完全一样，引用、更新与差异比较也不再指向同一个对象。这里要解决的是身份一致性，不是文本相似度。

不过，共用 ID 不意味着两个存储介质原子提交。ThreadStore 的契约区分历史与元数据更新；原始 trace 与业务历史也有不同职责。[F2][F3] **推导边界：** 稳定身份减少一类恢复歧义，但写入失败、部分完成和日志索引重建仍需独立协议。

把事件历史保留为审计证据、让活动上下文是派生视图，是一种候选结构；它不能保证任何未采集的原始请求都可凭空重建。要证明实际模型输入，应检查当时的工具声明、system/developer 内容和路由，而不是仅保存最终摘要。

## 4. 怎样判断这次压缩值得？

采用分析模型：任务总成本 = 摘要调用成本 + 后续模型请求成本 + 因信息损失产生的返工成本。只比较“压缩后少了多少 token”会漏掉摘要请求与失败重做；只看一次模型调用速度也会漏掉前缀缓存变化。

质量指标应包含目标/约束保留、未完成工具状态、精确文件引用、关键失败证据与最终任务正确性。缓存和价格的具体收益必须实测；本篇没有给出未经测量的节省比例。若需要模型逐字保留大量证据，应考虑外部证据存储加引用，不能要求摘要同时承担无损档案职责。

## 5. 验证与选型结论

**上游实验待运行：** 准备一个包含早期约束、已完成副作用、失败测试和未完成目标的固定历史，分别运行保留末尾、工具结果裁剪和当前压缩路径。使用 mock 摘要先验证身份及协议，真实摘要质量另做评测。恢复后对照实际请求，不能只对照 UI 转录。

**失败注入：** 在生成摘要后、替换活动历史后、落盘确认后分别中止测试进程，观察可恢复前缀。必须写清每个观察属于 live、store 还是 model request；身份相同仍可能缺一段已执行效果的结果。

**读后应能自行决策：** 有损内容、确定性状态和审计证据是否应该分开？本工作负载的主瓶颈是否真的来自会话长度？如果不需要恢复，也没有复杂工具协议，简单窗口可能优于当前结构。

[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L1-L300
[F2]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L65-L205
[F3]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/rollout-trace/README.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：重建历史，同时返回基线快照

源码：[`compact.rs`，L66–L130](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L66-L130)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L66-L130 -->
```rust
pub(crate) async fn build_compaction_replacement_history(
    sess: &Session,
    step_context: &StepContext,
    world_state: &WorldState,
    compacted_history: Vec<ResponseItemEnvelope>,
) -> (Vec<ResponseItemEnvelope>, WorldStateSnapshot) {
    let (updates, snapshot) = sess
        .build_initial_context_with_world_state(step_context, world_state)
        .await;
    let (prefix, context) = split_prefix_updates(updates);
    let context = merge_world_state_updates(context);
    (
        assemble_compaction_history(compacted_history, prefix, context),
        snapshot,
    )
}
```

#### 逐段讲解

输入不只有 `compacted_history`：还包含当前 Session、StepContext 和 WorldState。代码因此明确表示摘要后的请求需要结合当前执行世界重建，而不是孤立拼接摘要。

`build_initial_context_with_world_state` 同时返回 updates 与 snapshot。接着只变换 updates，snapshot 原样作为第二个返回值交还调用者。**从这段可以证明新历史和比较基线成对输出；snapshot 后续如何用于差分，要继续跟踪调用者，不能在这里推测全部实现。**

`split_prefix_updates` 把必须作为前缀的条目与普通 context 分开；`merge_world_state_updates` 再处理后者。两个步骤说明“信息有哪些”和“信息位于哪里”都参与请求语义。

**设计分析：** 如果只返回消息数组、不返回同步的状态基线，后续增量更新可能重复注入旧事实，或把刚建立的事实当作未曾发送。该风险是从接口推导的分析，不是声称上游出现过此 bug。

### 3. 核心源码 B：上下文插入位置是显式策略

同一文件和定位范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L66-L130 -->
```rust
fn assemble_compaction_history(
    compacted_history: Vec<ResponseItemEnvelope>,
    prefix: Vec<ResponseItem>,
    context: Vec<ResponseItem>,
) -> Vec<ResponseItemEnvelope> {
    let history = insert_initial_context_before_last_real_user_or_summary(
        compacted_history,
        context.into_iter().map(ResponseItemEnvelope::new).collect(),
    );
    prefix
        .into_iter()
        .map(ResponseItemEnvelope::new)
        .chain(history)
        .collect()
}
```

#### 逐段讲解

第一步交给专门的 helper 确定 context 在压缩历史中的位置；调用名称指出它针对最后真实用户输入或摘要附近的插入位置。**准确的边界判定应读 helper，而不是根据名称重新写一个 `messages.insert(...)` 当作源码。**

`context` 与 `prefix` 从 `ResponseItem` 包装为 `ResponseItemEnvelope`，而 `compacted_history` 已经是 envelope。说明已有历史和新建上下文并非同一种生产路径，不能无条件丢掉原 envelope 中的信息。

最后 `prefix.chain(history)` 明确把 prefix 放在拼装结果前面。这里的 order 是真实代码行为，不是用于展示的排序。如果随意按时间重排，可能改变指令位置和后续请求前缀。

### 4. 核心源码 C：检查点不只保存摘要文本

同一文件和定位范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L66-L130 -->
```rust
pub(crate) struct CompactedHistoryMetadata {
    pub(crate) input_goal_ids: HashSet<ResponseItemId>,
    pub(crate) message: String,
    pub(crate) window_number: u64,
    pub(crate) window_ids: AutoCompactWindowIds,
    pub(crate) compaction_response_id: Option<String>,
    pub(crate) compaction_model_hash: Option<String>,
    pub(crate) reviewer_compaction_hash: Option<String>,
}
```

字段把目标关联、窗口身份、响应与模型相关元数据和文本分开。附近注释还说明 `replace_compacted_history` 在构造持久化 `CompactedItem` 前补齐缺失 ID，以保持 live/persisted 历史一致。这里应进一步追踪使用方，不根据字段名推测未读的 hash 算法。

**关键区分：** 文本一致不保证对象身份一致；保存了检查点不保证摘要没丢关键信息；正确组装消息也不等于存储已经稳定提交。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/02-context-session.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
