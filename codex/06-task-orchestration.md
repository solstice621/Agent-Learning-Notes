# Codex 06｜子 Agent 编排：按需加载与归属校验

[总目录](../README.md) · [先读导览](../START_HERE.md) · [项目架构](00-architecture.md) · [问题索引](../DESIGN_INDEX.md)

代码中 `// 笔记：` 为新增中文注释，其余保留上游原文。

你让一个子 Agent 查资料。它已经交回结果，过了一会儿，你又补充：“请把第二点展开。”这时它可能早已从内存卸载，却仍保留原来的身份和历史。

**任务存在、程序对象已加载、当前正在工作，是三件事。** 这一版的多 Agent V2 将它们分开管理：持久记录保存身份和历史，ThreadManager 管理已加载对象，每个 Session 再管理当前一轮。

<!-- decision: C06-D1 | 为什么保留子任务，却不让它一直占着内存？ -->
## 子任务的按需加载与消息递送

任务树的根会话恢复时，`restore_v2_agent_metadata()` 先查持久的父子关系，只登记子任务身份，不逐个重建执行对象。这样，“列出有哪些子任务”无需把它们全部启动。

真正追加工作时，`send()` 才按需加载。下面这段里，最值得注意的是 `_residency_pin` 活得比 `send_input()` 更久：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/api.rs#L112-L120 -->
```rust
                    // 笔记：已登记身份不代表执行对象仍在内存；先根据元数据判断是否需要按需恢复。
                    let receiver = self.get_agent_metadata(target);
                    // 笔记：这个局部变量虽然以下划线开头，仍持有防卸载读锁，直到当前作用域结束。
                    let _residency_pin = if receiver.is_some() {
                        self.ensure_v2_agent_loaded(resume_config, target, /*parent*/ None)
                            // 笔记：加载过程可能等待存储或资源；成功之后再提交输入。
                            .await?
                    } else {
                        None
                    };
                    // 笔记：发送期间仍保留 pin，堵住加载成功后立刻被其他任务卸载的窗口。
                    let submission_id = self.send_input(target, input, start_options).await?;
                    (receiver.unwrap_or_default(), submission_id)
```

这个 pin 是一把读锁，可理解为“这次提交还在使用对象，请暂时别卸载”。卸载方必须取得同一个对象上的写锁；拿不到就报告忙。否则可能出现：刚检查加载成功，另一个操作把它卸掉，消息还没来得及送进去。

容量不足时，管理器会尝试卸载可卸载的闲置对象；卸载前保存记录，停止执行，再从已加载表中移除。身份和历史仍在，所以之后可以重建。这换来了较少的常驻对象，也增加了重新读取历史、恢复配置的成本。

若子任务只运行一次、交回结果后永不继续，一个普通异步任务加结果存储已经够用。这里多出的复杂度，是为“保留同一个可继续的子会话”付费。

<!-- decision: C06-D2 | 为什么父任务编号相同，还要重新检查归属？ -->
## 父子关系与实例归属校验

设父任务 P 的旧对象已经停止，同编号的新对象随后恢复。一个迟到的操作还拿着旧 P，只比较编号就可能误认它仍代表当前父任务。

通过父任务恢复子任务时，代码不仅检查编号，还比较“传入的父对象”和管理器中当前对象是否真是同一个：

<!-- annotated-source: https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L326-L338 -->
```rust
        // 笔记：这一组检查只适用于传入父对象的恢复路径，parent 为空会跳过该分支。
        if let Some(parent) = &parent {
            let parent_thread_id = parent.session.thread_id;
            let registered_parent = state.get_thread(parent_thread_id).await.ok();
            if !registered_parent
                // 笔记：编号相同还不够；指针相等证明它就是管理器当前登记的那一个父实例。
                .as_ref()
                .is_some_and(|registered| Arc::ptr_eq(registered, parent))
                || !parent.is_running()
                // 笔记：父任务还必须处于运行态，并使用本分支要求的多 Agent V2。
                || parent.multi_agent_version() != Some(MultiAgentVersion::V2)
                || !Arc::ptr_eq(
                    // 笔记：再确认双方属于同一个任务注册表，防止把子任务接到另一棵运行时任务树。
                    &self.runtime.registry,
                    &parent.session.services.local_agent_runtime.registry,
                )
            {
```

后面还会核对历史、元数据中的父编号是否一致，并重新采用当前父任务的环境和执行策略。某些本地权限变化会取双方允许范围的交集；缓存远程环境的权限变化则会拒绝这条恢复路径。

这里需要保留一个细节：`ensure_v2_agent_loaded()` 的 `parent` 参数可为空。普通发送者触发加载与“通过父对象恢复”是不同路径，上面的完整父对象检查只发生在提供父对象时。不能把一个分支的规则概括成所有发送都如此。

对象比较解决的是当前进程中旧对象冒用新生命周期的问题；它不是跨机器通用的身份凭证。真正要做远程调度，还得另行定义 Worker 身份和失效规则。

## 自测

查看一个子任务显示 `Unloaded`，能否据此认定任务已删除？刚加载成功，能否立刻释放 pin 再去发送消息？

<details>
<summary>参考答案与证据</summary>

都不能。前者只说明执行对象未驻留；后者会重新打开“检查成功到实际使用之间”的卸载窗口。

已重读[元数据恢复](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L190-L274)、[卸载与锁](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/residency.rs#L34-L101)、[环境重校验](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control/spawn.rs#L473-L561)。上游[恢复测试](https://github.com/openai/codex/blob/a9b0815167c27ab13719dd12d13b63e02b70d221/codex-rs/core/src/agent/control_tests.rs#L1276-L1443)检查未加载状态、历史恢复和消息提交；本轮只阅读，未运行或测量内存收益。

</details>

---

固定源码：`openai/codex@a9b0815167c27ab13719dd12d13b63e02b70d221`｜研究日期：2026-10-12。

[源码重读记录](../research/reread/codex-05-08.md) · [研究方法与验证边界](../RESEARCH_METHOD.md) · [源码归属与许可](../THIRD_PARTY_NOTICES.md)
