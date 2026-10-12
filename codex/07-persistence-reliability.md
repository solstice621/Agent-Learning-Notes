# Codex 07｜为什么必须区分记录、持久化检查点与可恢复的执行？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 不先定义 ACK，就无法讨论可靠性

“save 成功”可能表示数据进入内存队列、可被本进程读到、稳定存储已确认，或者其他进程可接管。把这些都叫持久化，会在故障时产生互相矛盾的预期。

ThreadStore 的 PersistContext 明确区分 Standard/ThreadPreparation 与允许后台处理的 SubagentSpawn、TurnStart、SteeredUserInput；flush/shutdown 对排队写入有单独保证。[F1] daemon_recovery 又要求输入已记录，并提醒调用者捕获后要 flush 再保存恢复快照。[F2]

## 2. 决策 C07-D1：为什么不每个事件同步刷盘，也不全部后台写？

| 策略 | 优点 | 不能忽略的风险 |
|---|---|---|
| 每条记录都等稳定存储 | ACK 含义简单、故障窗口小 | 写入次数和延迟进入热路径；跨介质也未必原子 |
| 只在会话结束保存 | 实现简单、正常路径快 | 长任务中断损失大；结束钩子可能不执行 |
| 所有写入异步且立即 ACK | 低等待时间 | 上层容易把未落盘输入当作可恢复事实 |
| 按语义检查点分级并设 fence | 在延迟与恢复边界之间选择 | 所有调用方必须理解各类 ACK |

源码并不要求允许后台的 context 一定异步，后端仍可同步完成；它规定的是上层最多能依赖什么，而不是具体 I/O 实现。[F1] 这是接口设计里重要的一点：**不要把某个当前后端碰巧提供的更强保证，当作全部后端的契约。**

反事实：输入已经入 writer，恢复 snapshot 已经发布，但实际输入尚未 durable。重启看到“应恢复这个 Turn”，却找不到它需要的输入基线。flush-before-snapshot 的意义就是建立依赖顺序；仅使用相同 ID 不能修复这个窗口。[F2]

## 3. 决策 C07-D2：为什么恢复资格宁可保守，也不能对所有任务统一 resume？

已读 interrupted_turn 路径要求 Regular、未取消、RecordedTurnInput、单一本地环境，以及受支持的 FromThread 环境配置。[F2] 代码注释说明远程身份/配置不由这条 daemon 恢复路径持久化。

**设计推导：** 恢复不是“把最后一段 Prompt 再发一次”。它至少需要输入、环境身份、配置和继续意图相互相容。对一个用户明确取消的任务自动恢复，会违背停止意图；对一个无法恢复身份的远程环境继续发工具调用，会制造未授权或错环境操作。

保守拒绝降低自动恢复覆盖率，但避免把不能兑现的环境假装可用。若业务要求更广恢复范围，就必须增加具体身份、环境重建、权限重新授权与生命周期记录，而不是删掉 `return None`。

## 4. 一个单靠日志无法消除的歧义

考虑两个物理世界：A 在记录 tool/call 后、工具尚未执行时崩溃；B 在工具产生副作用后、结果尚未记录时崩溃。只看相同的持久日志 `[tool/call]`，恢复者无法区分 A/B。

**这是在上述观察假设下的推导，不是声称 exactly-once 在所有系统都不可能。** 无条件重试可能重复 B 的效果；不重试可能让 A 永远未完成。解决需要外部幂等键、状态查询、同事务效果、补偿或人工确认等额外机制。把缺失结果补为 unknown/interrupted 是诚实记录，不是证明外部动作没有发生。

历史与元数据分开也不等于天然跨 JSONL/SQLite 原子事务。应该研究谁是真源、哪个索引可重建、失败如何暴露；不能看到两个存储文件就宣称统一提交协议已存在。

## 5. 验证、预算与选型

本仓库新增的机制实验只构造“同日志、不同外部效果”两个世界，验证观察不可区分；它不是 Codex crash test。**上游实验待运行：** 在输入记录前、记录后 fence 前、fence 后与 snapshot 后注入崩溃，记录恢复前缀；对测试计数工具在副作用后中断，检查是否重复或保持结果未知。

设计恢复目标时先给出 RPO/可丢失工作范围、允许重做的成本、环境重建时间和有副作用工具种类。短暂可重做的只读评测可能不需要每步持久化；跨小时有外部效果的任务则需要更强的检查点与归因。

