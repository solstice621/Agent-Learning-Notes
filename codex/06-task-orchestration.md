# Codex 06｜为什么子 Agent 要区分持久身份、运行驻留与当前父归属？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从“spawn 一个异步任务”到可继续的子会话

一次短暂委派只需要启动 future、等待结果、销毁局部变量。若子任务还必须可查找、可卸载、可恢复、可继续对话，并且受父任务权限约束，future 就不再是足够的数据模型。

已读实现把恢复 Agent 元数据与加载 runtime 分开；ensure_v2_agent_loaded 在继续时校验父对象、运行状态、registry 归属，返回需要由调用方保持的 residency pin。[F1] 这些事实支持下面两项设计研究，但不证明此系统已经是多机器调度平台。

## 2. 决策 C06-D1：为什么“知道任务存在”不必“让它一直驻留”？

存储身份回答“它是谁、属于谁、历史在哪里”；resident runtime 回答“执行所需对象现在是否加载”；active Turn 回答“它现在是否工作”。三者生命周期不一样。

| 方案 | 合理场景 | 主要成本 |
|---|---|---|
| 子任务是一次性 future | 不需要继续、只有一份结果 | 结果后无法继续原会话 |
| 所有子会话永远加载 | 子任务少、低延迟优先 | 长期对象与连接累积 |
| 只保存最终结果 | 大批独立评测 | 无法恢复中间对话 |
| 身份持久、runtime 按需加载 | 多个可继续任务 | 冷启动、驱逐竞争、状态恢复更复杂 |

**推导：** 按需驻留的收益取决于闲置会话比例和加载成本。不能看到“metadata-only restore”就宣称内存减少某个百分比；如果子任务始终繁忙，反复驱逐可能得不偿失。

residency pin 的关键是维护加载后到提交输入之间的有效期。如果 load 成功便立刻释放保护，另一个动作可能在真正提交前驱逐它，形成检查时可用、使用时失效的窗口。源码注释要求调用者保留 pin 到输入提交。[F1] 这是一个跨函数的生命周期契约，不应只研究加载函数的返回值。

## 3. 决策 C06-D2：为什么 parentID 相同还不够？

代码使用 `Arc::ptr_eq` 检查 registry 里当前父对象就是传入的对象，还检查父是否运行、是否 V2、是否同一个 registry。[F1]

**反事实：** 父会话 ID=P 的旧对象停止，随后同 ID 的新对象恢复。旧异步回调晚到，仍拿着 P。如果只比较字符串，它可能误把旧生命周期的授权用于新父。对象身份检查能拒绝这一类本进程中的过期关系。它类似 generation 校验的用途，但对象地址不是跨机器 fencing token，也不能跨重启保存。

恢复还要处理当前环境和权限条件。历史上曾经允许的动作，不应仅因为日志里存在就天然拥有当前权限。**推导原则：** 恢复历史是数据行为，恢复执行权是授权行为；二者应分别检查。具体所有平台和远程模式的权限收紧规则仍需逐分支审计，本文不声称已经覆盖。

### 上下文继承是另一条权利边界

spawn.rs 的过滤逻辑会按模式筛选父历史，并排除某些角色/运行时信息及父累计 token。[F1] 复制父任务的目标和发现，有助于子任务理解；复制父的临时角色、许可描述或累计用量，则可能制造错误身份与重复计费归因。

但是，过度过滤也可能丢失关键约束，使子 Agent 再做一遍父任务。应该用任务所需信息完整度与不应继承的能力/计数共同评估，而不是默认“继承越少越安全”或“越多越聪明”。

## 4. 成本、替代方案与不能外推的能力

持久 Agent 图、resident registry、active task 三层增加一致性维护。父结束时是否取消子任务、子结果如何通知、后台任务是否可脱离父继续，都要成为明确产品政策，而不是从 parentID 自动推导。

如果工作是大量独立、不可继续的 rollout，一个普通 Job ID + immutable input + result store 可能更合适；把所有 rollout 做成完整聊天 Session 会增加不必要状态。反过来，长交互式委派需要继续同一子会话时，简单 map of futures 会越来越脆弱。

## 5. 验证与读后判断

**上游实验待运行：** 创建子任务后卸载 runtime，核对身份仍存在；在 reload 与 submit 之间插入驱逐请求，检查 pin 的作用；让旧父回调在同 ID 新父启动后到达，验证不会获得控制；恢复前收紧测试权限，检查错误分类。

**量化指标：** 常驻对象数、冷加载延迟、重新获取模型/环境的成本、失败恢复率，以及输入在加载竞争中是否重复或丢失。避免只测 spawn 平均延迟。

读完应能分别回答：一个子任务是否存在、是否加载、是否运行、谁现在有权继续它。能分清这四个问题，才有基础讨论把 Agent 执行扩展到远程 Worker。

[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L1-L540

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：父 ID 相同还不够

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

#### 逐段讲解

`get_thread(parent_thread_id)` 查询现在注册的对象，再用 `Arc::ptr_eq` 检查它是不是传入的那个活对象。仅比较 ID 字符串不能识别“旧对象已经销毁，同 ID 新对象出现”的情况。

`parent.is_running()` 与 V2 检查限定当前恢复流程的前提；registry 的指针相等进一步检查本地运行时归属。四组条件共同定义这条 owner-validated reload 路径的适用范围。

**注意条件范围：** 校验包在 `if let Some(parent)` 内。没有传入 parent 的 sender-driven 路径有不同语义，不能把本段总结为“所有恢复都必须传入并运行父线程”。

`await.ok()` 把查询失败变成不存在，最终返回统一的 ownership unavailable 错误。由此可以讨论诊断信息与授权判定的取舍，但不能编造原始错误必然被丢失于所有日志。

### 3. 核心源码 B：已加载 runtime 与持久身份分开处理

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

#### 逐段讲解

当适用且线程已加载时，获取 residency pin，而不是再次初始化 runtime。函数前的注释要求调用者一直保留返回的 pin，直到输入提交完成。**分析：** “检查它已加载”和“使用它”之间如果允许被卸载，就会产生使用窗口；pin 用于连接这个窗口，但具体锁协议需继续读 `pin_v2_residency`。

如果未走快速路径，则先检查 registry 中子 Agent 的 metadata。metadata 存在和 runtime 活跃不是同一个状态。接着读取被驱逐时的环境选择，为后续恢复准备输入。

这段不包含重新加载的全部代码，也没有证明远程工作区或权限始终可恢复。同文件后续会读取历史、父归属和当前环境配置，完整实验要跟踪到底。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/06-task-orchestration.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
