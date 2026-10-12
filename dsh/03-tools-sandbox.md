# DSH 03｜为什么并发执行却顺序提交？并发有界为何不等于内存有界？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 先分清启动、完成与提交

模型给出 A、B、C 三个调用。body 可能按 B、C、A 完成；系统还要决定后置处理、日志结果和额外上下文以什么顺序对其他组件可见。DSH 的 runGroup 用 inFlight 跟踪未完成 dispatch，用 slots 保存结果，用 committed 沿模型顺序推进。[F1]

先纠正一个不充分理由：**“为了可以重放，所以必须模型顺序提交”不成立。** 完成顺序也可以被日志记录并重放。真正要分析的是当前顺序控制了哪些后续行为。

## 2. 决策 D03-D1：为什么把并行范围限定在执行体，把后置行为顺序化？

commitReady 除了 append result，还调用 finalize/finish 并接纳 additionalContexts；提交后待启动调用的 executionMode 可以重新判断。[F1] 因此顺序影响的不只是最终结果数组。

**推导场景：** A/B 都返回额外上下文，或后置 hook 更新工具注册。若完成先后直接决定这些行为顺序，单纯工具耗时差异就可能改变后续上下文与调度。按模型顺序提交减少这部分时序差异，但不使工具本身确定、不回滚外部副作用，也不保证整个任务可重复。

| 候选方案 | 强项 | 代价 |
|---|---|---|
| 全串行 | 顺序最直接、冲突容易推理 | 独立操作不能 overlap |
| 无界并发＋统一收集再按序处理 | 代码简洁，返回数组也能保持输入顺序 | 无在途上限、整个批次等待、动态屏障困难 |
| 有界并发＋完成即提交 | 完成结果及时可见 | 后置效果/上下文受完成顺序影响 |
| 有界滚动池＋模型顺序提交 | 兼顾 overlap 与规定的语义顺序 | 队头阻塞、结果缓冲、调度复杂度 |

`Promise.all` 不能被当作“结果必然乱序”的反面教材：它可以按输入顺序返回结果。真正比较的是并发上限、增量提交、屏障与取消，而不是 API 名字。

## 3. 决策 D03-D2：为什么 maxParallelToolCalls 不是完整的资源预算？

源码限制的是 `inFlight.size < maxParallelToolCalls`。后面短任务完成后会从 inFlight 移除并补新任务，而它们的结果可能仍在 slots 等前面慢任务提交；slots 按整个 group 分配，已提交结果也没有在这段代码立即清空。[F1]

**可构造反例：** 并发上限 2；A 耗时 100，后面六个调用各耗时 1。A 一直占一个位置，另一个位置可连续完成六项。即使在途数从未超过 2，A 完成前仍可有六项已完成结果待提交。这里的 100/1 是抽象逻辑时间，不是产品测量。

因此需要分别讨论在途数量、待提交结果数、保留结果字节与完整调用组大小。不能由 inFlight 有界推出整个调度器内存有界；也不能只看本段就声称进程输出毫无限制，因为单工具和其他层可能另有上限。

可考虑同时限制“已启动但未提交”的窗口、为结果设字节预算、将大结果落到受控存储、或允许某些无后置效果调用完成即提交。每个方案都会改变 throughput/latency/语义：按未提交窗口限流会在 A 很慢时停止补任务，降低 overlap；落盘增加 I/O 与清理协议；乱序提交必须证明相关效果可交换。

## 4. 动态分类与取消为什么增加复杂度？

exclusive barrier 与结果 hook 可以改变后续工具分类；调度器在未开始前重读模式，取消后停止补充、等待 started dispatch，并为未启动调用记录合成错误。[F1][T1] 这比一次分组后 Promise.all 复杂，是因为“尚未开始”的政策仍可变化。

但能力标记仍需可信：isConcurrencySafe 并非自动证明没有共享状态；顺序提交也不能修复已经并发发生的冲突写入。沙箱文件效应模式、并发冲突域和网络隔离要分别描述。[D1]

## 5. 验证与选择条件

本仓库离散事件机制实验验证：完成顺序与提交顺序可以不同；宽度 2 的上述例子会积累 6 个待提交结果；给“未提交窗口”也设限可降低 backlog，但不能让 body 结果更早完成。只证明抽象性质，不替代 DSH 测试或内存压测。

**上游实验待运行：** gated tool 让首项阻塞、后续返回可控大结果；分别记录在途数、completed-not-committed、retained bytes 和 RSS；让后置 observer 改分类，核对 barrier；取消期间检查真实结果、未启动和结果未知的区别。

