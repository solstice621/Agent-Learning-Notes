# DSH 07｜为什么用写入 Handle，而不是全局 append(id)？为什么在副作用前 Flush？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从作者记录的旧设计问题出发

Handle-based persistence 决策记录描述旧 seam 混合了全局 session 监听、发布后认领、缓存保留、崩溃修复与 revision 反复检查。缺少显式写入所有者，使跨进程写入权难以找到诚实的归属；持续外部写入还可能令读/check/read 循环无法收敛。[A1]

该记录标为 implemented，但其中某些后续层仍写作当时 planned。**本篇用它说明历史动机，不把历史计划直接当作固定提交所有后端的现状。** 当前 checkpoint 策略另以源码为依据。[F1]

## 2. 决策 D07-D1：为什么所有写入必须经过拥有生命周期的 Handle？

选择是由 Agent 生命周期取得 per-session handle，所有 read/append/flush/close 经由它；语义 crash repair 移到持有写权的 resume，普通读观察者只在内存平衡，不写回。[A1][D1]

| 作者记录或研究对照 | 取舍 |
|---|---|
| 全局监听器事后认领 session | 自动方便，但归属隐式、重载后可能猜错 |
| Handle 之外保留 append(id) | 方便调用，但绕过唯一写入权检查入口 |
| typed ReadHandle/WriteHandle 分拆 | 编译期可拒绝写只读句柄；作者记录因 seam 风格与类型复杂度未选 |
| 单一带 access 的 Handle | 所有权路径统一，操作在运行时拒绝；类型层面少一项保护 |

这里要明确：采用 runtime refusal 是作者在该代码库内的选择，不是 typed read/write handles 天生不好。不同语言与团队可能更值得支付类型区分成本。

**直接记录的代价：** 后端热重载可能使已有 handle 失效，写入需明确失败直到 Session 恢复，而不是偷偷重新认领；空 session 对其他进程可见还依赖 materialization/flush。[A1] 明确所有权提高可解释性，却可能降低“看上去无缝”的热更新体验。

## 3. 决策 D07-D2：为什么在模型/工具副作用边界前设置检查点？

当前 session-checkpoint-policy 用 async generator 先 flush 再创建下游模型流；对顶层工具在 body 前 flush，之后再检查取消；对 agent/pre-step 刷新前一步结果。带 parent 的嵌套工具复用外层边界，具体适用条件由代码检查。[F1]

**反事实：** 工具已经执行，调用事实却只在内存中；崩溃后既不知道发生了哪个动作，也无法配对结果。将调用/请求的已记录前缀先 durable，使恢复至少有行动意图。这个政策只有在对应插件实际挂载并且经过该链路时才成立，不能说“一切 DSH 请求都保证如此”。

| 检查点策略 | 优点 | 代价 |
|---|---|---|
| 每事件 fsync | 细粒度持久 | 写放大与热路径等待 |
| 仅结束刷盘 | 正常路径快 | 长任务故障丢失大 |
| 请求/工具前语义 fence | 保护关键行动依据 | 存储延迟和失败进入执行许可路径 |
| 外部事务工作流 | 可以组合更强恢复 | 成本与系统依赖更大 |

flush 失败时不继续模型/工具，是有意的 fail-closed。对于无副作用可重做批处理，这可能太保守；对于不可轻易撤销的行动，更清晰的执行证据往往值得等待。选择应与恢复目标匹配。

## 4. Handle 和检查点各自没有解决什么？

append 接纳、同 backend 可见、flush durable 是不同承诺。[D1] 即使调用事实已落盘，工具外部效果与结果落盘仍不是一个事务；崩溃后仍可能只有 call、没有 outcome。恢复补 unknown/interrupted 不是副作用回滚。

单写者 handle 也不自动覆盖租约丢失后的旧 Worker；跨进程机制需要具体 backend 证据，跨节点还可能需 fencing、存储一致性与执行端校验。历史 ADR 的“下一层计划”不能当作当前已验证能力。

语义修复移出存储，减少存储对 Agent 状态机的耦合；代价是所有 resume/observer 必须遵守修复与写入权限分工。一个读取会话的 UI 不应该因为发现未闭合 Turn 就修改仍有活 writer 的日志。

## 5. 验证与学习结果

**上游实验待运行：** 双 write open、只读写拒绝、close 后 reopen；模型/工具前 flush 拒绝时确认下游未调用；取消在 flush 期间到达时确认 body 不启动；半个 Turn 的 read-only 与 write resume 对照；插件未挂载时单独记录没有这些 checkpoint 保证。

本仓库机制实验只验证“存在 WAL intent 仍可能结果未知”，不模拟实际 fsync 或租约。

读完应能说明：为什么写权限需要一个唯一入口和所有者，为什么关键边界宁可停止也不无日志继续，为什么即使这样仍不能承诺外部效果 exactly-once。

[A1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/.agents/notes/implemented/architecture/2026-08-27-handle-based-session-persistence.md
[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/session/session-checkpoint-policy/src/index.ts#L1-L100
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/persistence.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：先 flush，再构造下游模型流

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

#### 逐段讲解

返回的是异步生成器，真正被消费时先 await flush，之后才调用 next 并委派其 stream。若 flush 拒绝，下游 adapter 不会由这条包装路径启动。

区别在于 next 被延迟调用，而不只是把已经启动的网络请求结果延迟展示。**设计分析：** 若先构造会立即产生副作用的下游操作，再等待日志提交，崩溃时可能出现请求已经发出、重建依据却没有持久化的窗口。

这里不能推导 provider 端没有其他独立副作用，也不能证明 JSONL 后端每次具体使用什么系统调用；策略层只建立调用顺序与契约。

### 3. 核心源码 B：只有能关联活 Session 的调用套检查点

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

### 4. 核心源码 C：顶层工具前 flush，等待后再检查取消

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

#### 逐段讲解

无 Agent 的调用和有 parent 的嵌套调用跳过本检查点，源码注释说明 nested dispatch 复用外层已持久的调用。这是明确的 scope，不是遗漏条件可以随意忽略。

flush 期间用户可能取消，所以 await 后检查 signal。取消返回 canonical aborted-before-dispatch 结果，不进入 next 工具体。否则已写下调用事实才允许副作用开始。

pre-step 还会在进入下一模型工作前持久化前一 Step 提交的批次。**这不是 Loop 在每个 turn/end 强制 fsync 的代码**，也不等于下游每个事件都单独写盘。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/dsh/07-persistence-reliability.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
