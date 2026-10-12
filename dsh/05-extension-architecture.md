# DSH 05｜为什么插件边界首先是资源所有权，而不是热加载功能？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从普通依赖注入到可替换执行世界

直接给 Agent 构造函数传一个 model、一个 tool map 和一个 store，已经是一种清楚的依赖注入。只有当不同宿主、远程执行、模型策略和用户能力组合需要独立替换时，才值得建立插件服务树。

官方架构将 capability seam 分为服务定义、提供方、消费方；filesystem 与 subprocess 应属于同一 execution world，替换能力不能让一半操作在本地、一半在远程。[D1] 因此本篇不以“全部插件化”本身为好坏标准，而看它是否维护可替换的完整契约。

## 2. 决策 D05-D1：为什么替换一个工具不等于替换一种能力？

**反事实：** read 工具读远程工作区，而 bash 仍在本地 cwd 执行。两者都能成功，却针对不同文件世界。上层模型看到的路径相同，也不能发现执行已经错位。

| 方案 | 适合什么 | 问题 |
|---|---|---|
| 每个工具自行连接环境 | 少量独立工具 | 路径、凭证和生命周期各自为政 |
| 一个巨型 runtime service | 单部署、简单所有权 | 很多不相关能力被绑在一起 |
| Definition/Provider/Consumer | 可替换完整能力及一致契约 | 需要设计缺失能力、组合兼容和资源生命周期 |
| 全远程 RPC 能力 | 强宿主/执行分离 | 版本、认证、取消、网络失败都进入契约 |

官方架构给出能力分层；其对“为什么能统一移动 execution world”的说明是直接材料。[D1] 其他候选取舍是本笔记推导。只有一个抽象接口而没有定义提供方/消费方如何使用，并不能证明真实可替换；更不能因挂在插件树里就声称有进程或安全隔离。

插件还要选择正确事件域：durable Session facts、live Agent events 和 capability interception 不具有相同持久性。把状态只藏在 live callback 内，重启就无法重建；把所有瞬时事件都做业务日志，又增加写入与迁移成本。

## 3. 决策 D05-D2：为什么取消资源创建后，还要接收并清理迟到的结果？

FactoryOwnership 停止接受新工作，取消工厂信号，等待已跟踪 startup 和 live teardown；raceAbortCall 对已取消后才返回的值调用 releaseAbandoned。[F1]

**反事实时间线：** t0 开始创建远程工作区；t1 插件卸载，不再等待创建 Promise；t2 远端成功创建工作区并返回。若只在 t1 抛 AbortError，没人获得这个迟到资源的所有权，它可能一直存活并产生费用。

等待所有创建完成后才能取消，避免漏资源却可能让 UI/宿主被卡住；直接放弃最快却泄漏；“取消等待＋迟到结果仍需释放”将响应性与所有权分开，但增加 cleanup 分支和失败归因。

注意：调用 releaseAbandoned 不自动证明任何远程资源一定被释放，仍需要具体释放实现、错误观察和期限。源码使用 Promise.allSettled 汇集释放失败，不让第一项失败就跳过其他清理；但一个永不 settle 的资源仍可能阻塞收敛。[F1] 是否加入超时、强制回收或孤儿资源扫描，是进一步平台设计，不是这里已经实现的保证。

## 4. 为什么“可逆注册”不是普通 remove(key)？

旧插件可能在卸载期间仍有未完调用；同 ID 新插件可能已被装配。旧 disposer 若只按字符串删 registry，可能删除新代际的注册。回调、Scope、对象身份或 generation 都要绑定到具体生命周期。

这与取消后的迟到工具结果是同一类所有权问题：**谁发起、谁最终接收、谁有权改变现在的状态？** 它不因为 JavaScript 单线程就消失，await 后状态可以已经改变。

因此热更新付出的成本包括就绪屏障、依赖释放顺序、回滚、迟到资源与取消传播。短命 CLI 可以选择重启而不热更新；配置固定的执行 Worker 也可以使用不可变镜像替代动态插件树。这些替代值得比较，不应先假定热更新必需。

## 5. 验证、反证与学习目标

本仓库机制实验检查旧生命周期的完成/释放不能影响同 ID 新对象，属于自建状态模型。

**上游实验待运行：** 阻塞 setup、开始卸载、再返回资源，检查 abandoned cleanup；让一个 disposer 失败，核对其他仍被等待；同 ID 新代际建立后触发旧回调，检查它不能注销或修改新实例；切换 remote provider 后对照 fs/subprocess 所见路径。

如果系统没有独立替换能力需求，直接函数/构造依赖往往更简单。若要支撑多种执行环境和研究策略，最应学习的是公开契约、scope 与所有权，而非 YAML 配置行的数量。

[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/architecture.md
[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/index.ts#L110-L245

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：先拒绝新工作，再等待旧工作收敛

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

#### 逐段讲解

`accepting=false` 先关闭接纳，再发 teardown signal 和唤醒等待 inactive 的调用者。不能反过来先等待全部 Agent 停止、同时又允许新 Agent 加入，导致卸载永远无法结束。

等待集合不只有 liveAgents，还包含 startupTasks。资源尚未发布为 Agent 时也可能占用连接、Session writer 或工作区；“registry 里没有它”不代表没有需要清理的启动工作。

Promise.allSettled 收集全部结果，而不是第一个失败就提前退出、漏掉其他清理。之后聚合错误，既完成排空尝试，也不把失败静默吞掉。

**限制：** allSettled 不给出时限，任意不合作的外部操作仍可能阻塞；这段也不是跨进程停止协议。下一步要验证各 dispose 的契约和超时策略。

### 3. 核心源码 B：取消等待不等于底层操作停止

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

#### 逐段讲解

先处理调用前已经取消，避免启动没必要的 operation。否则将实际操作保存为 pending，再与取消竞争。即使 raceAbort 先因取消而结束，pending 仍可能稍后成功返回资源。

`pending.then(releaseAbandoned, ...)` 专门处理这个迟到的值。**分析：** 在创建容器、远程工作区或 Session writer 等场景，调用者放弃等待不等于资源没有创建。忽略迟到结果会导致资源泄漏。

这段只在提供 releaseAbandoned 时安装回收，而且该回调类型为同步 void；不能据此承诺任意异步清理都已经等待完成。真正资源释放职责仍在调用者及工厂生命周期。

原异常继续抛出，不用迟到清理把取消伪装成成功。raceAbort 内部还负责移除 AbortSignal listener，避免重复累积监听器。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/dsh/05-extension-architecture.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
