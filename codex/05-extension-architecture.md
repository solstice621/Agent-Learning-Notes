# Codex 05｜Extension：从类型化注册到执行接纳

[总目录](../README.md) · P1 · 对照：[OpenCode](../opencode/05-extension-architecture.md) / [DSH](../dsh/05-extension-architecture.md)

**固定源码：** `openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`。源码位于 `codex-rs/ext/extension-api/`，注意中间的 `ext/`。原文节选，未运行扩展实验。

## 1. 本篇研究对象

这里研究宿主装配的 Rust contributor registry，不把它与 Skills、MCP、面向用户的插件包或者脚本热加载视为同一机制。关键问题是：扩展能影响什么、何时安装、由谁消费、如何进入资源准入。

## 2. 核心源码 A：可变 builder 结束后交出 registry

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

### 逐段讲解

注册方法要求 `&mut self`，构造期可以追加贡献者；`build(self)` 消耗 builder，交出完成的 registry。调用者不再通过同一个 builder 任意追加。这表达结构上的构造/使用阶段分离。

两类 contributor 使用不同 trait，而不是一个任意字符串事件加 `Any` payload。学习时先看每个 trait 的输入输出和返回值是否能影响流程，再看实现；不要只数接口数量。

**限制：** 不可变 registry 不保证 contributor 内部无可变状态。`Arc<dyn ...>` 共享对象，实际实现仍可能使用锁、缓存或原子变量。也不能仅凭 vector 顺序推断所有回调的执行方式，消费方决定是否串行、并行或短路。

## 3. 核心源码 B：结构体划分不同的扩展职责

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

## 4. 核心源码 C：在消费输入前申请 permit

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

## 5. 学习实验

测试宿主装一个可控 gate：首次拒绝、第二次允许，观察 pending input 是否仍能被执行；再安装仅观察事件的 contributor，记录正常完成、拒绝和取消时的回调。

另用同一个共享 contributor 服务两个合成会话，检查其内部可变状态是否串会话。这里测试的是实现者的状态隔离，不是 registry 的字段数量。

## 6. 验收

交付扩展点矩阵：构造者、消费方、可变内容、失败传播、作用域。能解释为什么 `build(self)` 与内部状态不可变不同，为什么准入应早于消费工作，为什么不把 Rust 内核扩展与任意热加载插件混用。

静态分析不能证明所有第三方扩展都正确。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
