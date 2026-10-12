# DSH 02｜Session：规范事件与派生模型历史

[总目录](../README.md) · P0 · 对照：[Codex](../codex/02-context-session.md) / [OpenCode](../opencode/02-context-session.md)

**固定源码：** `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。本篇新增精读 `packages/core/session/src/index.ts` 的真实 append/commit/deriveMessages 实现。代码是原文，不是从文档重写的事件溯源示例。未运行实验。

## 1. 关键问题

事件日志是事实源，但不是每条事件都变成模型消息。日志追加顺序、当前 Surface 顺序、请求头和派生历史是不同视图。下面看实际实现怎样保证载荷稳定、避免重入以及维护派生缓存。

## 2. 核心源码 A：写入前先快照、校验并冻结

源码：[`core/session/src/index.ts`，L800–L827](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L800-L827)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L800-L827 -->
```ts
    const dataSnapshot = snapshotJsonValue(data)
    if (dataSnapshot === undefined) {
      throw new Error(`session event "${type}" carries non-JSON-serializable data`)
    }
    const surfaceMetadataSnapshot = snapshotJsonValue(surfaceMetadata)
    if (surfaceMetadataSnapshot === undefined) {
      throw new Error(`session event "${type}" carries non-JSON-serializable surface metadata`)
    }
    const entry = this.publicationEntry()
    const event = deepFreeze({
      type,
      seq: SessionSeq(this.log.length),
      time: Date.now(),
      data: dataSnapshot,
      ...(surfaceMetadataSnapshot as { surfaceOp?: unknown; sourceEventSeqs?: unknown }),
    } as unknown as SessionEvent<T>)
    validateSessionEventData(event, `session event "${type}" at seq ${event.seq}`)
    this.commit(event as SessionEvent, entry)
    return event
```

### 逐段讲解

数据和 surface metadata 分别快照，不能序列化就拒绝，而不是等存储写入时才悄悄丢字段。外部调用者后来修改原 data 对象，不应改变已经接纳的事件。

seq 取当前 log.length，再冻结 envelope 和 data，完成事件级校验后才 commit。TypeScript 的类型断言不是运行时校验替代品；这里明确调用 validateSessionEventData。

**分析：** 可重放系统必须先固定“究竟发生了什么”，不能把仍可变的对象指针当历史。此处还没有承诺磁盘持久性。

## 3. 核心源码 B：提交与观察者通知有边界

源码：[`index.ts`，L856–L897](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L856-L897)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L856-L897 -->
```ts
  private commit(event: SessionEvent, entry: SessionEntry | undefined): void {
    this.surfaceManager.validateNext(event)

    if (entry !== undefined) entry.appending = true
    try {
      let callbacks: SessionCallback[] | undefined
      const callbackArgs: unknown[] = [this, event]
      if (entry !== undefined) {
        callbacks = collectSessionCallbacks(entry.emitCtx, [entry.carrier, 'session/event', ...callbackArgs])
      }
      this.log.push(event)
      this.eventsSnapshot = undefined
      if (callbacks !== undefined && entry !== undefined) {
        invokeContainedSessionObservers(entry.emitCtx, 'session/event', entry.id, callbackArgs, callbacks)
      }
    } finally {
      if (entry !== undefined) {
        entry.appending = false
        if (entry.detachRequested && !entry.announcing) entry.detach()
      }
    }
  }
```

先让 SurfaceManager 检查 next event，再进入 publication 的 appending 区间。入 log 后使 eventsSnapshot 缓存失效，然后通知观察者；finally 解除 appending，并处理延迟 detach。

前面的 publicationEntry 会拒绝发布期间的重入 append。**设计分析：** 如果观察者在当前事件尚未完成发布时任意追加，可能破坏顺序与同一 publication 的假设；这里选择明确拒绝，而不是靠调用者自觉。

观察者 containment 和 storage flush 仍是不同职责。不能因为 callback 已被通知，就认为导出、刷盘或远端交付都成功。

## 4. 核心源码 C：Surface 变化决定缓存能否增量复用

源码：[`index.ts`，L955–L1015](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L955-L1015)。

<!-- source: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L955-L1015 -->
```ts
  deriveMessages(): Message[] {
    const surface = this.surface
    const nodes = surface.nodes
    const generation = surface.contentGeneration
    if (generation !== this.derivedGeneration) {
      this.derived = []
      this.derivedNodes = 0
      this.derivedGeneration = generation
    }
    for (const seq of nodes.slice(this.derivedNodes)) {
      // Surface sequences are built from this.log — seq is always a valid
      // index by construction. The non-null assertion expresses that invariant.
      // oxlint-disable-next-line typescript/no-non-null-assertion
      const msg = this.deriveEventMessage(this.log[seq]!)
      // A surface node is one of the five message-producing types, but an
      // empty-content assistant/message (a max-tokens step that hosts only
      // usage) derives to null and must not enter the transcript.
      if (msg) this.derived.push(msg)
    }
    this.derivedNodes = nodes.length
    return [...this.derived]
  }
```

### 逐段讲解

generation 不变时只处理新增 Surface nodes；发生内容替换或投影变化导致 generation 改变时，丢弃派生缓存重建。若只看 log 是否增长，就无法正确处理“追加一条 replacement 事件改变旧位置”的情况。

遍历顺序来自 surface.nodes，不是直接遍历全部 log，因此 log-only 事件不会自动进入模型 history。某些节点还可能派生 null，例如只携带 usage 的空 assistant 内容。

返回 `[...this.derived]` 复制外层数组；附近契约说明内部 Message 对象共享且冻结。因此调用者的数组不会随后被追加，也不能借共享 Message 改写历史。拷贝数组不等于每次深拷贝所有消息。

## 5. 与压缩的联系与实验

[Compaction 契约](https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/compaction.md) 用日志记录 replacement，而不改写旧事件。Surface 位置可能与 seq 数值顺序不同，不能按 seq 区间随便删消息。

实验：先追加普通消息，再加入 log-only event，再做一次 Surface replacement；每步记录 log、nodes、generation 与 deriveMessages。最后修改调用者原 data 和返回数组，检查已接纳消息保持不变。全程用合成内容。

验收应能解释事件事实与模型视图的分离、为什么 generation 影响缓存、为什么 append-only 仍可改变活动上下文。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
