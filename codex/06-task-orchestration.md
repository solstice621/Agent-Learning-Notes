# Codex 06｜Subagent：身份、驻留与恢复所有权

[总目录](../README.md) · P1 · 对照：[OpenCode](../opencode/06-task-orchestration.md) / [DSH](../dsh/06-task-orchestration.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。聚焦 V2 子 Agent reload 的实际条件，不声称覆盖所有 spawn/fork 模式。未运行子任务实验。

## 1. 为什么从恢复入口学习编排？

创建一个子 Agent 只展示 happy path。恢复入口会暴露真正的所有权要求：父线程是否仍然有效、子身份是否存在、运行时是否需要重新加载、谁保证提交输入之前它不会又被卸载。

本篇选择 `LocalAgentControl::ensure_v2_agent_loaded`。它比单独研究 `spawn_agent` 的工具 schema 更接近 Agent Runtime。

## 2. 核心源码 A：父 ID 相同还不够

源码：[`agent/control/spawn.rs`，L310–L372](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L310-L372)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L310-L372 -->
```rust
        if let Some(parent) = &parent {
            let parent_thread_id = parent.session.thread_id;
            let registered_parent = state.get_thread(parent_thread_id).await.ok();
            if !registered_parent
                .as_ref()
                .is_some_and(|registered| Arc::ptr_eq(registered, parent))
                || !parent.is_running()
                || parent.multi_agent_version() != Some(MultiAgentVersion::V2)
                || !Arc::ptr_eq(
                    &self.runtime.registry,
                    &parent.session.services.local_agent_runtime.registry,
                )
            {
                return Err(CodexErr::InvalidRequest(format!(
                    "cannot resume multi-agent v2 child {thread_id}: parent ownership is unavailable; resume the parent first"
                )));
            }
        }
```

### 逐段讲解

`get_thread(parent_thread_id)` 查询现在注册的对象，再用 `Arc::ptr_eq` 检查它是不是传入的那个活对象。仅比较 ID 字符串不能识别“旧对象已经销毁，同 ID 新对象出现”的情况。

`parent.is_running()` 与 V2 检查限定当前恢复流程的前提；registry 的指针相等进一步检查本地运行时归属。四组条件共同定义这条 owner-validated reload 路径的适用范围。

**注意条件范围：** 校验包在 `if let Some(parent)` 内。没有传入 parent 的 sender-driven 路径有不同语义，不能把本段总结为“所有恢复都必须传入并运行父线程”。

`await.ok()` 把查询失败变成不存在，最终返回统一的 ownership unavailable 错误。由此可以讨论诊断信息与授权判定的取舍，但不能编造原始错误必然被丢失于所有日志。

## 3. 核心源码 B：已加载 runtime 与持久身份分开处理

同一源码范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L310-L372 -->
```rust
        if owner_thread_id.is_none()
            && let Ok(thread) = state.get_thread(thread_id).await
        {
            return self.runtime.pin_v2_residency(&state, &thread).await;
        }
        if self
            .runtime
            .registry
            .agent_metadata_for_thread(thread_id)
            .is_none()
        {
            return Err(CodexErr::ThreadNotFound(thread_id));
        }
        let mut environment_selections = self.runtime.registry.evicted_environments(thread_id);
```

### 逐段讲解

当适用且线程已加载时，获取 residency pin，而不是再次初始化 runtime。函数前的注释要求调用者一直保留返回的 pin，直到输入提交完成。**分析：** “检查它已加载”和“使用它”之间如果允许被卸载，就会产生使用窗口；pin 用于连接这个窗口，但具体锁协议需继续读 `pin_v2_residency`。

如果未走快速路径，则先检查 registry 中子 Agent 的 metadata。metadata 存在和 runtime 活跃不是同一个状态。接着读取被驱逐时的环境选择，为后续恢复准备输入。

这段不包含重新加载的全部代码，也没有证明远程工作区或权限始终可恢复。同文件后续会读取历史、父归属和当前环境配置，完整实验要跟踪到底。

## 4. 需要建立的四层模型

| 层 | 代表什么 | 常见误解 |
|---|---|---|
| 持久化线程/Agent 关系 | 能找回历史身份和父子信息 | 表示进程仍活着 |
| 内存 registry metadata | 当前运行时知道这个子身份 | 表示模型正在执行 |
| loaded / resident runtime | 可以承载请求的对象已加载 | 表示已拿到长期运行权 |
| active Turn | 当前具体工作正在推进 | 等同于子身份的全部寿命 |

同文件的 fork 过滤还体现“继承模型上下文，不继承所有父运行状态”的原则；具体过滤取决于模式。本篇不把一个 helper 的策略外推为所有子 Agent。

## 5. 待运行实验

实验一：保留旧 parent 对象，卸载并恢复同 ID parent 后，用旧对象请求子恢复，检查归属拒绝；再用当前对象重试。实验必须使用测试宿主，不伪造真实用户的权限。

实验二：创建子线程后分别观察 metadata 与 resident runtime，触发卸载/恢复并在输入提交前后释放 pin。记录具体持有期间，不以 UI 列表存在判断驻留。

实验三：恢复前收紧父执行策略或改变环境，检查是否明确拒绝不再有效的配置。未读到的分支保留待核对，不假定旧授权自动沿用。

## 6. 验收与迁移

能解释为什么对象身份检查不同于 ID 检查、为什么子身份与 runtime 分离、为什么 pin 要跨过输入提交。把学习结果画成创建—驻留—卸载—恢复的资源图。

这些是本地生命周期设计，不是跨节点 fencing。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