**读后应能选择：** 对独立纯读结果，完成即处理可能更好；需要模型顺序的语义效果时，顺序提交值得成本；对大输出，单一并发计数不是充分的资源约束。

[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L115-L260
[T1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/tool-calls.spec.ts
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/sandbox.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：未启动调用可以重新分类

源码：[`agent-loop/src/tool-calls.ts`，L140–L250](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L140-L250)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L140-L250 -->
```ts
  const fillPool = async (): Promise<void> => {
    while (!aborted && nextToStart < group.length && inFlight.size < maxParallelToolCalls) {
      // Re-read later modes after ordered commits so registry changes can create a barrier.
      // oxlint-disable-next-line typescript/no-non-null-assertion -- bounded by the loop condition
      const nextCall = group[nextToStart]!
      if (nextToStart > 0 && mode === 'parallel'
        && ctx.tools.executionMode(nextCall.exec).kind !== 'parallel') break
      await startCall(nextToStart)
      nextToStart++
      throwSchedulerFailure()
      await commitReady()
      throwSchedulerFailure()
      // Abort may arrive while pre-execute awaits.
      if (signal.aborted) aborted = true
    }
  }
```

#### 逐段讲解

三项 while 条件约束取消状态、待启动数量和在途数量。这里限制的是 inFlight，不是会话历史长度或总内存。

启动下一项前重新读 executionMode；若后来不再可并发，则先停补池，让外层处理 barrier。这与“模型一发出调用就永久冻结全部并发策略”不同。

startCall 与 commitReady 都可能 await，所以后面重新检查 scheduler failure 和 AbortSignal；单在循环入口检查不够。**分析：** 异步边界之后重新验证前提，是可变注册表和取消竞争中的关键模式。

### 3. 核心源码 B：并发完成，但按模型顺序提交

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L140-L250 -->
```ts
  const commitReady = async (): Promise<void> => {
    while (committed < group.length) {
      const slot = slots[committed]
      if (slot === undefined) break
      const call = group[committed]
      const result = slot.needsPost
        ? await ctx.tools[TOOL_RUNTIME_SCHEDULER].finalize(slot.exec, slot.result)
        : ctx.tools[TOOL_RUNTIME_SCHEDULER].finish(slot.exec, slot.result)
      // oxlint-disable-next-line typescript/no-non-null-assertion -- bounded index
      appendToolResult(session, turn, step, call!.block, result, callSeqs[committed]!)
      for (const context of result.additionalContexts ?? []) acceptContext(context)
      concluded ||= result.concludesTurn === true
      committed++
    }
  }
```

#### 逐段讲解

只检查 slots[committed]：即使后面 slot 已经完成，前面 undefined 就停。因此 dispatch 可乱序完成，commit 却只跨过连续前缀。

后置 finalize/finish 先完成，再写入与 callSeq 关联的工具结果，最后接纳 additionalContexts。模型历史和额外上下文顺序因此受同一提交序列控制。

`concluded ||=` 保留任何一次工具结果表达的结束意图，但是否立刻停止全部调用还要看外层逻辑，不能从这个布尔赋值推出“之后工具绝不运行”。

**取舍分析：** 顺序提交利于解释与重放，但会产生 head-of-line waiting：第一个慢工具阻塞后面已完成结果。应测量 commit wait，不把它全部算成后面工具 body 的耗时。

### 4. 核心源码 C：调度失败先排空，不让已启动任务失管

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/src/tool-calls.ts#L140-L250 -->
```ts
  } catch (error: unknown) {
    schedulerFailure ??= { error }
    await Promise.allSettled(inFlight.values())
    throw schedulerFailure.error
  }

  if (aborted) {
    // Started calls and accepted context settle first; every remaining model
    // call then receives an ordered synthetic result before the turn aborts.
    for (const call of group.slice(started)) appendSkippedToolCall(session, turn, step, call.block)
    return { consumed: group.length, aborted: true, concluded }
  }
```

scheduler failure 保留第一个失败，等待已经启动的 dispatch settled 后再向上抛出；普通 abort 则为未启动部分补成对的跳过结果。这与“Promise.race 返回一次错误就不管其他 Promise”不同。

allSettled 不自动中断工具，也不能保证任意不合作的工具及时结束；这是需要测试 provider/工具取消契约的地方。已经发生但结果未知的副作用也不能写成未启动。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/dsh/03-tools-sandbox.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
