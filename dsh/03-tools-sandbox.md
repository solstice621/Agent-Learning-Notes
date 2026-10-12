# DSH 03｜Tools：滚动池、顺序提交与取消排空

[总目录](../README.md) · P0 · 对照：[Codex](../codex/03-tools-sandbox.md) / [OpenCode](../opencode/03-tools-sandbox.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。展示实际 tool-calls 调度器，不把并发调度当作安全隔离。实验尚未运行。

## 1. 本篇的三个时间轴

模型给出调用顺序；工具 body 有实际开始/完成顺序；结果及 additionalContexts 有提交顺序。三个顺序不必相同。调度器必须在并发收益、可解释历史和错误收敛之间取舍。

## 2. 核心源码 A：未启动调用可以重新分类

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

### 逐段讲解

三项 while 条件约束取消状态、待启动数量和在途数量。这里限制的是 inFlight，不是会话历史长度或总内存。

启动下一项前重新读 executionMode；若后来不再可并发，则先停补池，让外层处理 barrier。这与“模型一发出调用就永久冻结全部并发策略”不同。

startCall 与 commitReady 都可能 await，所以后面重新检查 scheduler failure 和 AbortSignal；单在循环入口检查不够。**分析：** 异步边界之后重新验证前提，是可变注册表和取消竞争中的关键模式。

## 3. 核心源码 B：并发完成，但按模型顺序提交

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

### 逐段讲解

只检查 slots[committed]：即使后面 slot 已经完成，前面 undefined 就停。因此 dispatch 可乱序完成，commit 却只跨过连续前缀。

后置 finalize/finish 先完成，再写入与 callSeq 关联的工具结果，最后接纳 additionalContexts。模型历史和额外上下文顺序因此受同一提交序列控制。

`concluded ||=` 保留任何一次工具结果表达的结束意图，但是否立刻停止全部调用还要看外层逻辑，不能从这个布尔赋值推出“之后工具绝不运行”。

**取舍分析：** 顺序提交利于解释与重放，但会产生 head-of-line waiting：第一个慢工具阻塞后面已完成结果。应测量 commit wait，不把它全部算成后面工具 body 的耗时。

## 4. 核心源码 C：调度失败先排空，不让已启动任务失管

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

## 5. Sandbox 的承诺边界

[Sandbox 契约](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/sandbox.md) 定义 per-call 文件副作用政策，并返回 full/partial；网络和进程可见性不在 SandboxMode 的这套词汇中。受限 provider 不可用时必须 fail closed。

这些是执行隔离的独立契约。本篇的调度代码不证明文件或网络访问安全；工具 hook、guard 与 OS enforcement 应分开审查。

## 6. 实验与验收

用 [上游 gated-tool 测试](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/agent-loop/tests/tool-calls.spec.ts) 让 c2/c3 先完成、c1 最后完成，记录完成与 commit 的差异；在中间替换未启动工具的并发模式；在两项运行、一项未启动时取消。

验收是五工具时间线：parallel、parallel、exclusive、parallel、parallel，分别标出 body、barrier、commit、additionalContext 和 abort。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
