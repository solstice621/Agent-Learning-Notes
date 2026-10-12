# DSH 07｜Persistence：真正的模型/工具前置检查点

[总目录](../README.md) · P1 · 对照：[Codex](../codex/07-persistence-reliability.md) / [OpenCode](../opencode/07-persistence-reliability.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。本篇补读上一轮未展开的 `session-checkpoint-policy/src/index.ts`。以下保证以该插件挂载、对应分支被命中为前提；未验证全部 profile，也未做崩溃测试。

## 1. 先回顾 append / flush 的区别

Session.append 在内存事实层提交事件；持久化 Handle 的 append 可以接纳/缓冲；flush 是稳定存储屏障。[持久化契约](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/persistence.md) 还规定单写者、只读 handle、close 与修复边界。

上一轮不能根据文档概括断定每个 Turn 都直接 flush。本次直接检查策略插件怎样把 durability 插在具体副作用前。

## 2. 核心源码 A：先 flush，再构造下游模型流

源码：[`session-checkpoint-policy/src/index.ts`，L1–L83](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L1-L83)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L1-L83 -->
```ts
function afterCheckpoint(
  ctx: Context,
  session: Session,
  next: () => AsyncIterable<StreamChunk>,
): AsyncIterable<StreamChunk> {
  return (async function* (): AsyncIterable<StreamChunk> {
    await ctx.sessions.flush(session)
    yield* next()
  })()
}
```

### 逐段讲解

返回的是异步生成器，真正被消费时先 await flush，之后才调用 next 并委派其 stream。若 flush 拒绝，下游 adapter 不会由这条包装路径启动。

区别在于 next 被延迟调用，而不只是把已经启动的网络请求结果延迟展示。**设计分析：** 若先构造会立即产生副作用的下游操作，再等待日志提交，崩溃时可能出现请求已经发出、重建依据却没有持久化的窗口。

这里不能推导 provider 端没有其他独立副作用，也不能证明 JSONL 后端每次具体使用什么系统调用；策略层只建立调用顺序与契约。

## 3. 核心源码 B：只有能关联活 Session 的调用套检查点

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L1-L83 -->
```ts
  ctx.on('llm/stream', (options, next): AsyncIterable<StreamChunk> => {
    if (options.sessionId === undefined) return next()
    const session = ctx.sessions.get(options.sessionId)
    return session === undefined ? next() : afterCheckpoint(ctx, session, next)
  })
```

没有 sessionId，或当前 store 找不到 Session，就直接 next。因此准确表述不是“所有 LLM 调用都先刷盘”，而是插件对能关联本地活 Session 的这条调用链建立检查点。

**验收要点：** 检查 profile 是否挂载、options 是否携带正确 sessionId、查找是否成功。仅看包存在于仓库不能证明当前部署启用了策略。

## 4. 核心源码 C：顶层工具前 flush，等待后再检查取消

同一源码范围。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L1-L83 -->
```ts
  ctx.on('tools/execute', async (exec, next): Promise<ToolExecutionResult> => {
    if (exec.agent === undefined || exec.parent !== undefined) return next()
    await ctx.sessions.flush(exec.agent.session)
    if (exec.signal.aborted) return abortedBeforeDispatchResult()
    return next()
  })

  // Before each request, persist everything committed by the preceding step;
  // the first step's call is an intentional no-op beyond any prompt intake.
  ctx.on('agent/pre-step', async ({ agent }, next): Promise<PreStepDecision> => {
    await ctx.sessions.flush(agent.session)
    return next()
  })
```

### 逐段讲解

无 Agent 的调用和有 parent 的嵌套调用跳过本检查点，源码注释说明 nested dispatch 复用外层已持久的调用。这是明确的 scope，不是遗漏条件可以随意忽略。

flush 期间用户可能取消，所以 await 后检查 signal。取消返回 canonical aborted-before-dispatch 结果，不进入 next 工具体。否则已写下调用事实才允许副作用开始。

pre-step 还会在进入下一模型工作前持久化前一 Step 提交的批次。**这不是 Loop 在每个 turn/end 强制 fsync 的代码**，也不等于下游每个事件都单独写盘。

## 5. 仍然没有解决的 exactly-once

日志先持久化可以证明有调用意图，但进程可能在工具产生效果后、结果存储前死亡。恢复仍需要标记未知结果；不能因为有前置 checkpoint 就自动安全重试支付、发信或写外部系统。

物理尾部恢复、单写者 handle 与语义补齐属于其他层。读取接口契约可以理解职责，但证明实现正确还要检查后端与实际 crash 实验。

## 6. 实验与验收

装配 mock persistence，把 flush 放在闸门上；分别发模型请求与顶层工具，确认放行前 adapter/tool body 尚未调用。让 flush 拒绝，检查副作用调用次数为 0；在等待期间取消，再确认得到 aborted-before-dispatch。

单独测试无 sessionId、无 Agent、嵌套调用的分支，记录为什么跳过。必须在测试 profile 明确挂载本插件。

验收给出每个检查点的前提、保护的副作用、失败结果和未解决的窗口。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
