# Codex 05｜为什么类型化扩展点与执行准入比一个万能 Hook 更有价值？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 问题不是“插件够不够多”

假设宿主要接入审计、上下文注入、工具策略和容量控制。最简单的方案是在 Loop 里增加四个 if；另一个方案是提供 `onEvent(name, payload)`，任何插件都能修改任何状态。前者初期清楚但逐渐耦合，后者看似灵活却把约束隐藏在字符串和执行顺序里。

当前代码使用 ExtensionRegistryBuilder 收集类型化 contributor，build 后交付 registry；职责包含 input、context、tool、model request、lifecycle、admission 等。[F1] 这里研究的是宿主内核装配，不把它与用户脚本插件、Skills 或 MCP 混为一个系统。

## 2. 决策 C05-D1：为什么在编译期划分贡献能力？

**源码事实：** registry 按 trait 存储 contributor，build 消费 builder，暴露不同职责的 getter；to_builder 复制 Arc，用于宿主进一步添加贡献。[F1]

**设计推导：** 接口是对修改权的约束。上下文贡献方可以参与请求内容，却不需要接触进程管理；工具生命周期观察方不应偷偷接管输入队列。接口越明确，调用者越容易知道失败传播、是否影响控制流、以及需要在哪些测试里覆盖。

| 方案 | 强项 | 代价 |
|---|---|---|
| Loop 内直接调用业务组件 | 调用链直观、初期成本低 | 每种部署策略都修改核心 |
| 万能事件/字典 Hook | 扩展快、接口少 | payload 隐式契约、误用权限、顺序耦合 |
| 类型化 contributor | 编译期检查和职责可见 | trait/API 数量增长，跨版本维护更严格 |
| 远程插件协议 | 故障与进程边界更清晰 | 序列化、版本协商、取消、延迟与认证成本 |

这些是研究候选，不是声称 Codex 作者逐一否决过它们。类型安全也不等于业务安全：一个 contributor 内部仍可持有 Mutex、网络客户端或其他共享状态。不可变 registry 防止注册结构被随意改变，不证明每个 handler 纯函数、无竞争或无泄漏。

**反例：** 如果两个 Session 共用同一 Arc contributor，而它把最近一次用户内容放在未按 Session 分区的字段里，registry 再不可变也不能阻止跨会话混淆。该风险需要实现审查，而不是由 `Arc` 名字解决。

## 3. 决策 C05-D2：为什么容量准入要先于输入消费？

`admit_turn_start()` 返回 permit；缺少 permit 时，在 Core 消费 pending input 前拒绝启动；没有配置 gate 的宿主走允许路径。顺序与默认行为在源码注释和分支中明确。[F1]

**反事实：** 输入先出队，再发现没有模型/执行容量。系统此时必须选择丢弃、重新入队、保留半启动状态，或让已接纳工作无限等待。把准入前移，并不能消灭排队，但能避免无执行权的任务过早推进到难恢复的状态。

为什么 permit 不只是 bool？源码类型返回一个拥有生命周期的对象，适合用所有权把资源预约与工作生命周期关联。**这是类型所允许的设计解释，不是某个未知 permit 实现已正确释放的证明。** 还需检查实际实现是否在 cancel、error、正常完成与初始化失败时释放。

如果需要提供 durable“已接受”响应，可以先将输入持久化，再等待执行准入；不要把输入持久化与执行 permit 对立起来。准确顺序是可分别 ACK 的 admission 与 execution start，而不是所有系统都必须在排队前预约昂贵资源。

## 4. 可扩展性产生了哪些新问题？

接口越细，跨域需求越可能需要协调多个 contributor。必须规定调用顺序、是否可变换输入、错误是否阻止启动，以及生命周期是否允许阻塞。强类型不会自动防止一个审计 sink 在热路径等待远程服务。

对于固定部署、没有外部宿主定制的系统，少量明确函数依赖可能比搭建注册体系更好。对于需要在研究实验、产品 CLI 和服务端复用同一 Loop 的系统，稳定的类型化边界更有价值；但这个适用判断不能替代性能测量。

## 5. 验证方案与迁移结论

**上游实验待运行：** gate 第一次不给 permit，第二次允许，检查输入身份和消费次数；在已经获得 permit、尚未发模型请求时取消，检查资源释放。给 contributor 注入阻塞/抛错，观察影响哪一层；同时跑两个合成 Session 检查状态是否错误共享。

**反证标准：** 如果新增一个简单策略需要改十多个 trait，却并没有降低耦合或形成更清晰权限边界，就要重新评估接口粒度。类型化是工具，不是终点。

面向 Agent Infra，值得带走的是“扩展点也有 authority、ordering 与 lifetime”；不是学会注册一个回调就等于会做插件平台。准入 gate 是容量控制的接缝，不是跨节点租约和租户配额的一揽子实现。

