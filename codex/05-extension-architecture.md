# Codex 05｜扩展架构：职责划分与关闭流程

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

假设你想给 Codex 加一段项目背景，再记录每次工具执行的耗时。都塞进主循环当然能用，但下次接入另一种界面时，可能又得修改同一段核心代码。

**这一版的办法是：宿主安装功能，核心在约定的位置调用它们。** `codex-core` 负责会话与执行，app-server 负责装配；两者之间的 ExtensionRegistry 是一张按职责分组的名单。

<!-- decision: C05-D1 | 不同功能为什么不共用一个万能回调？ -->
## 扩展接口的职责划分

在 app-server 的 `thread_extensions()` 中，队列、记忆、MCP、Skills 等模块依次安装，最后调用 `build()`。各模块可以登记一种或多种能力；核心随后按执行阶段取出对应名单。

看注册接口就能发现：补充上下文、提供 MCP 服务、处理输入，是不同入口。

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/ext/extension-api/src/registry.rs#L112-L125 -->
```rust
    // 笔记：三类能力进入各自名单；核心到对应阶段才调用，不能把它们当成同一个事件回调。
    /// Registers one prompt contributor.
    pub fn prompt_contributor(&mut self, contributor: Arc<dyn ContextContributor>) {
        // 笔记：Arc 让宿主与注册表共享这一实现；trait 规定它必须提供上下文贡献能力。
        self.registry.context_contributors.push(contributor);
    }

    /// Registers one runtime MCP server contributor.
    pub fn mcp_server_contributor(&mut self, contributor: Arc<dyn McpServerContributor<C>>) {
        // 笔记：MCP 服务贡献与文字上下文贡献分开注册，即使二者来自同一产品模块。
        self.registry.mcp_server_contributors.push(contributor);
    }

    /// Registers one turn-input contributor.
    pub fn turn_input_contributor(&mut self, contributor: Arc<dyn TurnInputContributor>) {
        // 笔记：输入贡献者参与输入处理，其触发位置和上下文贡献者不同。
        self.registry.turn_input_contributors.push(contributor);
    }
```

例如构造模型上下文时，Session 遍历 `context_contributors()`，调用 `contribute_thread_context()`，再按片段的插入位置放入上下文提示或开发者指令。它不需要知道这段文字来自哪项产品功能。

这里的 **extension 指进程内的 Rust 装配接口**。MCP、Skills 可以经由这些接口接入，但它不等于 MCP 协议，也不是泛指用户安装的一切插件。接口上的类型负责告诉编译器“这里需要哪一种能力”，并没有把扩展代码隔离进沙箱。

相比 `onEvent(name, payload)` 这种万能回调，职责更容易查找，参数错误也更早暴露；代价是接口更多，跨职责功能需要登记多处。只有两三个固定功能的小程序，直接调用几个函数往往更省事。

<!-- decision: C05-D2 | 服务准备退出时，为什么先关入口再取输入？ -->
## 关闭时的输入准入与交接

另一个扩展入口叫 `TurnStartAdmission`。名字容易让人联想到容量配额，但当前 app-server 的实现主要服务于**平稳关闭**：不再接纳新工作，同时等已经接纳的提交完成。

其核心逻辑很短：拿同一把锁检查入口是否关闭；未关闭就增加正在提交的计数，交出一个 permit。

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/turn_admission.rs#L52-L62 -->
```rust
    fn try_admit(&self) -> Option<TurnPermit> {
        // 笔记：检查关闭状态与增加计数共用一把锁，避免关闭流程漏掉同时进入的新提交。
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // 笔记：入口关闭后不发许可；调用方需拒绝本次提交或另行保留待处理输入。
        if state.closed {
            return None;
        }
        // 笔记：先增加在途提交计数，再返回拥有生命周期的许可；许可释放时会减回计数。
        state.active += 1;
        self.active_tx.send_replace(state.active);
        Some(TurnPermit(self.clone()))
```

Core 启动新一轮前先索取 permit；拿不到便返回 `ServerDraining`，不把输入推进为已启动的工作。permit 在提交作用域结束时释放，`Drop` 将计数减一；运行中的轮次另有计数。这样就堵住了“服务以为已经闲了，另一份输入却正准备启动”的缝隙。

这个门也有明确例外：向正在执行的一轮追加输入，以及部分父任务委派的工作，可以走不同路径，让已接纳工作有机会收尾。它不是“一关闭就拒绝所有活动”。

如果只返回一个布尔值，关闭流程只能知道刚才允许过，却不知道提交何时结束。把许可做成有生命周期的对象，正是为了补上后半句。

## 自测

关闭信号到来时，某请求已拿到 permit、尚未创建运行中的轮次。此时能因为“运行轮数为零”就退出吗？

<details>
<summary>参考答案与证据</summary>

不能。还要等正在提交的计数归零，否则会漏掉即将发布的新轮次。

已重读[宿主装配](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/extensions.rs#L50-L121)、[上下文消费](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/mod.rs#L4405-L4437)、[启动与例外](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/session/turn_input.rs#L392-L451)。上游[关闭测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/app-server/src/turn_admission_tests.rs#L6-L28)检查拒绝新请求及 permit 释放计数；本轮只阅读，未运行。本文不把此门解释为已实现的模型容量控制。

</details>

---

固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/codex-05-08.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
