# OpenCode 01｜为什么输入接纳、运行协调、Step 与 Attempt 要各有边界？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从一个 HTTP 请求里完成全部工作会怎样？

最简单的服务端 Agent 是：收到 prompt → 调模型 → 执行工具 → 返回结果。短任务且客户端连接可靠时，它清晰有效。问题出现在客户端断连、同会话重复提交、运行中 steer、插件/Location 重载，以及清理期间又到达新任务。

当前 Core 把 SessionExecution、SessionRunner、runStep、SessionStep.attempt 分开。[F1][F2][F3] 不能仅用“解耦”解释这些层次；应说明每层分别拥有哪个不能交给别人猜测的事实。

## 2. 决策 O01-D1：为什么 durable input 与 wake 不是同一件事？

输入记录表达“系统接受了什么”；wake 表达“请检查是否有工作”。重复 wake 可以合并，但不同输入不能因为只剩一个 wake 就丢掉。运行协调器按 Session key 串行，相互独立的 key 则允许并发。[F4]

**源码里的直接理由：** `pendingWake` doorbell 关闭“drain 最后一次检查没有工作”与“切换 idle”之间的缝隙。[F4] 具体竞争是：t0 drain 认为无 eligible work；t1 新输入到达并 wake；t2 旧执行结束。如果 t1 只发现已经 busy 然后直接返回，t2 可能清掉 busy 后无人再启动，新输入就滞留。保留 pendingWake，使当前 drain 再查一次或由 settle 启动 successor。

| 候选方案 | 优点 | 不足或适用限制 |
|---|---|---|
| 每个请求开一个新 Loop | 实现简单 | 同 Session 可同时消费/更新历史 |
| 只用 busy 布尔值忽略重复 wake | 避免双启动 | idle 转换窗口可能丢失唤醒 |
| 永久轮询数据库 | 不依赖精确唤醒 | 延迟与扫描成本；仍需串行归属 |
| durable inbox＋可合并 doorbell | 内容与执行通知分离 | 必须处理 stopping、settlement 和 successor |

这些比较中，doorbell 的具体动机有代码注释支持；其余方案的得失是研究推导。这里是本进程调度，不是跨节点 exactly-once 队列。

## 3. 决策 O01-D2：为什么一个 Step 需要多个 Attempt，而不是重启整个 Turn？

Runner 拥有逻辑策略：输入在何时 promote，压缩是否必要，是否达到最大步骤，以及 Location 改变怎样继续。Attempt 拥有一次模型流、由它引发的工具和终态结算。[F2][F3]

**反事实：** 第一次请求在任何输出前连接失败。若重启整个 prompt admission，可能重复提升输入或让后来排队消息提前进入同一逻辑工作；若只在 HTTP 客户端无限重发，又可能忽略已提交输出和工具副作用。逻辑 Step 与物理 Attempt 分开，使重试只重复应该重复的部分。

Outcome 的 Retry、Continue、RecoverFull、Compacted 并非几个近义词。它们让“原请求还没发生有效输出”“已经有输出需继续”“续接状态失效需完整恢复”“上下文需要改变”成为可分支的决策。[F3] 但类型存在不等于所有 provider 行为都被证明，仍需各 adapter 的协议测试。

为何不拆更多层？每增加一层就增加接口、错误传播和状态传递。当前分层之所以值得研究，是每层有独立重试/取消/所有权边界，而不只是文件变小。一个固定工作流可能不需要 Location reload 或 steer，完全可以合并部分层次。

## 4. 取消语义如何检验这个划分？

Coordinator 的 interrupt 可以先确认接受，清理和 settled hook 后来完成；awaitSettlement 只等被中断的执行，awaitIdle 会跟随随后启动的 successor。[F4] 这不是 API 冗余：用户要尽快收到停止确认，资源管理器可能必须等旧任务清完，关闭服务则可能要等新任务也不再存在。

**分析：** “完成 Promise”必须命名其所等待的对象。用一个通用 done 同时代表收到取消、旧工作结束、整个会话闲置，会让并发调用方产生错误假设。尤其在清理期间新输入到达时，awaitIdle 可能比单次 settlement 长得多。

## 5. 验证与设计选择

**上游实验待运行：** 在 drain 最后检查与 idle transition 之间受控插入 wake，验证新任务不会搁置；在 cleanup 中加入新输入，对照 interrupt、awaitSettlement、awaitIdle 的完成时刻；同 Step 首次失败时确认没有重复 promote。

本仓库机制实验模拟 lost-wakeup 与保留 doorbell 的区别，只检查这个抽象窗口，不运行 OpenCode/Effect。上游验证还需断言原子区、取消和 hook 的真实调度。

**应能带走的判断：** 内容不应寄存在易丢失的通知里；运行串行化不等于禁止并发；logical work 与 physical attempt 分离，是为了限定重做和等待范围。不是所有 Agent 都要四层，但每个系统都必须回答这些范围。

[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/execution.ts
[F2]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/llm.ts#L1-L280
[F3]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/runner/step.ts#L1-L290
[F4]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/core/src/session/run-coordinator.ts#L1-L245

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：先选执行环境，再运行该环境的 Runner

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

#### 逐段讲解

`yield* store.get` 先取得 Session；`instances.provide(session)` 为本次 Effect 提供相应环境中的依赖。这里不是把一个全局工具/文件系统对象永久绑定到所有会话。

Runner 返回 Complete、Moved、Reloaded，而不是一个含义不明的 true/false。环境移动或重新加载后，Execution 重新通过 drain 选择依赖，并携带 continuation。**分析：** 这让环境生命周期与逻辑任务连续性分别表达，但不证明任务已经跨机器迁移。

`tapCause` 对仅中断的 cause 不按普通错误记录，其余日志附加 sessionID。控制信号与业务失败不能粗暴转成同一个 error string。

### 3. 核心源码 B：会话推进发生在安全边界

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

### 4. 核心源码 C：一个逻辑 Step 可以包含多个尝试

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



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/01-agent-loop.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
