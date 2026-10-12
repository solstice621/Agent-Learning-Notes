# DSH 02｜为什么采用事件日志＋Surface，以及增量缓存没有消除哪些成本？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 从可变 messages 数组推导需求

若只需当前上下文，一个可变数组最直接：压缩时 splice，更新指令时覆盖。若还要解释过去模型看到了什么、恢复失败尝试、fork 历史并让不同消费者读取同一事实，直接覆盖会抹掉改变发生的原因。

DSH Session 使用冻结的事件作为事实，Surface 管理当前模型可见节点，deriveMessages 从 Surface 派生消息。[F1][D1] 这是一种为可重建性付出存储和投影复杂度的选择，不是所有聊天系统都应该使用 Event Sourcing。

## 2. 决策 D02-D1：为什么事实日志与活动上下文分开？

**反事实：** 压缩后直接将历史替换成摘要，随后模型做出错误决策。维护者无法判断错误来自原始工具结果、摘要丢约束、指令变化还是模型决策。保存替换事实与旧事件，使这些路径有可审计依据。

| 方案 | 适用价值 | 需要承受什么 |
|---|---|---|
| 原地修改 messages | 小型当前态应用 | 过去视图和变更原因消失 |
| 每次保存完整请求快照 | 易审计实际输入 | 重复数据大、索引和身份关联复杂 |
| 事件＋活动投影 | 复用事实、表达替换过程 | 投影版本、迁移、缓存失效和重建成本 |
| 仅摘要加外部原文引用 | 阅读型长任务 | 引用可用性、权限和精确请求重建仍需设计 |

append 先 snapshot/validate/freeze，再进入 log 并通知观察者。[F1] **推导：** 如果历史只保存调用者对象引用，调用者事后修改原对象就会悄悄“改写过去”；快照与冻结稳定的是已接纳事实，不是磁盘持久性。`this.log.push` 的 commit 不能当作 fsync。

Surface 顺序也不一定等于事件 seq 数值顺序。新的摘要拥有较大 seq，却可能替换到较早位置；按数值区间删节点会误解多次压缩。Compaction 契约要求理解位置范围与工具配对。[D2]

## 3. 决策 D02-D2：为什么增量投影仍然返回数组快照？

deriveMessages 在 contentGeneration 不变时只处理新增 nodes；generation 变化时重建；最后 `return [...this.derived]`。[F1] 返回新外层数组，避免后续 append 改变调用者已经拿到的快照；内部冻结 Message 可共享，避免重复深拷贝所有内容。

**本轮纠正一个容易误读的复杂度：** 投影计算可为 O(新增节点)，但创建完整返回数组仍需 O(当前消息数) 次引用复制。若每加入一条消息都请求完整数组，总引用复制量可达到 1+2+…+N，即 O(N²)。这是对特定调用模式的分析，不是宣称 DSH 整个任务性能必然平方增长；调用频率、序列化和底层 Surface 访问还会影响实际成本。

| 返回结构 | 好处 | 新的约束 |
|---|---|---|
| 直接返回可变内部数组 | 少一次复制 | 调用方观察到后续变化或修改缓存 |
| 完整深拷贝 | 所有权简单 | 消息内容复制开销大 |
| 新数组＋共享冻结消息 | 稳定外层快照、内容可复用 | O(N) 引用复制仍存在 |
| 持久化序列/游标/增量接口 | 避免频繁完整快照 | 消费方协议、版本和迭代失效更复杂 |

因此不能仅因存在缓存就声称“上下文读取是 O(delta)”。也不能仅看到数组复制就认定应改为游标：模型请求常常仍需要完整序列化，优化返回结构可能不是主瓶颈。

## 4. 选择 Event Sourcing 的真实代价

事件不可变使修正通过新事实表达，而不是删除旧错误；这需要 schema 兼容和明确未知事件政策。多消费者共享事件也意味着一个 cardinality 改动可能要迁移同 Session 引用和 fork cut。若所有旧日志都可丢弃，这些约束反而可能没有收益。

发布期间拒绝 reentrant append 是另一种明确选择。[F1] 它保护当前 publication 的顺序假设，却限制了观察者直接写入；插件需要在合适边界提交新事实，而不能随意递归修改。事件驱动不是自动没有控制流，它把控制流移进了发布协议。

## 5. 验证、反例与学习结果

本仓库机制实验分别计数增量投影和数组引用复制，验证两种成本并不相同；也测试替换后只按“log 增长”无法维持旧投影。它不运行 DSH 源码，不提供真实性能数字。

**上游实验待运行：** 修改原输入对象、返回数组和返回的 Message，检查冻结/快照边界；多次 Surface replacement 后比对实际模型历史；对长历史分别量投影、数组构建、序列化、网络与模型耗时。

应带走的判断：稳定事实与当前视图是否值得分离？缓存优化了哪一项工作，剩余工作在哪里？如果业务只需要最后状态、不需要历史解释，原地更新和简单快照可能更合适。

[F1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/packages/core/session/src/index.ts#L790-L1015
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/session.md
[D2]: https://github.com/deepseek-ai/deepseek-harness/blob/d743267388641bc76f17c45ce8b4c231aed1d32c/docs/subsystems/compaction.md

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：写入前先快照、校验并冻结

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

#### 逐段讲解

数据和 surface metadata 分别快照，不能序列化就拒绝，而不是等存储写入时才悄悄丢字段。外部调用者后来修改原 data 对象，不应改变已经接纳的事件。

seq 取当前 log.length，再冻结 envelope 和 data，完成事件级校验后才 commit。TypeScript 的类型断言不是运行时校验替代品；这里明确调用 validateSessionEventData。

**分析：** 可重放系统必须先固定“究竟发生了什么”，不能把仍可变的对象指针当历史。此处还没有承诺磁盘持久性。

### 3. 核心源码 B：提交与观察者通知有边界

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

### 4. 核心源码 C：Surface 变化决定缓存能否增量复用

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

#### 逐段讲解

generation 不变时只处理新增 Surface nodes；发生内容替换或投影变化导致 generation 改变时，丢弃派生缓存重建。若只看 log 是否增长，就无法正确处理“追加一条 replacement 事件改变旧位置”的情况。

遍历顺序来自 surface.nodes，不是直接遍历全部 log，因此 log-only 事件不会自动进入模型 history。某些节点还可能派生 null，例如只携带 usage 的空 assistant 内容。

返回 `[...this.derived]` 复制外层数组；附近契约说明内部 Message 对象共享且冻结。因此调用者的数组不会随后被追加，也不能借共享 Message 改写历史。拷贝数组不等于每次深拷贝所有消息。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/dsh/02-context-session.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
