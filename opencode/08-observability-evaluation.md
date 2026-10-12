# OpenCode 08｜为什么选择一次编码、每连接独立队列，而不是共享 PubSub？

[总目录](../README.md) · [设计索引](../DESIGN_INDEX.md) · [研究方法与证据](../RESEARCH_METHOD.md)

**设计研究版 v3｜研究日期：2026-10-12｜固定源码：`anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。** 下面先论证需求、反例、候选方案与代价，再展开真实源码。作者明示理由、文档契约和研究推导分别标注；上游运行实验仍为待运行。

## 1. 官方记录的真实目标与原先路径

架构文档说明原先每个 HTTP 订阅连接分别过滤、schema/JSON 编码和 SSE 封装；N 个客户端意味着同一事件重复执行 N 份相关工作。旧机制又已经保证慢客户端不会阻塞健康客户端。[A1]

因此目标不是泛泛的“性能更好”，而是：**减少重复编码，同时保留每个连接独立的滞后预算与失败域。** 必须同时满足这两个条件，才有理由评价候选方案。

## 2. 决策 O08-D1：为什么不使用一个共享的有界 PubSub？

官方明确考虑过共享 PubSub，并逐项解释其现成策略与所需语义的差异。[A1]

| 候选策略 | 哪项需求不自然满足 |
|---|---|
| bounded | 最慢订阅者可能阻塞共享发布者 |
| dropping | 共享容量满时可能为所有人拒绝该次发布 |
| sliding | 落后者跳过事件仍保持连接，可能静默失步 |
| unbounded | 缺少结构性积压上限 |
| 自定义共享 ring＋逐订阅者淘汰 | 能实现目标，但增加游标、作用域、容量回收和终态协议 |

当前每个连接保存的不是重新编码的一份内容，而是同一个不可变字符串的引用。因此进一步共享 ring 主要减少队列引用存储，不能再把它算成“消除了 N 份编码”。官方选择以一定引用槽位开销换取简单的单连接溢出语义，并明确只有测量证明剩余存储/offer 成本重要时才重新考虑。[A1][F1]

**推导：** 优化应先消除占主导的重复工作，再决定是否为剩余开销支付协议复杂度。共享结构不是天然比独立结构更高级；哪个故障应该影响谁，往往比容器名字更重要。

## 3. 决策 O08-D2：为什么宁可断开，也不默默跳过坏事件？

EventFeed 溢出只失败那个连接；编码失败则断开当前连接，跳过坏事件，仍允许后续连接和有效事件。[F1] 官方理由是避免让客户端带着不可见 gap 继续运行，同时避免单个坏事件永久毒死 feed。[A1]

这里是 volatile live feed，不是 durable Session replay。断开让客户端知道状态需要重新获取；它并不自动提供漏掉事件的重放保证。替代方案可以是显式 resync-required 控制消息、带 cursor 的 durable stream，或对状态型更新允许覆盖旧值；但它们必须改写交付契约，不能只把 dropping 换成 sliding 就假定等价。

**反例：** 如果事件只是每秒更新一次温度，旧值可被新值替代，滑动窗口很合理；如果事件是有顺序依赖的工具 lifecycle delta，静默丢一个开始或终态可能使 UI 永远停留在错误状态。要先分类事件语义再选择队列政策。

## 4. 两个容易被“有界”一词掩盖的成本

默认 4,096 是沿用的事件数阈值，不是实验证明的最优点，更不是 RSS 上限。frame 大小可变，HTTP、内核、代理与客户端缓冲都在它之外；即使队列只有一项，那一项也可能很大。[A1]

编码一次后，向每个连接 offer 和 socket 写仍与客户端数相关。无客户端时跳过编码、先过滤 internal events、同步注册再展示 connected 等细节，也影响空载成本、容量计数和启动 gap。[F1][A1]

官方微基准隔离的是重复编码边界，不是端到端网络栈、模型任务速度或客户端解码。不要将其百分比写成 Agent 总吞吐提升。本笔记没有重跑该 benchmark。

## 5. 验证、改变方案的条件与结论

本仓库机制实验用容量为 1 的抽象快/慢消费者验证独立失败，并用两个不同字节长度的 frame 说明事件数不约束字节量。这些测试不是实际 HTTP 或 Effect 测试。

**上游实验待运行：** 重跑 event-feed.test.ts，核对一次编码、多订阅者相同 frame、慢连接单独溢出、坏事件后新连接可用；再测 frame 分布、队列高水位、heap/RSS、每连接延迟与重连频率。[T1]

当连接规模和实测引用开销成为瓶颈时，再评估共享 ring；当事件天然为可覆盖状态时，再考虑滑动策略；当要求离线不丢事件时，增加 durable replay，而不是无限调大队列。

**应学会的决策：** 在性能优化中保留已有交付语义，明确哪里允许丢失、如何显式暴露 gap，以及什么证据会促使自己换一种实现。

[A1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/event-stream-architecture.md
[F1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L1-L100
[T1]: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/test/event-feed.test.ts

## 6. 核心源码与逐段核对

以下保留上一版的全部核心源码块及所在导读段；源码、缩进与定位范围不改写。前文设计研究补足其适用前提和反例，特别不能将收益概括误当作运行保证。

### 2. 核心源码 A：没有订阅者时不编码，编码失败有明确处理

源码：[`server/src/event-feed.ts`，L33–L81](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L33-L81)。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L33-L81 -->
```ts
  const publish = Effect.fnUntraced(function* (event: Event.Payload) {
    if (!isOpenCodeEvent(event)) return
    if (subscribers.size === 0) return
    const encoded = yield* Effect.try({
      try: () => render(event),
      catch: (cause) => new EncodingError({ eventID: event.id, eventType: event.type, cause }),
    }).pipe(
      Effect.catch((error) =>
        Effect.logError("Failed to encode public event", {
          eventID: error.eventID,
          eventType: error.eventType,
          cause: error.cause,
        }).pipe(Effect.andThen(fail(error)), Effect.as(undefined)),
      ),
    )
```

#### 逐段讲解

公开事件过滤在序列化前；没有订阅者直接返回，所以 headless/空闲状态不需要为无人接收的 SSE 编码。

`render(event)` 位于后续 subscriber 循环之外，一次 publication 只产生一次 encoded 字符串，而不是每个客户端独立 schema/JSON 转换。

编码失败调用 fail，清理并失败当前订阅队列；不是只丢一条坏事件却让连接继续假装完整。函数外的 feed 仍可接受以后连接，这与一个慢订阅者超容量的处理不同。

### 3. 核心源码 B：队列满，只移除对应订阅者

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L33-L81 -->
```ts
    if (encoded === undefined) return
    for (const subscriber of subscribers) {
      if (Queue.offerUnsafe(subscriber, encoded)) continue
      subscribers.delete(subscriber)
      Queue.failCauseUnsafe(subscriber, Cause.fail(new SubscriberOverflowError({ capacity })))
    }
```

offer 成功则继续下一个；失败立即从集合移除，并向该队列报告 SubscriberOverflow。没有在此 await 慢客户端腾空间，也没有为所有人丢同一帧。

每个队列存的是同一个 immutable string 值的引用，避免重复编码；但仍需 O(订阅者数) 的 offer 和各自网络发送，不能由此宣称端到端成本变成 O(1)。

文件默认容量为 4,096 个事件。**事件数不是内存字节上限**：frame 大小、HTTP/内核缓冲和消费者缓存仍需独立测量。

### 4. 核心源码 C：订阅与清理绑定请求 Scope

同一源码范围。

<!-- source: https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/src/event-feed.ts#L33-L81 -->
```ts
  return Service.of({
    subscribe: Effect.acquireRelease(
      Queue.dropping<string, Error>(capacity).pipe(Effect.tap((queue) => Effect.sync(() => subscribers.add(queue)))),
      (queue) =>
        Effect.sync(() => subscribers.delete(queue)).pipe(Effect.andThen(Queue.shutdown(queue)), Effect.asVoid),
    ).pipe(Effect.map(Stream.fromQueue)),
  })
```

acquire 创建并登记队列，release 删除并 shutdown。将资源生命期绑定 Scope，避免客户端已经断开但注册表还保留队列，继续消耗内存和 fan-out 成本。

这里的 dropping queue 被 offer 失败后的显式断连规则包裹；不能只看到 Queue.dropping 就解释成“静默跳过事件并一直保持连接”。执行语义由队列与周围协议共同决定。



## 7. 记录与验证边界

源码一致性检查只核对代码与固定版本匹配；设计结构检查只核对章节、决策编号和生成完整性，不证明论证正确。自建机制测试只验证抽象反例；没有编译或运行上游 Agent、真实模型、性能评测或 OS 沙箱测试。完整上一版保存在 [Git 历史](https://github.com/solstice621/Agent-Learning-Notes/blob/69577b8d1dc34b052090b43206faa9fcd2c597b2/opencode/08-observability-evaluation.md)。源码归属与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
