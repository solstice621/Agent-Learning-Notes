# DSH 05｜Plugins：卸载收敛与取消后的迟到资源

[总目录](../README.md) · P1 · 对照：[Codex](../codex/05-extension-architecture.md) / [OpenCode](../opencode/05-extension-architecture.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。本篇不只介绍 Cordis 概念，而是阅读默认 Agent factory 的实际资源管理。原文节选，未运行卸载竞态实验。

## 1. 插件化首先是所有权问题

[官方架构](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/architecture.md) 将 Service Definition、Provider、Consumer 分开。真正困难的部分是替换和卸载：已经启动的 Agent、正在创建的资源、旧 callback 和新同 ID 对象由谁处理？

本篇用 `FactoryOwnership` 与 `raceAbortCall` 展示两个重要边界。Profile/bundle 配置解决装配；下面的代码解决装配后的资源寿命，两者不可互相替代。

## 2. 核心源码 A：先拒绝新工作，再等待旧工作收敛

源码：[`agent-loop/src/index.ts`，L110–L222](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L110-L222)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L110-L222 -->
```ts
  async dispose(): Promise<void> {
    this.accepting = false
    this.teardown.abort(new Error('agent loop is not active'))
    this.inactive.resolve()
    const settlements = await Promise.allSettled([
      ...[...this.liveAgents].map(dispose => dispose()),
      ...this.startupTasks,
    ])
    const failures: unknown[] = []
    for (const result of settlements) {
      if (result.status === 'rejected') failures.push(result.reason)
    }
    throwCollectedFailures(failures, 'agent loop disposal failed')
  }
```

### 逐段讲解

`accepting=false` 先关闭接纳，再发 teardown signal 和唤醒等待 inactive 的调用者。不能反过来先等待全部 Agent 停止、同时又允许新 Agent 加入，导致卸载永远无法结束。

等待集合不只有 liveAgents，还包含 startupTasks。资源尚未发布为 Agent 时也可能占用连接、Session writer 或工作区；“registry 里没有它”不代表没有需要清理的启动工作。

Promise.allSettled 收集全部结果，而不是第一个失败就提前退出、漏掉其他清理。之后聚合错误，既完成排空尝试，也不把失败静默吞掉。

**限制：** allSettled 不给出时限，任意不合作的外部操作仍可能阻塞；这段也不是跨进程停止协议。下一步要验证各 dispose 的契约和超时策略。

## 3. 核心源码 B：取消等待不等于底层操作停止

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L110-L222 -->
```ts
async function raceAbortCall<T>(
  operation: () => PromiseLike<T> | T,
  signal: AbortSignal,
  id: SessionId,
  releaseAbandoned?: (value: T) => void,
): Promise<T> {
  if (signal.aborted) {
    throw signal.reason instanceof Error
      ? signal.reason
      : new Error(`agent "${id}" creation aborted`, { cause: signal.reason })
  }
  const pending = Promise.resolve().then(operation)
  try {
    return await raceAbort(pending, signal, id)
  } catch (error: unknown) {
    // oxlint-disable-next-line typescript/no-unnecessary-condition -- the signal can abort while the operation is awaited.
    if (signal.aborted && releaseAbandoned !== undefined) {
      void pending.then(releaseAbandoned, () => undefined)
    }
    throw error
  }
}
```

### 逐段讲解

先处理调用前已经取消，避免启动没必要的 operation。否则将实际操作保存为 pending，再与取消竞争。即使 raceAbort 先因取消而结束，pending 仍可能稍后成功返回资源。

`pending.then(releaseAbandoned, ...)` 专门处理这个迟到的值。**分析：** 在创建容器、远程工作区或 Session writer 等场景，调用者放弃等待不等于资源没有创建。忽略迟到结果会导致资源泄漏。

这段只在提供 releaseAbandoned 时安装回收，而且该回调类型为同步 void；不能据此承诺任意异步清理都已经等待完成。真正资源释放职责仍在调用者及工厂生命周期。

原异常继续抛出，不用迟到清理把取消伪装成成功。raceAbort 内部还负责移除 AbortSignal listener，避免重复累积监听器。

## 4. 与插件作用域、公开能力的联系

默认 factory 用 PreparedAgent 管理未发布资源，并在 setup/registry publication/creation listeners 失败时协调回滚。公开消费者应依赖 Agent/Session/Capability 契约，而不是导入 ReactLoopAgent 私有方法。

例如 Goal Driver 通过公开服务和事件操作输入，见 [06](06-task-orchestration.md)。但“依赖公开接口”不等于可无条件搭配任何实现：新 Loop 仍需满足相同生命周期与事件顺序。

## 5. 实验与验收

实验一：让 setup 等待闸门，在 factory.dispose 后释放它，检查没有半发布 Agent 或残留 writer。实验二：底层 operation 不响应取消、稍后才 resolve，验证 releaseAbandoned 被调用且没有误释放后来新创建的对象。实验三：一个 disposer 失败，观察其他 cleanup 仍被等待且错误聚合可见。

只用合成资源和本地 mock，不创建收费云实例。记录接纳关闭、取消通知、资源迟到和最终 teardown 四个时刻。

验收能解释为什么启动中的任务也属于卸载责任、为什么 Promise.race 不是底层取消、为什么旧 disposer 需要绑定精确生命周期。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
