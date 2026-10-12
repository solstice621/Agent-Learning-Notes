# Codex 02｜上下文管理：历史压缩与状态恢复

Codex 已经改了几处代码、看了大段日志，任务还没完成，模型能接收的上下文却快装满了。如果只留下“之前做了一些修改，请继续”，下一步就可能忘记用户限制，或者不知道现在在哪个目录工作。

**压缩后的输入由摘要、保留的用户消息和重新生成的环境信息一起组成；程序还要保存这份新历史，供以后恢复。**

压缩在核心执行循环里衔接前后两次模型请求。`run_auto_compact` 会按功能和 provider 能力选择不同路径。本篇沿 `compact.rs` 的本地摘要路径往下看；这里的“本地”是由客户端组织摘要流程，摘要本身仍要请求模型。[查看路径选择](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn.rs#L1435-L1508)。

<!-- decision: C02-D1 | 为什么拿到摘要以后，还要重新拼装上下文？ -->
## 压缩后上下文的重建

先把已有历史交给模型，请它总结。结果回来后，代码从最近的用户消息向前挑选，在 token 限额内保留文字，再加上摘要。超出预算的消息可能被裁剪，所以“保留用户消息”也不是无损保存全部对话。[查看消息筛选](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L690-L769)。

接着才是容易忽略的一步：把当前环境等程序已知的信息重新放进新上下文。`WorldState` 是这些环境与运行信息的结构化集合，不需要让摘要模型凭记忆重写。

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/compact.rs#L86-L95 -->
```rust
    // 笔记：环境等结构化信息从当前状态重新生成，不依赖摘要模型回忆。
    let (updates, snapshot) = sess
        .build_initial_context_with_world_state(step_context, world_state)
        .await;
    // 笔记：先区分前缀与普通上下文，再把重复的 WorldState 更新合并。
    let (prefix, context) = split_prefix_updates(updates);
    let context = merge_world_state_updates(context);
    (
        // 笔记：最终替换历史同时包含摘要历史和重建的上下文；snapshot 留作后续比较基线。
        assemble_compaction_history(compacted_history, prefix, context),
        snapshot,
    )
}
```

`updates` 被拆成窗口前缀和普通上下文，后者合并后再与压缩历史组装。比如当前工作目录、指令来源发生变化，就应根据本次捕获的环境重新生成相关内容。摘要可以解释“之前为什么修改 A”，程序生成的上下文则告诉后续模型“现在在什么环境里继续”。

这个分工也解释了为什么单纯“只留最后十条”不总够用：十条长日志可能挤掉最早的目标；全部交给摘要，又会让本可确定重建的环境信息依赖模型记忆。不过，若主要问题只是某个工具输出过长，先裁剪工具日志往往更简单。

<!-- decision: C02-D2 | 为什么内存和存档必须保存同一份新历史？ -->
## 压缩历史的持久化与恢复

假设内存里摘要的编号是 `msg-a`，写入文件时又分配成 `msg-b`。文字相同，后续引用却可能找不到原来的消息。Codex 先补齐缺失的消息 ID，然后才同时用于活动历史和压缩检查点。

下面的 `clone` 保留的是同一批条目的内容和身份；一份进入内存，一份放进待持久化记录：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4213-L4226 -->
```rust
            // 笔记：前面已经补齐消息 ID；此处克隆使持久化检查点沿用与活动历史相同的身份。
            let replacement_history = items.clone();
            // 笔记：items 移交给活动历史；replacement_history 留给下面的持久化记录。
            state.replace_annotated_history(
                items,
                Some(reference_context_item.clone()),
                HistoryReplacement::Compaction {
                    reviewer_compaction_hash: metadata.reviewer_compaction_hash,
                },
            );
            state.reasoning_effort_pin = ReasoningEffortPin::Compacted;
            // 笔记：基线随这次历史替换一起更新，以便下一请求只补充必要的环境变化。
            state.history.set_world_state_baseline(world_state_baseline);
            // 笔记：这里只构造待保存条目；磁盘写入发生在后续调用，不能视为原子提交。
            CompactedItem {
                message: metadata.message,
                replacement_history: Some(replacement_history),
                guardian_history: state.history.guardian_history_checkpoint(),
```

还有一个实际的并发细节：模型正在总结时，用户可能清除了目标。新摘要基于较早的历史，直接替换会把这次清除覆盖掉。实现会找出摘要输入之后接受的目标更新，按原顺序追加到替换历史中。[查看 ID 分配及目标更新合并](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4157-L4212)。

这种做法增加了重建、合并和存档的复杂度，也挡不住摘要丢失细节。压缩是否划算，要看后续任务能否正确完成，不能只看输入缩短多少。相同 ID 也不意味着内存与磁盘原子提交：这里先换内存，再调用持久化接口。

## 自测

摘要文字正确，但压缩过程中刚接受的“清除目标”不见了，这次压缩算成功吗？

<details>
<summary>参考答案</summary>

不算。摘要正确只说明旧输入总结得对；替换历史还必须保留之后接受的目标变更，否则下一请求拿到的是过时状态。

</details>

证据与局限：上游[检查点测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/tests.rs#L6229-L6281)同时断言并发目标更新被保留、持久化历史等于活动历史；本轮只阅读，未执行。远端 V2 与 TokenBudget 路径的摘要内容和组织方式不能由本地路径一概推出。
