# Codex 07｜Persistence：后台提交许可与恢复资格

[总目录](../README.md) · P1 · 对照：[OpenCode](../opencode/07-persistence-reliability.md) / [DSH](../dsh/07-persistence-reliability.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。本篇新增阅读 `thread-store/src/store.rs`，用实际 trait 和策略代码解释落盘语义。未执行崩溃测试。

## 1. 最重要的问题

一次 persist 方法成功，到底表示进入缓冲、读取可见，还是稳定存储完成？如果输入已经记录但工具效果未知，能恢复什么？必须从契约和分支回答，不能用“支持 JSONL”代替。

## 2. 核心源码 A：不同检查点允许不同持久化时机

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

### 逐段讲解

策略显式允许 SubagentSpawn、TurnStart、SteeredUserInput 在返回前只入队，再由后续 durability barrier 约束；ThreadPreparation/Standard 不走这个许可。函数名是 allows，不是必须异步：后端仍可以同步实现。

与 [01](01-agent-loop.md) 的 `PersistContext::SteeredUserInput` 连起来，就能看出：输入接纳函数完成，不应无条件理解成所有字节已稳定落盘。

**特别注意：** ThreadPreparation 的 false 不单独证明一定创建了物理文件；下面的 trait 注释还允许某些未激活的 preparation 留在内存。要读完整语义，不能只看 bool。

## 3. 核心源码 B：接口明确命名 durability barrier

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

## 4. 核心源码 C：恢复快照有明确资格条件

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

## 5. 故障窗口与实验

| 窗口 | 待验证的事实 | 不可默认的结论 |
|---|---|---|
| 入 writer 后、flush 前 | 当前内存与存储分别有什么 | 重启一定保留全部输入 |
| flush 后、快照前 | 可以重建哪个记录前缀 | 当前活动工作一定被自动接管 |
| 工具效果后、结果前 | 外部效果是否已发生 | 结果缺失代表工具没执行 |
| shutdown / discard | 哪些资源释放、哪些记录保留 | 两个接口语义一样 |

只在合成会话中注入故障，使用带 invocation ID 的临时计数工具验证重复效果。验收必须记录具体 ACK 和持久前缀，而不是只展示“重启后能聊天”。

## 6. 学习目标

能把持久化策略、稳定存储 barrier、恢复资格和外部副作用分开说明；能指出 trait 契约与后端实现的证据等级。未读到的调用方与存储实现继续保留为待验证，不能据此宣称 exactly-once。

原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