**应学到的不是某个 flush 名字，而是承诺组合：** 允许后台的写入只能依赖后续 fence；可恢复的任务只能使用其真的保存过的执行前提；未知副作用需要额外协议，不能由日志重放替代。

[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L65-L205
[F2]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/daemon_recovery.rs#L1-L70

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：不同检查点允许不同持久化时机

源码：[`thread-store/src/store.rs`，L65–L95](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L65-L95)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L65-L95 -->
```rust
impl PersistContext {
    /// Whether a store may enqueue this checkpoint before returning and fence it at a later
    /// durability barrier. Stores may still choose to persist synchronously.
    pub fn allows_background_persistence(self) -> bool {
        match self {
            Self::ThreadPreparation | Self::Standard => false,
            Self::SubagentSpawn | Self::TurnStart | Self::SteeredUserInput => true,
        }
    }
}
```

#### 逐段讲解

策略显式允许 SubagentSpawn、TurnStart、SteeredUserInput 在返回前只入队，再由后续 durability barrier 约束；ThreadPreparation/Standard 不走这个许可。函数名是 allows，不是必须异步：后端仍可以同步实现。

与 [01](01-agent-loop.md) 的 `PersistContext::SteeredUserInput` 连起来，就能看出：输入接纳函数完成，不应无条件理解成所有字节已稳定落盘。

**特别注意：** ThreadPreparation 的 false 不单独证明一定创建了物理文件；下面的 trait 注释还允许某些未激活的 preparation 留在内存。要读完整语义，不能只看 bool。

### 3. 核心源码 B：接口明确命名 durability barrier

源码：[`store.rs`，L180–L210](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L180-L210)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/thread-store/src/store.rs#L180-L210 -->
```rust
    fn persist_thread(
        &self,
        thread_id: ThreadId,
        context: PersistContext,
    ) -> ThreadStoreFuture<'_, ()>;

    /// Flushes all queued items and returns once they are durable/readable.
    fn flush_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()>;

    /// Flushes pending items and closes the live thread writer.
    /// Stores with opt-in disposable preparations may discard an unactivated preparation.
    fn shutdown_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()>;
```

这是源代码中的 trait 契约，而不是某个后端的实际 fsync 实现。`context` 让调用者表明持久化用途，`flush_thread` 提供明确的完成承诺，`shutdown_thread` 还拥有关闭 writer 的职责。

同文件另有 `discard_thread` 用于初始化失败后的清理，不强迫未持久化 preparation 落盘。**分析：** 正常关闭、初始化回滚和业务检查点不应共享一个含糊的 close API。这里也不能推导 JSONL 和 SQLite 已通过同一个跨存储事务提交。

### 4. 核心源码 C：恢复快照有明确资格条件

源码：[`session/daemon_recovery.rs`，L22–L55](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/daemon_recovery.rs#L22-L55)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/daemon_recovery.rs#L22-L55 -->
```rust
        let active = self.active_turn.lock().await;
        let task = active.as_ref()?.task.as_ref()?;
        if task.kind != crate::state::TaskKind::Regular || task.cancellation_token.is_cancelled() {
            return None;
        }
        let context = &task.turn_context;
        context.extension_data.get::<RecordedTurnInput>()?;
        let settings = context.next_step_settings.load();
        let environments = self.services.turn_environments.snapshot_now();
        // Remote identities/configuration are not persisted across daemon restarts.
        if environments.environments.len() != 1 {
            return None;
        }
        let environment = environments.single_local_environment()?.selection();
        if environment.config != EnvironmentConfigState::FromThread {
            return None;
        }
```

Option 上的 `?` 表示缺少活动 task 或 RecordedTurnInput 时返回 None，而不是构造不完整快照。普通任务、尚未取消、输入已入记录流程、单一本地环境、受支持配置来源，是这条捕获路径的前提。

文件头明确要求捕获之后、持久化快照之前由调用方 flush rollout。`RecordedTurnInput` 只证明进入 writer，不是工具没执行的证明，更不是所有记录已经 durable。

**范围不能扩大：** 这是这条 daemon 路径的限制，不是对所有 Codex 恢复方式的总判决。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/07-persistence-reliability.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
