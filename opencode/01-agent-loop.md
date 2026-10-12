# OpenCode 01｜Loop：Execution、Runner、Step、Attempt

[总目录](../README.md) · P0 · 对照：[Codex](../codex/01-agent-loop.md) / [DSH](../dsh/01-agent-loop.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`，取自 dev，不代表所有发行版。当前研究 `packages/core`，不再沿上一计划中已失效的旧 Processor 路径。下列为原文节选，实验未运行。

## 1. 本篇问题

为什么需要 Execution、Runner、Step 和 Attempt 四个概念？它们分别处理执行归属、会话推进、逻辑模型工作与一次物理尝试。把它们压成一个 while 循环，很容易把新输入接纳、网络重试和环境变更混在一起。

## 2. 核心源码 A：先选执行环境，再运行该环境的 Runner

源码：[`session/execution.ts`，L66–L182](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L66-L182)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts#L66-L182 -->
```ts
      const session = yield* store.get(sessionID)
      if (!session) return yield* Effect.die(new Error(`Session not found: ${sessionID}`))
      const result = yield* SessionRunner.Service.use((runner) =>
        runner.drain({ sessionID, force, continuation, promotable }),
      ).pipe(
        instances.provide(session),
        Effect.tapCause((cause) =>
          Cause.hasInterruptsOnly(cause)
            ? Effect.void
            : Effect.logError("Failed to drain Session", cause).pipe(Effect.annotateLogs({ sessionID })),
        ),
      )
      return yield* SessionRunner.DrainResult.$match(result, {
        Complete: () => Effect.void,
        Moved: (result) => drain(sessionID, false, result.continuation, promotable),
        Reloaded: (result) => drain(sessionID, result.force, result.continuation, promotable),
      })
```

### 逐段讲解

`yield* store.get` 先取得 Session；`instances.provide(session)` 为本次 Effect 提供相应环境中的依赖。这里不是把一个全局工具/文件系统对象永久绑定到所有会话。

Runner 返回 Complete、Moved、Reloaded，而不是一个含义不明的 true/false。环境移动或重新加载后，Execution 重新通过 drain 选择依赖，并携带 continuation。**分析：** 这让环境生命周期与逻辑任务连续性分别表达，但不证明任务已经跨机器迁移。

`tapCause` 对仅中断的 cause 不按普通错误记录，其余日志附加 sessionID。控制信号与业务失败不能粗暴转成同一个 error string。

## 3. 核心源码 B：会话推进发生在安全边界

源码：[`session/runner/llm.ts`，L165–L282](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282 -->
```ts
      while (true) {
        const next = yield* advanceToStep()
        if (next._tag !== "Ready") return next
        continuing = yield* runStep(next.context, step)
        step++
        force = false
        entering = false
      }
```

`advanceToStep` 不只是把 step 加一，它在前面的实现中处理输入提升、控制项和上下文准备。只有 Ready 才进入 `runStep`；Moved/Reloaded 等结果要交回上一层。

`continuing` 来自本次 Step 的结果；step 只在逻辑步骤完成后推进。**一个 Step 中发生网络重试，不应该每次都回这里消费下一条用户输入或增加逻辑 step。** 这由下面的内层循环体现。

## 4. 核心源码 C：一个逻辑 Step 可以包含多个尝试

同一 `llm.ts` 定位范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L165-L282 -->
```ts
      let assistantMessageID = SessionMessage.ID.create()
      const retry = yield* SessionRunnerRetry.make(bus, sessionID)
      let initial: SessionContext.Loaded | undefined = first
      let recoverOverflow = true
      let recoverContinuation = true
      while (true) {
        // Reuse boundary preparation once; retries refresh context without delivering more input.
        const loaded = initial ?? (yield* prepareContext(sessionID).pipe(Effect.flatMap(context.load)))
        initial = undefined
        const compacted = yield* compaction.compact({ reason: "auto", context: loaded })
        if (compacted.status === "failed") return yield* new StepFailedError({ error: compacted.error })
        if (compacted.status === "completed") {
          assistantMessageID = SessionMessage.ID.create()
          continue
        }
```

这是 `runStep` 内部的连续片段。第一次复用传入 context，以后的尝试重新加载；注释明确“不再交付新输入”。压缩成功会建立新的 assistant 身份并继续准备，而不是把旧请求原样重发。

两个 recover 标志表示恢复策略有自己的状态；不能仅凭这里的初值宣称可无限重试。实际何时关闭标志要继续读 outcome 分派，重试预算见 [04](04-llm-streaming.md)。

## 5. 职责表

| 层 | 本轮源码展现的责任 | 不该偷做的事 |
|---|---|---|
| Execution | 进程内协调、选择实例、环境变化后再进入 | 把局部 active 状态当集群租约 |
| Runner | 边界、输入与逻辑 Step | 每次 transport retry 都提升新输入 |
| Step/Attempt | 模型流、工具 Fiber、终态 | 私自接管整个会话调度 |
| Provider | 执行具体模型协议 | 代替 Harness 判断业务目标完成 |

## 6. 待运行实验与验收

mock provider 在输出前失败一次、第二次成功，观察逻辑 Step 与 physical request 数；再在已有输出后失败，观察是否保留部分回答与改变 assistantMessageID。另在运行期间提交 steer、queue 和 compaction 控制项，记录提升时机。

验收是一张四层时序图：每条输入只在哪个边界提升，哪一种重试停留在 Step 内，哪一种环境变化返回 Execution。文件 `runner/index.ts` 是接口，不应被当作完整 Loop 实现。

本篇静态分析未证明所有配置与平台分支。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
