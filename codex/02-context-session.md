# Codex 02｜Context / Session：摘要之外的历史重建

[总目录](../README.md) · P0 · 前置：[01](01-agent-loop.md) · 对照：[OpenCode](../opencode/02-context-session.md) / [DSH](../dsh/02-context-session.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。原文节选不改写变量名或流程；以下仅分析已读的本地压缩路径，不能代表所有远端压缩实现。未运行实验。

## 1. 本篇的问题

为什么压缩不是“把旧 messages 换成一句总结”？因为下一次请求仍需要初始指令、环境事实、普通上下文和正确顺序，还要与持久化检查点中的身份一致。

阅读入口是 `core/src/compact.rs`。把它看成一个有状态输入、有返回基线的历史转换器，比只研究摘要 Prompt 更接近 Harness 工程。

## 2. 核心源码 A：重建历史，同时返回基线快照

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

### 逐段讲解

输入不只有 `compacted_history`：还包含当前 Session、StepContext 和 WorldState。代码因此明确表示摘要后的请求需要结合当前执行世界重建，而不是孤立拼接摘要。

`build_initial_context_with_world_state` 同时返回 updates 与 snapshot。接着只变换 updates，snapshot 原样作为第二个返回值交还调用者。**从这段可以证明新历史和比较基线成对输出；snapshot 后续如何用于差分，要继续跟踪调用者，不能在这里推测全部实现。**

`split_prefix_updates` 把必须作为前缀的条目与普通 context 分开；`merge_world_state_updates` 再处理后者。两个步骤说明“信息有哪些”和“信息位于哪里”都参与请求语义。

**设计分析：** 如果只返回消息数组、不返回同步的状态基线，后续增量更新可能重复注入旧事实，或把刚建立的事实当作未曾发送。该风险是从接口推导的分析，不是声称上游出现过此 bug。

## 3. 核心源码 B：上下文插入位置是显式策略

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

### 逐段讲解

第一步交给专门的 helper 确定 context 在压缩历史中的位置；调用名称指出它针对最后真实用户输入或摘要附近的插入位置。**准确的边界判定应读 helper，而不是根据名称重新写一个 `messages.insert(...)` 当作源码。**

`context` 与 `prefix` 从 `ResponseItem` 包装为 `ResponseItemEnvelope`，而 `compacted_history` 已经是 envelope。说明已有历史和新建上下文并非同一种生产路径，不能无条件丢掉原 envelope 中的信息。

最后 `prefix.chain(history)` 明确把 prefix 放在拼装结果前面。这里的 order 是真实代码行为，不是用于展示的排序。如果随意按时间重排，可能改变指令位置和后续请求前缀。

## 4. 核心源码 C：检查点不只保存摘要文本

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

## 5. 研究与实验

构造固定历史，包含目标、禁止操作、已完成工具副作用、未完成工作。用固定摘要结果先测试重建机制：标出 prefix/context/history 来源与顺序，比较压缩后 live 历史和恢复后的 ID，再另行用真实模型评估摘要质量。

故障注入选择摘要失败、历史已构造但未提交、持久化失败三个边界。每个实验记录能恢复的实际前缀，不以 UI 仍能显示文字证明 durability。

## 6. 验收

交付“原日志—活动历史—模型请求”对照表，解释 `WorldStateSnapshot` 为什么与结果一起返回、Envelope 为什么不能随手去掉、插入位置为什么属于语义。

**扩展阅读：** [ThreadStore 契约](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/README.md) 区分原始历史与元数据写入；[07](07-persistence-reliability.md) 讨论落盘边界。源码许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
