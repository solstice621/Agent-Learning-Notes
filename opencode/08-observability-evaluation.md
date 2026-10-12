# OpenCode 08｜EventFeed：一次编码与慢订阅者隔离

[总目录](../README.md) · P2（学习顺序） · 对照：[Codex](../codex/08-observability-evaluation.md) / [DSH](../dsh/08-observability-evaluation.md)

**固定源码：** `anomalyco/opencode@60a212c0769acd96b446acbadeb790486830f91d`。本篇由上一轮架构文档阅读进一步进入实际 `packages/server/src/event-feed.ts`。未运行负载测试。

## 1. 为什么这是 Agent Infra 问题

多个客户端同时观察 Agent 时，重复序列化会增加 CPU，慢客户端可能堆积事件。问题是怎样限制滞后，又不拖住健康观察者和任务发布。

## 2. 核心源码 A：没有订阅者时不编码，编码失败有明确处理

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

### 逐段讲解

公开事件过滤在序列化前；没有订阅者直接返回，所以 headless/空闲状态不需要为无人接收的 SSE 编码。

`render(event)` 位于后续 subscriber 循环之外，一次 publication 只产生一次 encoded 字符串，而不是每个客户端独立 schema/JSON 转换。

编码失败调用 fail，清理并失败当前订阅队列；不是只丢一条坏事件却让连接继续假装完整。函数外的 feed 仍可接受以后连接，这与一个慢订阅者超容量的处理不同。

## 3. 核心源码 B：队列满，只移除对应订阅者

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

## 4. 核心源码 C：订阅与清理绑定请求 Scope

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

## 5. Live feed 不是持久化日志

[事件流架构文档](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/event-stream-architecture.md) 解释独立连接滞后预算；[Session 契约](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/specs/v2/session.md) 另有 durable log/replay。

SSE 重连不自动补齐离线期间的业务事件；客户端应结合权威状态或日志恢复，不能用一个 live 队列承担 exactly-once 交付。

## 6. 实验与验收

先读并运行 [event-feed.test.ts](https://github.com/anomalyco/opencode/blob/60a212c0769acd96b446acbadeb790486830f91d/packages/server/test/event-feed.test.ts)，用容量为 1 的快慢两个订阅者验证独立溢出，再确认 encode 计数是一次。

性能实验固定事件数量，改变单条大小与订阅者数，记录编码 CPU、heap/RSS、队列水位、overflow 和健康连接延迟。不能把文档的编码微基准直接当网络吞吐或 Agent 任务性能。

验收是一份交付契约：谁过滤、谁编码、满了丢谁、怎样报告 gap、怎样恢复业务状态。原文许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