[F1]: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L1-L230

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：可变 builder 结束后交出 registry

源码：[`registry.rs`，L135–L225](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L135-L225)。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L135-L225 -->
```rust
    /// Registers one tool-lifecycle contributor.
    pub fn tool_lifecycle_contributor(&mut self, contributor: Arc<dyn ToolLifecycleContributor>) {
        self.registry.tool_lifecycle_contributors.push(contributor);
    }

    /// Registers one ordered turn-item contributor.
    pub fn turn_item_contributor(&mut self, contributor: Arc<dyn TurnItemContributor>) {
        self.registry.turn_item_contributors.push(contributor);
    }

    /// Finishes construction and returns the immutable registry.
    pub fn build(self) -> ExtensionRegistry<C> {
        self.registry
    }
```

#### 逐段讲解

注册方法要求 `&mut self`，构造期可以追加贡献者；`build(self)` 消耗 builder，交出完成的 registry。调用者不再通过同一个 builder 任意追加。这表达结构上的构造/使用阶段分离。

两类 contributor 使用不同 trait，而不是一个任意字符串事件加 `Any` payload。学习时先看每个 trait 的输入输出和返回值是否能影响流程，再看实现；不要只数接口数量。

**限制：** 不可变 registry 不保证 contributor 内部无可变状态。`Arc<dyn ...>` 共享对象，实际实现仍可能使用锁、缓存或原子变量。也不能仅凭 vector 顺序推断所有回调的执行方式，消费方决定是否串行、并行或短路。

### 3. 核心源码 B：结构体划分不同的扩展职责

同一源码范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L135-L225 -->
```rust
pub struct ExtensionRegistry<C: Sync> {
    event_sink: Arc<dyn ExtensionEventSink>,
    turn_start_admission: Option<Arc<dyn TurnStartAdmission>>,
    thread_lifecycle_contributors: Vec<Arc<dyn ThreadLifecycleContributor<C>>>,
    turn_lifecycle_contributors: Vec<Arc<dyn TurnLifecycleContributor>>,
    config_contributors: Vec<Arc<dyn ConfigContributor<C>>>,
    token_usage_contributors: Vec<Arc<dyn TokenUsageContributor>>,
    skill_invocation_contributors: Vec<Arc<dyn SkillInvocationContributor>>,
    context_contributors: Vec<Arc<dyn ContextContributor>>,
    mcp_server_contributors: Vec<Arc<dyn McpServerContributor<C>>>,
    turn_input_contributors: Vec<Arc<dyn TurnInputContributor>>,
    tool_contributors: Vec<Arc<dyn ToolContributor>>,
    tool_lifecycle_contributors: Vec<Arc<dyn ToolLifecycleContributor>>,
    model_request_contributors: Vec<Arc<dyn ModelRequestContributor>>,
    turn_item_contributors: Vec<Arc<dyn TurnItemContributor>>,
    approval_review_contributors: Vec<Arc<dyn ApprovalReviewContributor>>,
}
```

这里不是让每个扩展都拿到整个 Session 随意修改，而是分别提供 context、tool、model request、lifecycle 等接口。不同 trait 代表不同职责，但是否真正限制访问权限还需读接口定义和实现，不把类型名称当作安全沙箱。

`turn_start_admission` 是可选的单一 gate，而多个 contributor 存成列表，说明能力组合不只有一种基数。设计扩展时应明确“允许多个实现叠加”还是“只有一个最终决定者”。

**设计分析：** 将观察性扩展与接纳性扩展分开，能减少一个统计组件无意控制主执行的风险；实际错误是否隔离仍取决于消费路径。

### 4. 核心源码 C：在消费输入前申请 permit

同一源码范围。

<!-- source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L135-L225 -->
```rust
    /// Acquires the host's turn-start permit, or an empty permit for ungated hosts.
    /// A missing permit rejects the start before Core consumes pending input.
    pub fn admit_turn_start(&self) -> Option<Box<dyn Send>> {
        match &self.turn_start_admission {
            Some(admission) => admission.admit_turn_start(),
            None => Some(Box::new(())),
        }
    }
```

未安装 gate 返回空的允许 permit；安装后由宿主决定。`None` 的意义是拒绝准入，不是“没有插件所以禁止一切”。注释把拒绝点放在消费输入之前，避免拿走工作后才发现没有容量。

`Box<dyn Send>` 不告诉我们实际 permit 使用什么资源控制，也不证明它是分布式租约。完整研究要追踪谁持有、何时 drop、取消是否释放。不要把这个 seam 直接命名为“已经实现全局调度器”。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/codex/05-extension-architecture.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
